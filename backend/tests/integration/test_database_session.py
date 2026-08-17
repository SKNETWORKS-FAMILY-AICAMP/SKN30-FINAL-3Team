import os

import pytest
from sqlalchemy import text
from sqlmodel import Session, create_engine


@pytest.mark.skipif(
    not os.getenv("TEST_DB_URL"),
    reason="TEST_DB_URL is required for PostgreSQL integration tests",
)
def test_postgresql_session_executes_query() -> None:
    engine = create_engine(os.environ["TEST_DB_URL"], pool_pre_ping=True)

    with Session(engine) as session:
        assert session.execute(text("SELECT 1")).scalar_one() == 1
