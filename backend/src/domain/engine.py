from sqlalchemy.engine import Engine
from sqlmodel import create_engine

from core.config import Config


def create_database_engine(config: Config) -> Engine:
    return create_engine(
        config.db.url.get_secret_value(),
        pool_pre_ping=True,
        pool_size=config.db.pool.size,
        max_overflow=config.db.pool.max_overflow,
        pool_timeout=config.db.pool.timeout_seconds,
    )
