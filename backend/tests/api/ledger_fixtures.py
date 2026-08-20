from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session, create_engine

from core.config import Config
from domain.authentication.dependencies import (
    get_authentication_context,
    get_current_user,
    require_csrf,
)
from domain.authentication.models import AuthenticationContext, CurrentUser, UserRole
from domain.authentication.service import hash_token
from domain.session import get_db_session
from main import create_app

requires_database = pytest.mark.skipif(
    not os.getenv("TEST_DB_URL"),
    reason="TEST_DB_URL is required for PostgreSQL integration tests",
)


@contextmanager
def ledger_client(
    config: Config,
    *,
    authenticate: bool = True,
    csrf_token: str | None = None,
) -> Iterator[tuple[TestClient, Session, int, int]]:
    """실제 PostgreSQL에 붙되 테스트 종료 시 전부 롤백하는 클라이언트.

    기본값은 인증과 CSRF를 통과시킨다. 대부분의 테스트가 검증하려는 것은 원장 동작이지
    인증 배선이 아니기 때문이다.

    `authenticate=False`는 인증 의존성을 그대로 둔다. 세션 쿠키가 없으므로 요청은 401이 된다.
    `csrf_token`을 주면 CSRF 검사만 실제 코드로 되돌린다. 그 토큰을 `X-CSRF-Token` 헤더로
    보내면 통과하고, 빠지거나 다르면 403이 된다.
    """
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

    current_user = CurrentUser(
        id=user_id,
        brokerage_id=brokerage_id,
        login_id="api-test",
        display_name="검증",
        role=UserRole.OWNER,
    )

    app = create_app(config=config, readiness_probe=lambda request: True)
    app.dependency_overrides[get_db_session] = lambda: session
    if authenticate:
        app.dependency_overrides[get_current_user] = lambda: current_user
        if csrf_token is None:
            app.dependency_overrides[require_csrf] = lambda: None
        else:
            # require_csrf는 그대로 두고 그것이 읽는 문맥만 바꾼다. 로그인 없이도
            # 실제 토큰 비교 코드를 지나가게 하기 위해서다.
            app.dependency_overrides[get_authentication_context] = lambda: AuthenticationContext(
                user=current_user,
                session_id=0,
                csrf_token_hash=hash_token(csrf_token),
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
