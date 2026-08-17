from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Session

from core.config import AppEnvironment, Config
from core.errors import ConfigurationError
from domain.authentication.models import AppUser, Brokerage, UserRole
from domain.authentication.repository import (
    add_brokerage,
    add_user,
    expired_sessions,
    find_active_user,
    find_brokerage_by_name,
)

DISABLED_PASSWORD_HASH = "!development-login-disabled!"


def create_development_user(
    db: Session,
    config: Config,
    brokerage_name: str,
    login_id: str,
    display_name: str,
    role: UserRole,
) -> AppUser:
    if config.app.environment is not AppEnvironment.LOCAL:
        raise ConfigurationError("development users can only be created in local environment")

    brokerage = find_brokerage_by_name(db, brokerage_name)
    if brokerage is None:
        brokerage = add_brokerage(db, Brokerage(name=brokerage_name))
    if brokerage.id is None:
        raise RuntimeError("brokerage identity was not generated")

    existing = find_active_user(db, brokerage.id, login_id)
    if existing is not None:
        db.commit()
        return existing

    user = add_user(
        db,
        AppUser(
            brokerage_id=brokerage.id,
            login_id=login_id,
            password_hash=DISABLED_PASSWORD_HASH,
            display_name=display_name,
            role=role.value,
        ),
    )
    db.commit()
    db.refresh(user)
    return user


def purge_expired_sessions(db: Session, now: datetime | None = None) -> int:
    targets = expired_sessions(db, now or datetime.now(UTC))
    for target in targets:
        db.delete(target)
    db.commit()
    return len(targets)
