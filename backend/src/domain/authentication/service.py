from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlmodel import Session

from core.config import Config
from core.errors import AuthenticationError
from domain.authentication.models import (
    AppUser,
    AuthenticationContext,
    CurrentUser,
    UserRole,
    UserSession,
)
from domain.authentication.repository import (
    add_user_session,
    find_active_user,
    find_user_by_id,
    find_user_session_by_hash,
)


@dataclass(frozen=True)
class IssuedSession:
    session_token: str
    csrf_token: str
    user: CurrentUser


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _current_user(user_id: int, user: AppUser) -> CurrentUser:
    return CurrentUser(
        id=user_id,
        brokerage_id=user.brokerage_id,
        login_id=user.login_id,
        display_name=user.display_name,
        role=UserRole(user.role),
    )


def issue_development_session(
    db: Session, config: Config, now: datetime | None = None
) -> IssuedSession:
    development = config.auth.development
    if not development.enabled or development.brokerage_id is None or not development.login_id:
        raise AuthenticationError(
            "DEVELOPMENT_AUTH_DISABLED", "development authentication is disabled"
        )

    user = find_active_user(db, development.brokerage_id, development.login_id)
    if user is None or user.id is None:
        raise AuthenticationError("DEVELOPMENT_USER_NOT_FOUND", "development user was not found")

    issued_at = now or datetime.now(UTC)
    session_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    absolute_expires_at = issued_at + timedelta(
        minutes=config.auth.session.absolute_timeout_minutes
    )
    idle_expires_at = min(
        issued_at + timedelta(minutes=config.auth.session.idle_timeout_minutes),
        absolute_expires_at,
    )
    add_user_session(
        db,
        UserSession(
            brokerage_id=user.brokerage_id,
            user_id=user.id,
            session_token_hash=hash_token(session_token),
            csrf_token_hash=hash_token(csrf_token),
            created_at=issued_at,
            last_seen_at=issued_at,
            idle_expires_at=idle_expires_at,
            absolute_expires_at=absolute_expires_at,
        ),
    )
    user.last_login_at = issued_at
    db.add(user)
    db.commit()
    return IssuedSession(
        session_token=session_token,
        csrf_token=csrf_token,
        user=_current_user(user.id, user),
    )


def authenticate_session(
    db: Session,
    config: Config,
    session_token: str,
    now: datetime | None = None,
) -> AuthenticationContext:
    checked_at = now or datetime.now(UTC)
    stored_session = find_user_session_by_hash(db, hash_token(session_token))
    if stored_session is None or stored_session.id is None:
        raise AuthenticationError("UNAUTHENTICATED", "authentication is required")
    if stored_session.revoked_at is not None:
        raise AuthenticationError("UNAUTHENTICATED", "authentication is required")
    if (
        stored_session.idle_expires_at <= checked_at
        or stored_session.absolute_expires_at <= checked_at
    ):
        stored_session.revoked_at = checked_at
        stored_session.revoked_reason = "EXPIRED"
        db.add(stored_session)
        db.commit()
        raise AuthenticationError("SESSION_EXPIRED", "the session has expired")

    user = find_user_by_id(db, stored_session.brokerage_id, stored_session.user_id)
    if user is None or user.id is None or not user.is_active:
        raise AuthenticationError("UNAUTHENTICATED", "authentication is required")

    update_interval = timedelta(seconds=config.auth.session.last_seen_update_seconds)
    if checked_at - stored_session.last_seen_at >= update_interval:
        stored_session.last_seen_at = checked_at
        stored_session.idle_expires_at = min(
            checked_at + timedelta(minutes=config.auth.session.idle_timeout_minutes),
            stored_session.absolute_expires_at,
        )
        db.add(stored_session)
        db.commit()

    return AuthenticationContext(
        user=_current_user(user.id, user),
        session_id=stored_session.id,
        csrf_token_hash=stored_session.csrf_token_hash,
    )


def validate_csrf(context: AuthenticationContext, csrf_token: str | None) -> str:
    if not csrf_token or not hmac.compare_digest(context.csrf_token_hash, hash_token(csrf_token)):
        raise AuthenticationError("INVALID_CSRF_TOKEN", "the CSRF token is invalid")
    return csrf_token


def revoke_session(
    db: Session,
    session_token: str,
    reason: str = "USER_LOGOUT",
    now: datetime | None = None,
) -> None:
    stored_session = find_user_session_by_hash(db, hash_token(session_token))
    if stored_session is None or stored_session.revoked_at is not None:
        return
    stored_session.revoked_at = now or datetime.now(UTC)
    stored_session.revoked_reason = reason
    db.add(stored_session)
    db.commit()
