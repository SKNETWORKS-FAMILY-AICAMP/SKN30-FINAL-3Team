from datetime import datetime

from sqlalchemy import or_
from sqlmodel import Session, col, select

from domain.authentication.models import AppUser, Brokerage, UserSession


def find_active_user(session: Session, brokerage_id: int, login_id: str) -> AppUser | None:
    statement = select(AppUser).where(
        AppUser.brokerage_id == brokerage_id,
        AppUser.login_id == login_id,
        col(AppUser.is_active).is_(True),
    )
    return session.exec(statement).first()


def find_user_by_id(session: Session, brokerage_id: int, user_id: int) -> AppUser | None:
    statement = select(AppUser).where(
        AppUser.brokerage_id == brokerage_id,
        AppUser.id == user_id,
    )
    return session.exec(statement).first()


def find_user_session_by_hash(session: Session, session_token_hash: str) -> UserSession | None:
    statement = select(UserSession).where(UserSession.session_token_hash == session_token_hash)
    return session.exec(statement).first()


def add_user_session(session: Session, user_session: UserSession) -> UserSession:
    session.add(user_session)
    session.flush()
    return user_session


def find_brokerage_by_name(session: Session, name: str) -> Brokerage | None:
    return session.exec(select(Brokerage).where(Brokerage.name == name)).first()


def add_brokerage(session: Session, brokerage: Brokerage) -> Brokerage:
    session.add(brokerage)
    session.flush()
    return brokerage


def add_user(session: Session, user: AppUser) -> AppUser:
    session.add(user)
    session.flush()
    return user


def expired_sessions(session: Session, now: datetime) -> list[UserSession]:
    statement = select(UserSession).where(
        or_(
            col(UserSession.absolute_expires_at) <= now,
            col(UserSession.idle_expires_at) <= now,
            col(UserSession.revoked_at).is_not(None),
        )
    )
    return list(session.exec(statement).all())
