from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session, create_engine

from core.config import Config
from domain.authentication.dependencies import get_current_user, require_csrf
from domain.authentication.models import CurrentUser, UserRole
from domain.session import get_db_session
from main import create_app

requires_database = pytest.mark.skipif(
    not os.getenv("TEST_DB_URL"),
    reason="TEST_DB_URL is required for PostgreSQL integration tests",
)


@contextmanager
def ledger_client(config: Config) -> Iterator[tuple[TestClient, Session, int, int]]:
    """실제 PostgreSQL에 붙되 테스트 종료 시 전부 롤백하는 클라이언트."""
    engine = create_engine(os.environ["TEST_DB_URL"])
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")

    brokerage_id = session.execute(
        text("INSERT INTO brokerage (name) VALUES ('API 검증 사무소') RETURNING id")
    ).scalar_one()
    user_id = session.execute(
        text(
            "INSERT INTO app_user (brokerage_id, login_id, password_hash, display_name, role)"
            " VALUES (:brokerage_id, 'api-test', 'unused', '검증', 'OWNER') RETURNING id"
        ),
        {"brokerage_id": brokerage_id},
    ).scalar_one()

    app = create_app(config=config, readiness_probe=lambda request: True)
    app.dependency_overrides[get_db_session] = lambda: session
    app.dependency_overrides[require_csrf] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=user_id,
        brokerage_id=brokerage_id,
        login_id="api-test",
        display_name="검증",
        role=UserRole.OWNER,
    )

    try:
        with TestClient(app) as client:
            yield client, session, brokerage_id, user_id
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def create_complex(client: TestClient, session: Session, brokerage_id: int, name: str) -> int:
    return session.execute(
        text("INSERT INTO property_complex (brokerage_id, name) VALUES (:b, :n) RETURNING id"),
        {"b": brokerage_id, "n": name},
    ).scalar_one()


def create_unit(client: TestClient, complex_id: int, **overrides: object) -> dict:
    payload = {"complex_id": complex_id, "unit_number": "101"}
    payload.update(overrides)
    response = client.post("/api/v1/property-units", json=payload)
    assert response.status_code == 201, response.text
    return response.json()
