from collections.abc import Iterator

from fastapi import Request
from sqlmodel import Session

from core.config import Config


def get_app_config(request: Request) -> Config:
    return request.app.state.config


def get_db_session(request: Request) -> Iterator[Session]:
    with Session(request.app.state.db_engine) as session:
        try:
            yield session
        except Exception:
            session.rollback()
            raise
