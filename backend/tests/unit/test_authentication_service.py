from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from sqlmodel import Session

import domain.authentication.service as authentication_service
from core.errors import AuthenticationError
from domain.authentication.models import (
    AppUser,
    AuthenticationContext,
    CurrentUser,
    UserRole,
    UserSession,
)
from domain.authentication.service import hash_token, issue_development_session, validate_csrf


class RecordingSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0

    def add(self, value: object) -> None:
        self.added.append(value)

    def commit(self) -> None:
        self.commits += 1


def context_for(csrf_token: str) -> AuthenticationContext:
    return AuthenticationContext(
        user=CurrentUser(
            id=1,
            brokerage_id=1,
            login_id="developer",
            display_name="Developer",
            role=UserRole.OWNER,
        ),
        session_id=1,
        csrf_token_hash=hash_token(csrf_token),
    )


def test_hash_token_is_deterministic_without_storing_plaintext() -> None:
    digest = hash_token("secret-session-token")

    assert digest == hash_token("secret-session-token")
    assert digest != "secret-session-token"
    assert len(digest) == 64


def test_valid_csrf_token_is_accepted() -> None:
    validate_csrf(context_for("csrf-token"), "csrf-token")


def test_invalid_csrf_token_is_rejected() -> None:
    with pytest.raises(AuthenticationError) as error:
        validate_csrf(context_for("csrf-token"), "wrong-token")

    assert error.value.code == "INVALID_CSRF_TOKEN"


def test_dev_session_uses_thirty_minute_idle_and_twelve_hour_absolute_expiry(
    make_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = make_config(
        {
            "APP_ENV": "dev",
            "DB_TARGET": "development",
            "AUTH_DEVELOPMENT_ENABLED": "true",
            "AUTH_DEVELOPMENT_BROKERAGE_ID": "3",
            "AUTH_DEVELOPMENT_LOGIN_ID": "developer",
            "AUTH_SESSION_IDLE_TIMEOUT_MINUTES": "30",
            "AUTH_SESSION_ABSOLUTE_TIMEOUT_MINUTES": "720",
        }
    )
    user = AppUser(
        id=7,
        brokerage_id=3,
        login_id="developer",
        password_hash="!development-login-disabled!",
        display_name="Developer",
        role=UserRole.OWNER.value,
    )
    issued_at = datetime(2026, 8, 27, 1, 2, 3, tzinfo=UTC)
    stored_sessions: list[UserSession] = []
    db = RecordingSession()

    monkeypatch.setattr(authentication_service, "find_active_user", lambda *_args: user)

    def capture_session(_db: Session, stored_session: UserSession) -> UserSession:
        stored_sessions.append(stored_session)
        return stored_session

    monkeypatch.setattr(authentication_service, "add_user_session", capture_session)

    issued = issue_development_session(cast(Session, db), config, now=issued_at)

    assert issued.user.id == 7
    assert len(stored_sessions) == 1
    stored = stored_sessions[0]
    assert stored.idle_expires_at == issued_at + timedelta(minutes=30)
    assert stored.absolute_expires_at == issued_at + timedelta(hours=12)
    assert stored.session_token_hash == hash_token(issued.session_token)
    assert stored.csrf_token_hash == hash_token(issued.csrf_token)
    assert user.last_login_at == issued_at
    assert db.commits == 1


@pytest.fixture
def active_session(monkeypatch: pytest.MonkeyPatch):
    """Control only repository I/O and time; exercise the real session policy."""
    now = datetime(2026, 9, 9, 3, 0, tzinfo=UTC)
    stored = UserSession(
        id=11,
        brokerage_id=3,
        user_id=7,
        session_token_hash=hash_token("session-token"),
        csrf_token_hash=hash_token("csrf-token"),
        created_at=now - timedelta(hours=1),
        last_seen_at=now,
        idle_expires_at=now + timedelta(minutes=30),
        absolute_expires_at=now + timedelta(hours=12),
    )
    user = AppUser(
        id=7,
        brokerage_id=3,
        login_id="developer",
        password_hash="!disabled!",
        display_name="Developer",
        role=UserRole.STAFF.value,
    )

    def find_session(_db, token_hash):
        assert token_hash == stored.session_token_hash
        return stored

    def find_user(_db, brokerage_id, user_id):
        assert (brokerage_id, user_id) == (stored.brokerage_id, stored.user_id)
        return user

    monkeypatch.setattr(authentication_service, "find_user_session_by_hash", find_session)
    monkeypatch.setattr(authentication_service, "find_user_by_id", find_user)
    return now, stored, user, RecordingSession()


@pytest.mark.parametrize("state", ["missing", "unpersisted", "revoked"])
def test_missing_or_revoked_session_is_rejected_without_writes(
    active_session, config, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    now, stored, _user, db = active_session
    if state == "missing":
        monkeypatch.setattr(authentication_service, "find_user_session_by_hash", lambda *_: None)
    elif state == "unpersisted":
        stored.id = None
    else:
        stored.revoked_at = now - timedelta(seconds=1)
        stored.revoked_reason = "USER_LOGOUT"

    with pytest.raises(AuthenticationError) as error:
        authentication_service.authenticate_session(cast(Session, db), config, "session-token", now)

    assert error.value.code == "UNAUTHENTICATED"
    assert db.added == []
    assert db.commits == 0


@pytest.mark.parametrize("deadline", ["idle_expires_at", "absolute_expires_at"])
@pytest.mark.parametrize("offset_seconds", [0, -1], ids=["exact-deadline", "past-deadline"])
def test_expired_session_is_revoked_and_committed_before_rejection(
    active_session, config, deadline: str, offset_seconds: int
) -> None:
    now, stored, _user, db = active_session
    setattr(stored, deadline, now + timedelta(seconds=offset_seconds))

    with pytest.raises(AuthenticationError) as error:
        authentication_service.authenticate_session(cast(Session, db), config, "session-token", now)

    assert error.value.code == "SESSION_EXPIRED"
    assert stored.revoked_at == now
    assert stored.revoked_reason == "EXPIRED"
    assert db.added == [stored]
    assert db.commits == 1


@pytest.mark.parametrize("state", ["missing", "unpersisted", "inactive"])
def test_session_does_not_authorize_a_removed_or_inactive_user(
    active_session, config, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    now, _stored, user, db = active_session
    if state == "missing":
        monkeypatch.setattr(authentication_service, "find_user_by_id", lambda *_: None)
    elif state == "unpersisted":
        user.id = None
    else:
        user.is_active = False

    with pytest.raises(AuthenticationError) as error:
        authentication_service.authenticate_session(cast(Session, db), config, "session-token", now)

    assert error.value.code == "UNAUTHENTICATED"
    assert db.added == []
    assert db.commits == 0


@pytest.mark.parametrize("elapsed_seconds", [299, 300, 301])
@pytest.mark.parametrize("remaining_minutes", [10, 60], ids=["absolute-cap", "idle-extension"])
def test_activity_updates_at_interval_and_never_extends_absolute_expiry(
    active_session, make_config, elapsed_seconds: int, remaining_minutes: int
) -> None:
    now, stored, user, db = active_session
    config = make_config(
        {
            "AUTH_SESSION_IDLE_TIMEOUT_MINUTES": "30",
            "AUTH_SESSION_LAST_SEEN_UPDATE_SECONDS": "300",
        }
    )
    stored.last_seen_at = now - timedelta(seconds=elapsed_seconds)
    stored.absolute_expires_at = now + timedelta(minutes=remaining_minutes)
    stored.idle_expires_at = now + timedelta(minutes=5)
    original_seen, original_idle = stored.last_seen_at, stored.idle_expires_at

    result = authentication_service.authenticate_session(
        cast(Session, db), config, "session-token", now
    )

    assert result.session_id == stored.id
    assert result.csrf_token_hash == stored.csrf_token_hash
    assert result.user.id == user.id
    assert result.user.brokerage_id == user.brokerage_id
    assert result.user.role == UserRole.STAFF
    assert stored.absolute_expires_at == now + timedelta(minutes=remaining_minutes)
    if elapsed_seconds < 300:
        assert stored.last_seen_at == original_seen
        assert stored.idle_expires_at == original_idle
        assert db.added == []
        assert db.commits == 0
    else:
        assert stored.last_seen_at == now
        assert stored.idle_expires_at == now + timedelta(minutes=min(30, remaining_minutes))
        assert db.added == [stored]
        assert db.commits == 1
