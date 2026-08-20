from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

import brokerage_ai
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ledger_fixtures import create_complex, create_unit, ledger_client, requires_database
from sqlalchemy import text
from sqlmodel import Session

from api.schemas.f3_runs import (
    GENERIC_FAILURE_CODE,
    GENERIC_FAILURE_MESSAGE,
    anchor_of,
)
from core.config import Config
from domain.agent_execution import service
from domain.agent_execution.models import (
    CROSS_JUDGMENT_RUN_TYPE,
    LEASE_EXPIRED_FAILURE_CODE,
    LEASE_EXPIRED_FAILURE_MESSAGE,
    AgentRun,
    AgentRunAnchorError,
)
from domain.authentication.dependencies import get_authentication_context, require_csrf
from domain.authentication.models import AuthenticationContext, CurrentUser, UserRole
from domain.authentication.service import hash_token
from main import create_app

CSRF_TOKEN = "f3-status-csrf-token"

PUBLIC_FIELDS = {
    "run_id",
    "status",
    "anchor_type",
    "anchor_id",
    "input_data_version",
    "created_at",
    "started_at",
    "completed_at",
    "failure_code",
    "failure_message",
}


def queue_listing_run(client: TestClient, session: Session, brokerage_id: int) -> dict:
    complex_id = create_complex(client, session, brokerage_id, "상태조회단지")
    unit = create_unit(client, complex_id)
    listing = client.post(
        f"/api/v1/property-units/{unit['unit']['id']}/listings",
        json={"is_sale_available": True, "sale_price": 2_880_000_000},
    ).json()
    response = client.post(
        "/api/v1/f3/runs",
        json={"anchor_type": "LISTING", "anchor_id": listing["id"]},
    )
    assert response.status_code == 202, response.text
    return response.json()


def queue_requirement_run(
    client: TestClient, session: Session, brokerage_id: int, user_id: int
) -> dict:
    party_id = session.execute(
        text(
            "INSERT INTO party (brokerage_id, party_type, name, privacy_consent_at,"
            " privacy_consent_by) VALUES (:b, 'PERSON', '상태 손님', now(), :u) RETURNING id"
        ),
        {"b": brokerage_id, "u": user_id},
    ).scalar_one()
    requirement = client.post(
        "/api/v1/property-requirements",
        json={"party_id": party_id, "demand_type": "매수"},
    ).json()["requirement"]
    response = client.post(
        "/api/v1/f3/runs",
        json={"anchor_type": "REQUIREMENT", "anchor_id": requirement["id"]},
    )
    assert response.status_code == 202, response.text
    return response.json()


def insert_agent_run(
    session: Session,
    brokerage_id: int,
    requested_by: int,
    *,
    run_type: str = CROSS_JUDGMENT_RUN_TYPE,
    parent_run_id: int | None = None,
) -> int:
    """Worker가 만들 하위 실행과 다른 실행 유형을 테스트 트랜잭션 안에서만 흉내낸다."""
    return session.execute(
        text(
            "INSERT INTO agent_run (brokerage_id, run_group_id, parent_run_id, run_type,"
            " agent_type, status, trigger_type, requested_by)"
            " VALUES (:b, :g, :p, :rt, 'BROKERAGE_WORKFLOW', 'QUEUED', 'USER_REQUEST', :u)"
            " RETURNING id"
        ),
        {
            "b": brokerage_id,
            "g": str(uuid4()),
            "p": parent_run_id,
            "rt": run_type,
            "u": requested_by,
        },
    ).scalar_one()


def broken_requirement_id(session: Session, brokerage_id: int) -> int:
    """앵커가 둘인 잘못된 행을 만들 때 쓸 구입장 ID. FK만 만족하면 된다."""
    party_id = session.execute(
        text(
            "INSERT INTO party (brokerage_id, party_type, name)"
            " VALUES (:b, 'PERSON', '불변식 손님') RETURNING id"
        ),
        {"b": brokerage_id},
    ).scalar_one()
    return session.execute(
        text(
            "INSERT INTO property_requirement (brokerage_id, party_id, demand_type)"
            " VALUES (:b, :p, '매수') RETURNING id"
        ),
        {"b": brokerage_id, "p": party_id},
    ).scalar_one()


def stored_run(session: Session, run_id: int) -> dict:
    row = (
        session.execute(text("SELECT * FROM agent_run WHERE id = :i"), {"i": run_id})
        .mappings()
        .one()
    )
    return dict(row)


def other_brokerage_run(session: Session) -> int:
    brokerage_id = session.execute(
        text("INSERT INTO brokerage (name) VALUES ('남의 사무소') RETURNING id")
    ).scalar_one()
    user_id = session.execute(
        text(
            "INSERT INTO app_user (brokerage_id, login_id, password_hash, display_name, role)"
            " VALUES (:b, 'other', 'unused', '남', 'OWNER') RETURNING id"
        ),
        {"b": brokerage_id},
    ).scalar_one()
    return insert_agent_run(session, brokerage_id, user_id)


@requires_database
def test_listing_run_status_is_returned_for_the_owning_brokerage(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _user_id):
        queued = queue_listing_run(client, session, brokerage_id)

        response = client.get(f"/api/v1/f3/runs/{queued['run_id']}")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["run_id"] == queued["run_id"]
        assert isinstance(body["run_id"], int)
        assert body["status"] == "QUEUED"
        assert body["anchor_type"] == "LISTING"
        assert body["anchor_id"] == queued["anchor_id"]
        assert body["input_data_version"] == queued["input_data_version"]
        assert body["created_at"] == queued["created_at"]
        assert body["started_at"] is None
        assert body["completed_at"] is None
        assert body["failure_code"] is None
        assert body["failure_message"] is None


@requires_database
def test_requirement_run_status_reports_the_requirement_anchor(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, user_id):
        queued = queue_requirement_run(client, session, brokerage_id, user_id)

        body = client.get(f"/api/v1/f3/runs/{queued['run_id']}").json()

        assert body["anchor_type"] == "REQUIREMENT"
        assert body["anchor_id"] == queued["anchor_id"]
        assert body["input_data_version"] == queued["input_data_version"]


def set_failure(session: Session, run_id: int, code: str | None, message: str | None) -> None:
    """Worker나 AI가 나중에 채울 실패 컬럼을 테스트 트랜잭션 안에서만 직접 세팅한다."""
    session.execute(
        text("UPDATE agent_run SET failure_code = :c, failure_message = :m WHERE id = :i"),
        {"c": code, "m": message, "i": run_id},
    )


@requires_database
def test_status_reflects_stored_lifecycle_columns(config: Config) -> None:
    """Worker가 채울 컬럼을 직접 세팅해 매핑을 확인한다. 상태 전이는 이 API가 하지 않는다."""
    with ledger_client(config) as (client, session, brokerage_id, _user_id):
        queued = queue_listing_run(client, session, brokerage_id)
        started_at = datetime(2026, 8, 19, 2, 20, tzinfo=UTC)
        completed_at = datetime(2026, 8, 19, 2, 20, 4, tzinfo=UTC)
        session.execute(
            text(
                "UPDATE agent_run SET status = 'FAILED_RETRYABLE', started_at = :s,"
                " completed_at = :c WHERE id = :i"
            ),
            {"s": started_at, "c": completed_at, "i": queued["run_id"]},
        )

        body = client.get(f"/api/v1/f3/runs/{queued['run_id']}").json()

        assert body["status"] == "FAILED_RETRYABLE"
        assert datetime.fromisoformat(body["started_at"]) == started_at
        assert datetime.fromisoformat(body["completed_at"]) == completed_at


@requires_database
def test_allowlisted_failure_code_is_returned_with_its_fixed_message(config: Config) -> None:
    """lease 상한 초과는 공개 가능한 코드다. 문구는 DB 원문이 아니라 고정 문구를 쓴다."""
    with ledger_client(config) as (client, session, brokerage_id, _user_id):
        queued = queue_listing_run(client, session, brokerage_id)
        set_failure(session, queued["run_id"], LEASE_EXPIRED_FAILURE_CODE, "내부 운영 원문")

        body = client.get(f"/api/v1/f3/runs/{queued['run_id']}").json()

        assert body["failure_code"] == LEASE_EXPIRED_FAILURE_CODE
        assert body["failure_message"] == LEASE_EXPIRED_FAILURE_MESSAGE
        assert "내부 운영 원문" not in body["failure_message"]


@requires_database
def test_unknown_failure_code_is_generalized(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _user_id):
        queued = queue_listing_run(client, session, brokerage_id)
        set_failure(session, queued["run_id"], "MODEL_TIMEOUT", "upstream 429 from provider")

        body = client.get(f"/api/v1/f3/runs/{queued['run_id']}").json()

        assert body["failure_code"] == GENERIC_FAILURE_CODE
        assert body["failure_message"] == GENERIC_FAILURE_MESSAGE


@requires_database
@pytest.mark.parametrize(
    ("failure_code", "stored_message"),
    [
        (LEASE_EXPIRED_FAILURE_CODE, "의뢰인 010-1234-5678 확인 필요"),
        ("MODEL_TIMEOUT", "kim.buyer@example.com 상담 로그 처리 중 실패"),
        ("UPSTREAM_ERROR", "openai.BadRequestError: invalid_request_error - context length"),
        (
            "INTERNAL_ERROR",
            'Traceback (most recent call last):\n  File "/srv/app/worker.py", line 42,'
            " in run\n    raise RuntimeError('db password rotated')",
        ),
    ],
    ids=["전화번호", "이메일", "외부_오류_원문", "stack_trace"],
)
def test_stored_failure_message_is_never_exposed(
    config: Config, failure_code: str, stored_message: str
) -> None:
    """DB failure_message에 무엇이 저장돼도 응답 본문 어디에도 원문이 나오지 않는다."""
    with ledger_client(config) as (client, session, brokerage_id, _user_id):
        queued = queue_listing_run(client, session, brokerage_id)
        set_failure(session, queued["run_id"], failure_code, stored_message)

        response = client.get(f"/api/v1/f3/runs/{queued['run_id']}")

        assert stored_message not in response.text
        assert response.json()["failure_message"] in {
            LEASE_EXPIRED_FAILURE_MESSAGE,
            GENERIC_FAILURE_MESSAGE,
        }


@requires_database
def test_successful_run_has_no_failure_fields(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _user_id):
        queued = queue_listing_run(client, session, brokerage_id)
        session.execute(
            text("UPDATE agent_run SET status = 'COMPLETED' WHERE id = :i"),
            {"i": queued["run_id"]},
        )

        body = client.get(f"/api/v1/f3/runs/{queued['run_id']}").json()

        assert body["status"] == "COMPLETED"
        assert body["failure_code"] is None
        assert body["failure_message"] is None


@requires_database
def test_status_response_hides_tenant_requester_model_and_snapshots(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _user_id):
        queued = queue_listing_run(client, session, brokerage_id)

        body = client.get(f"/api/v1/f3/runs/{queued['run_id']}").json()

        assert set(body) == PUBLIC_FIELDS


@requires_database
def test_unknown_run_is_not_found(config: Config) -> None:
    with ledger_client(config) as (client, _session, _brokerage_id, _user_id):
        response = client.get("/api/v1/f3/runs/987654321")

        assert response.status_code == 404
        assert response.json()["code"] == "NOT_FOUND"


@requires_database
def test_another_brokerage_run_is_not_found(config: Config) -> None:
    with ledger_client(config) as (client, session, _brokerage_id, _user_id):
        run_id = other_brokerage_run(session)

        response = client.get(f"/api/v1/f3/runs/{run_id}")

        assert response.status_code == 404
        assert response.json()["code"] == "NOT_FOUND"


@requires_database
def test_child_run_is_not_found(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, user_id):
        queued = queue_listing_run(client, session, brokerage_id)
        child_id = insert_agent_run(
            session, brokerage_id, user_id, parent_run_id=queued["run_id"]
        )

        response = client.get(f"/api/v1/f3/runs/{child_id}")

        assert response.status_code == 404
        assert response.json()["code"] == "NOT_FOUND"


@requires_database
def test_other_run_type_is_not_found(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, user_id):
        run_id = insert_agent_run(session, brokerage_id, user_id, run_type="POSITION_ANALYSIS")

        response = client.get(f"/api/v1/f3/runs/{run_id}")

        assert response.status_code == 404
        assert response.json()["code"] == "NOT_FOUND"


@requires_database
def test_reading_the_status_does_not_modify_the_run(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _user_id):
        queued = queue_listing_run(client, session, brokerage_id)
        before = stored_run(session, queued["run_id"])

        client.get(f"/api/v1/f3/runs/{queued['run_id']}")
        client.get(f"/api/v1/f3/runs/{queued['run_id']}")

        assert stored_run(session, queued["run_id"]) == before


@requires_database
def test_status_lookup_does_not_touch_the_ai_runtime(config: Config, monkeypatch) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("상태 조회는 AI runtime을 호출하지 않는다")

    monkeypatch.setattr(brokerage_ai, "create_ai_runtime", fail)
    monkeypatch.setattr(brokerage_ai, "load_ai_config", fail)

    with ledger_client(config) as (client, session, brokerage_id, _user_id):
        queued = queue_listing_run(client, session, brokerage_id)

        assert client.get(f"/api/v1/f3/runs/{queued['run_id']}").status_code == 200


@requires_database
def test_authenticated_get_succeeds_without_a_csrf_header(config: Config) -> None:
    """GET에는 CSRF를 요구하지 않는다. 실제 require_csrf를 되살려 두고 헤더 없이 호출한다."""
    with ledger_client(config) as (client, session, brokerage_id, user_id):
        queued = queue_listing_run(client, session, brokerage_id)
        app = cast(FastAPI, client.app)
        app.dependency_overrides.pop(require_csrf)
        app.dependency_overrides[get_authentication_context] = lambda: AuthenticationContext(
            user=CurrentUser(
                id=user_id,
                brokerage_id=brokerage_id,
                login_id="api-test",
                display_name="검증",
                role=UserRole.OWNER,
            ),
            session_id=1,
            csrf_token_hash=hash_token(CSRF_TOKEN),
        )

        response = client.get(f"/api/v1/f3/runs/{queued['run_id']}")

        assert response.status_code == 200, response.text


def test_unauthenticated_request_is_rejected(config: Config) -> None:
    app = create_app(config=config, readiness_probe=lambda request: True)

    with TestClient(app) as client:
        response = client.get("/api/v1/f3/runs/1")

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


@pytest.mark.parametrize("run_id", ["0", "-3"])
def test_non_positive_run_id_is_rejected(config: Config, run_id: str) -> None:
    app = create_app(config=config, readiness_probe=lambda request: True)
    user = CurrentUser(
        id=11,
        brokerage_id=5,
        login_id="api-test",
        display_name="검증",
        role=UserRole.OWNER,
    )
    app.dependency_overrides[get_authentication_context] = lambda: AuthenticationContext(
        user=user, session_id=1, csrf_token_hash=hash_token(CSRF_TOKEN)
    )

    with TestClient(app) as client:
        response = client.get(f"/api/v1/f3/runs/{run_id}")

    assert response.status_code == 422


@requires_database
@pytest.mark.parametrize(
    ("listing", "requirement"),
    [(False, False), (True, True)],
    ids=["앵커_없음", "앵커_둘"],
)
def test_run_without_exactly_one_anchor_is_not_exposed(
    config: Config, listing: bool, requirement: bool
) -> None:
    """앵커가 없거나 둘 다인 행은 REQUIREMENT/0 같은 가짜 앵커로 변환되면 안 된다."""
    with ledger_client(config) as (client, session, brokerage_id, user_id):
        queued = queue_listing_run(client, session, brokerage_id)
        session.execute(
            text(
                "UPDATE agent_run SET target_listing_id = :l, target_requirement_id = :r"
                " WHERE id = :i"
            ),
            {
                "l": queued["anchor_id"] if listing else None,
                "r": broken_requirement_id(session, brokerage_id) if requirement else None,
                "i": queued["run_id"],
            },
        )

        app = cast(FastAPI, client.app)
        with TestClient(app, raise_server_exceptions=False) as safe_client:
            response = safe_client.get(f"/api/v1/f3/runs/{queued['run_id']}")

        assert response.status_code == 500
        assert response.json()["code"] == "INTERNAL_SERVER_ERROR"
        assert "anchor_id" not in response.json()


def test_anchor_mapping_rejects_a_run_without_exactly_one_target() -> None:
    for listing_id, requirement_id in [(None, None), (7, 9)]:
        run = AgentRun(
            brokerage_id=1,
            run_group_id=uuid4(),
            run_type=CROSS_JUDGMENT_RUN_TYPE,
            agent_type="BROKERAGE_WORKFLOW",
            trigger_type="USER_REQUEST",
            requested_by=1,
            target_listing_id=listing_id,
            target_requirement_id=requirement_id,
        )

        with pytest.raises(AgentRunAnchorError):
            anchor_of(run)


@requires_database
def test_status_response_does_not_expose_lease_fields(config: Config) -> None:
    """Worker 선점 뒤에도 lease 소유자·만료·시도 횟수는 외부로 나가지 않는다."""
    with ledger_client(config) as (client, session, brokerage_id, _user_id):
        queued = queue_listing_run(client, session, brokerage_id)
        claimed = service.claim_next_run(session, "worker-status-check")
        assert claimed is not None and claimed.id == queued["run_id"]

        body = client.get(f"/api/v1/f3/runs/{queued['run_id']}").json()

        assert set(body) == PUBLIC_FIELDS
        assert body["status"] == "RUNNING"
        assert "lease_owner" not in body
        assert "lease_expires_at" not in body
        assert "attempt_count" not in body
