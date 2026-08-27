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
