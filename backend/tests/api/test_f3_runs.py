from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

import brokerage_ai
import pytest
from fastapi.testclient import TestClient
from ledger_fixtures import create_complex, create_unit, ledger_client, requires_database
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from core.config import Config
from domain.agent_execution import service
from domain.agent_execution.models import AnchorType
from domain.authentication.dependencies import get_authentication_context, get_current_user
from domain.authentication.models import AuthenticationContext, CurrentUser, UserRole
from domain.authentication.service import hash_token
from main import create_app

CSRF_TOKEN = "f3-csrf-token"


def create_listing(client: TestClient, complex_id: int, **overrides: object) -> dict:
    unit = create_unit(client, complex_id, **overrides)
    unit_id = unit["unit"]["id"]
    response = client.post(
        f"/api/v1/property-units/{unit_id}/listings",
        json={"is_sale_available": True, "sale_price": 2_880_000_000},
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_consented_party(session: Session, brokerage_id: int, name: str, user_id: int) -> int:
    return session.execute(
        text(
            "INSERT INTO party (brokerage_id, party_type, name, privacy_consent_at,"
            " privacy_consent_by) VALUES (:b, 'PERSON', :n, now(), :u) RETURNING id"
        ),
        {"b": brokerage_id, "n": name, "u": user_id},
    ).scalar_one()


def create_requirement(client: TestClient, party_id: int) -> dict:
    response = client.post(
        "/api/v1/property-requirements",
        json={"party_id": party_id, "demand_type": "매수"},
    )
    assert response.status_code == 201, response.text
    return response.json()["requirement"]


def stored_runs(session: Session, brokerage_id: int) -> list[dict]:
    rows = session.execute(
        text(
            "SELECT id, brokerage_id, run_group_id, parent_run_id, run_type, agent_type, status,"
            " trigger_type, requested_by, model_config_id, target_unit_id, target_listing_id,"
            " target_requirement_id, input_data_version, redacted_input_snapshot,"
            " redacted_output_snapshot FROM agent_run WHERE brokerage_id = :b ORDER BY id"
        ),
        {"b": brokerage_id},
    ).mappings()
    return [dict(row) for row in rows]


@contextmanager
def authenticated_client(config: Config) -> Iterator[TestClient]:
    """DB 없이 인증·CSRF 경로만 확인하는 클라이언트. require_csrf는 그대로 둔다."""
    app = create_app(config=config, readiness_probe=lambda request: True)
    user = CurrentUser(
        id=11,
        brokerage_id=5,
        login_id="api-test",
        display_name="검증",
        role=UserRole.OWNER,
    )
    app.dependency_overrides[get_authentication_context] = lambda: AuthenticationContext(
        user=user,
        session_id=1,
        csrf_token_hash=hash_token(CSRF_TOKEN),
    )
    with TestClient(app) as client:
        yield client


@requires_database
def test_listing_anchor_queues_a_single_run_for_the_current_user(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, user_id):
        complex_id = create_complex(client, session, brokerage_id, "실행단지")
        listing = create_listing(client, complex_id)

        response = client.post(
            "/api/v1/f3/runs",
            json={"anchor_type": "LISTING", "anchor_id": listing["id"]},
        )

        assert response.status_code == 202, response.text
        body = response.json()
        assert body["status"] == "QUEUED"
        assert body["anchor_type"] == "LISTING"
        assert body["anchor_id"] == listing["id"]
        assert body["input_data_version"] == listing["row_version"]
        assert body["created_at"] is not None
        UUID(body["run_group_id"])

        runs = stored_runs(session, brokerage_id)
        assert len(runs) == 1
        run = runs[0]
        assert run["id"] == body["run_id"]
        assert run["status"] == "QUEUED"
        assert run["brokerage_id"] == brokerage_id
        assert run["requested_by"] == user_id
        assert run["run_type"] == "CROSS_JUDGMENT"
        assert run["agent_type"] == "BROKERAGE_WORKFLOW"
        # F1 매물 저장이 이미 자동 접수했고 (F3-CR-02) 화면 요청은 그 실행을 재사용한다.
        assert run["trigger_type"] == "LEDGER_SAVE"
        assert run["parent_run_id"] is None
        assert run["model_config_id"] is None
        assert run["target_listing_id"] == listing["id"]
        assert run["target_unit_id"] == listing["unit_id"]
        assert run["target_requirement_id"] is None
        assert run["redacted_output_snapshot"] == {}


@requires_database
def test_response_hides_tenant_requester_and_input_snapshot(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _user_id):
        complex_id = create_complex(client, session, brokerage_id, "노출단지")
        listing = create_listing(client, complex_id)

        body = client.post(
            "/api/v1/f3/runs",
            json={"anchor_type": "LISTING", "anchor_id": listing["id"]},
        ).json()

        assert set(body) == {
            "run_id",
            "run_group_id",
            "status",
            "anchor_type",
            "anchor_id",
            "input_data_version",
            "created_at",
        }


@requires_database
def test_listing_row_version_becomes_the_input_data_version(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _user_id):
        complex_id = create_complex(client, session, brokerage_id, "버전단지")
        listing = create_listing(client, complex_id)
        updated = client.patch(
            f"/api/v1/property-listings/{listing['id']}",
            json={"row_version": listing["row_version"], "sale_price": 2_700_000_000},
        ).json()
        assert updated["row_version"] == listing["row_version"] + 1

        body = client.post(
            "/api/v1/f3/runs",
            json={"anchor_type": "LISTING", "anchor_id": listing["id"]},
        ).json()

        assert body["input_data_version"] == updated["row_version"]
        # 등록과 가격 변경이 각각 자동 접수를 만든다. 화면 요청은 최신 버전 실행을 재사용한다.
        latest = stored_runs(session, brokerage_id)[-1]
        assert latest["id"] == body["run_id"]
        assert latest["input_data_version"] == updated["row_version"]


@requires_database
def test_requirement_anchor_stores_the_requirement_target_and_row_version(
    config: Config,
) -> None:
    with ledger_client(config) as (client, session, brokerage_id, user_id):
        party_id = create_consented_party(session, brokerage_id, "판정 손님", user_id)
        requirement = create_requirement(client, party_id)
        updated = client.patch(
            f"/api/v1/property-requirements/{requirement['id']}",
            json={"row_version": requirement["row_version"], "workflow_stage": "방문예정"},
        ).json()["requirement"]
        assert updated["row_version"] == requirement["row_version"] + 1

        response = client.post(
            "/api/v1/f3/runs",
            json={"anchor_type": "REQUIREMENT", "anchor_id": requirement["id"]},
        )

        assert response.status_code == 202, response.text
        body = response.json()
        assert body["anchor_type"] == "REQUIREMENT"
        assert body["anchor_id"] == requirement["id"]
        assert body["input_data_version"] == updated["row_version"]

        run = stored_runs(session, brokerage_id)[-1]
        assert run["id"] == body["run_id"]
        assert run["target_requirement_id"] == requirement["id"]
        assert run["target_listing_id"] is None
        assert run["target_unit_id"] is None
        assert run["input_data_version"] == updated["row_version"]


@requires_database
def test_redacted_input_snapshot_keeps_only_anchor_and_version(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _user_id):
        complex_id = create_complex(client, session, brokerage_id, "스냅샷단지")
        listing = create_listing(client, complex_id)

        client.post("/api/v1/f3/runs", json={"anchor_type": "LISTING", "anchor_id": listing["id"]})

        assert stored_runs(session, brokerage_id)[-1]["redacted_input_snapshot"] == {
            "anchor_type": "LISTING",
            "anchor_id": listing["id"],
            "input_data_version": listing["row_version"],
        }


@requires_database
@pytest.mark.parametrize("anchor_type", ["LISTING", "REQUIREMENT"])
def test_unknown_anchor_is_not_found(config: Config, anchor_type: str) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _user_id):
        response = client.post(
            "/api/v1/f3/runs",
            json={"anchor_type": anchor_type, "anchor_id": 987_654_321},
        )

        assert response.status_code == 404
        assert response.json()["code"] == "NOT_FOUND"
        assert stored_runs(session, brokerage_id) == []


@requires_database
def test_another_brokerage_listing_is_not_found(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _user_id):
        other_brokerage_id = session.execute(
            text("INSERT INTO brokerage (name) VALUES ('남의 사무소') RETURNING id")
        ).scalar_one()
        other_complex_id = create_complex(client, session, other_brokerage_id, "남의단지")
        other_unit_id = session.execute(
            text(
                "INSERT INTO property_unit (brokerage_id, complex_id, unit_number)"
                " VALUES (:b, :c, '999') RETURNING id"
            ),
            {"b": other_brokerage_id, "c": other_complex_id},
        ).scalar_one()
        other_listing_id = session.execute(
            text(
                "INSERT INTO property_listing (brokerage_id, unit_id) VALUES (:b, :u) RETURNING id"
            ),
            {"b": other_brokerage_id, "u": other_unit_id},
        ).scalar_one()

        response = client.post(
            "/api/v1/f3/runs",
            json={"anchor_type": "LISTING", "anchor_id": other_listing_id},
        )

        assert response.status_code == 404
        assert response.json()["code"] == "NOT_FOUND"
        assert stored_runs(session, other_brokerage_id) == []


@requires_database
def test_another_brokerage_requirement_is_not_found(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _user_id):
        other_brokerage_id = session.execute(
            text("INSERT INTO brokerage (name) VALUES ('남의 사무소') RETURNING id")
        ).scalar_one()
        other_party_id = session.execute(
            text(
                "INSERT INTO party (brokerage_id, party_type, name)"
                " VALUES (:b, 'PERSON', '남의 손님') RETURNING id"
            ),
            {"b": other_brokerage_id},
        ).scalar_one()
        other_requirement_id = session.execute(
            text(
                "INSERT INTO property_requirement (brokerage_id, party_id, demand_type)"
                " VALUES (:b, :p, '매수') RETURNING id"
            ),
            {"b": other_brokerage_id, "p": other_party_id},
        ).scalar_one()

        response = client.post(
            "/api/v1/f3/runs",
            json={"anchor_type": "REQUIREMENT", "anchor_id": other_requirement_id},
        )

        assert response.status_code == 404
        assert response.json()["code"] == "NOT_FOUND"
        assert stored_runs(session, other_brokerage_id) == []


def delete_unit(client: TestClient, unit: dict) -> None:
    response = client.delete(
        f"/api/v1/property-units/{unit['unit']['id']}",
        params={"row_version": unit["unit"]["row_version"]},
    )
    assert response.status_code == 204, response.text


@requires_database
def test_listing_under_a_deleted_unit_is_not_found(config: Config) -> None:
    """세대 삭제는 딸린 매물 행을 건드리지 않는다. 그래도 앵커로는 쓸 수 없어야 한다.

    화면에서 사라진 세대의 매물 ID를 그대로 POST하면 존재하지 않는 대상의 실행이 생긴다.
    """
    with ledger_client(config) as (client, session, brokerage_id, _user_id):
        complex_id = create_complex(client, session, brokerage_id, "삭제세대단지")
        unit = create_unit(client, complex_id, unit_number="101")
        listing = client.post(
            f"/api/v1/property-units/{unit['unit']['id']}/listings",
            json={"is_sale_available": True, "sale_price": 2_880_000_000},
        ).json()
        assert (
            client.post(
                "/api/v1/f3/runs",
                json={"anchor_type": "LISTING", "anchor_id": listing["id"]},
            ).status_code
            == 202
        )
        session.execute(text("DELETE FROM agent_run WHERE brokerage_id = :b"), {"b": brokerage_id})

        delete_unit(client, unit)

        response = client.post(
            "/api/v1/f3/runs",
            json={"anchor_type": "LISTING", "anchor_id": listing["id"]},
        )

        assert response.status_code == 404
        assert response.json()["code"] == "NOT_FOUND"
        # 매물 행은 이력으로 남아 있어야 한다. 앵커에서 막는 것과 이력을 지우는 것은 다르다.
        assert (
            session.execute(
                text("SELECT is_deleted FROM property_listing WHERE id = :i"),
                {"i": listing["id"]},
            ).scalar_one()
            is False
        )
        assert stored_runs(session, brokerage_id) == []


@requires_database
def test_deleted_unit_listing_and_another_brokerage_listing_answer_identically(
    config: Config,
) -> None:
    """삭제된 세대의 매물, 남의 사무소 매물, 없는 ID가 서로 구분되면 안 된다."""
    with ledger_client(config) as (client, session, brokerage_id, _user_id):
        complex_id = create_complex(client, session, brokerage_id, "구분단지")
        unit = create_unit(client, complex_id, unit_number="101")
        deleted_unit_listing = client.post(
            f"/api/v1/property-units/{unit['unit']['id']}/listings",
            json={"is_sale_available": True, "sale_price": 2_880_000_000},
        ).json()
        delete_unit(client, unit)

        other_brokerage_id = session.execute(
            text("INSERT INTO brokerage (name) VALUES ('남의 사무소') RETURNING id")
        ).scalar_one()
        other_complex_id = create_complex(client, session, other_brokerage_id, "남의구분단지")
        other_unit_id = session.execute(
            text(
                "INSERT INTO property_unit (brokerage_id, complex_id, unit_number)"
                " VALUES (:b, :c, '999') RETURNING id"
            ),
            {"b": other_brokerage_id, "c": other_complex_id},
        ).scalar_one()
        other_listing_id = session.execute(
            text(
                "INSERT INTO property_listing (brokerage_id, unit_id) VALUES (:b, :u) RETURNING id"
            ),
            {"b": other_brokerage_id, "u": other_unit_id},
        ).scalar_one()

        answers = [
            client.post("/api/v1/f3/runs", json={"anchor_type": "LISTING", "anchor_id": anchor_id})
            for anchor_id in (deleted_unit_listing["id"], other_listing_id, 987_654_321)
        ]

        assert [response.status_code for response in answers] == [404, 404, 404]
        bodies = [response.json() for response in answers]
        assert {body["code"] for body in bodies} == {"NOT_FOUND"}
        assert len({body["message"] for body in bodies}) == 1


@requires_database
def test_deleted_requirement_is_not_found_and_live_requirement_still_queues(
    config: Config,
) -> None:
    """REQUIREMENT 앵커의 기존 경계는 그대로다. 삭제된 구입장만 막힌다."""
    with ledger_client(config) as (client, session, brokerage_id, user_id):
        party_id = create_consented_party(session, brokerage_id, "경계 손님", user_id)
        live = create_requirement(client, party_id)
        removed = create_requirement(client, party_id)
        assert (
            client.delete(
                f"/api/v1/property-requirements/{removed['id']}",
                params={"row_version": removed["row_version"]},
            ).status_code
            == 204
        )

        assert (
            client.post(
                "/api/v1/f3/runs",
                json={"anchor_type": "REQUIREMENT", "anchor_id": live["id"]},
            ).status_code
            == 202
        )
        before = len(stored_runs(session, brokerage_id))
        response = client.post(
            "/api/v1/f3/runs",
            json={"anchor_type": "REQUIREMENT", "anchor_id": removed["id"]},
        )

        assert response.status_code == 404
        assert response.json()["code"] == "NOT_FOUND"
        # 삭제된 구입장은 새 실행을 만들지 않는다. 저장 시점의 자동 접수는 그대로 남는다.
        assert len(stored_runs(session, brokerage_id)) == before
        assert live["id"] in {
            run["target_requirement_id"] for run in stored_runs(session, brokerage_id)
        }


@requires_database
def test_request_cannot_override_server_owned_fields(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _user_id):
        complex_id = create_complex(client, session, brokerage_id, "위조단지")
        listing = create_listing(client, complex_id)

        before = stored_runs(session, brokerage_id)
        response = client.post(
            "/api/v1/f3/runs",
            json={
                "anchor_type": "LISTING",
                "anchor_id": listing["id"],
                "brokerage_id": 999,
                "requested_by": 999,
                "status": "COMPLETED",
                "run_type": "SOMETHING_ELSE",
            },
        )

        assert response.status_code == 422
        # 거절된 요청은 아무것도 바꾸지 않는다. 저장 시점의 자동 접수만 남아 있다.
        assert stored_runs(session, brokerage_id) == before
        assert all(run["brokerage_id"] == brokerage_id for run in before)
        assert all(run["status"] == "QUEUED" for run in before)


@requires_database
def test_queueing_does_not_touch_the_ai_runtime(config: Config, monkeypatch) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("F3 실행 적재는 AI runtime을 호출하지 않는다")

    monkeypatch.setattr(brokerage_ai, "create_ai_runtime", fail)
    monkeypatch.setattr(brokerage_ai, "load_ai_config", fail)

    with ledger_client(config) as (client, session, brokerage_id, _user_id):
        complex_id = create_complex(client, session, brokerage_id, "무호출단지")
        listing = create_listing(client, complex_id)

        response = client.post(
            "/api/v1/f3/runs",
            json={"anchor_type": "LISTING", "anchor_id": listing["id"]},
        )

        assert response.status_code == 202
        assert len(stored_runs(session, brokerage_id)) == 1


def test_unauthenticated_request_is_rejected(config: Config) -> None:
    app = create_app(config=config, readiness_probe=lambda request: True)

    with TestClient(app) as client:
        response = client.post("/api/v1/f3/runs", json={"anchor_type": "LISTING", "anchor_id": 1})

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


def test_missing_csrf_token_is_rejected(config: Config) -> None:
    with authenticated_client(config) as client:
        response = client.post("/api/v1/f3/runs", json={"anchor_type": "LISTING", "anchor_id": 1})

    assert response.status_code == 403
    assert response.json()["code"] == "INVALID_CSRF_TOKEN"


@pytest.mark.parametrize(
    "payload",
    [
        {"anchor_type": "UNIT", "anchor_id": 1},
        {"anchor_type": "LISTING", "anchor_id": 0},
        {"anchor_type": "LISTING", "anchor_id": -3},
        {"anchor_type": "LISTING"},
    ],
)
def test_invalid_anchor_input_is_rejected(config: Config, payload: dict) -> None:
    app = create_app(config=config, readiness_probe=lambda request: True)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=11,
        brokerage_id=5,
        login_id="api-test",
        display_name="검증",
        role=UserRole.OWNER,
    )
    app.dependency_overrides[get_authentication_context] = lambda: AuthenticationContext(
        user=CurrentUser(
            id=11,
            brokerage_id=5,
            login_id="api-test",
            display_name="검증",
            role=UserRole.OWNER,
        ),
        session_id=1,
        csrf_token_hash=hash_token(CSRF_TOKEN),
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/f3/runs", json=payload, headers={"X-CSRF-Token": CSRF_TOKEN}
        )

    assert response.status_code == 422


@requires_database
def test_failed_insert_leaves_no_partial_run(config: Config) -> None:
    """requested_by가 실재하지 않으면 FK가 거절한다. 실패한 실행이 남으면 Worker가 집어간다."""
    with ledger_client(config) as (client, session, brokerage_id, _user_id):
        complex_id = create_complex(client, session, brokerage_id, "실패단지")
        # API 로 만들면 F1 저장이 자동 접수를 하고 그 실행이 재사용된다. 여기서 보려는 것은
        # 삽입 실패이므로 자동 접수가 붙지 않는 매물을 직접 넣는다.
        unit_id = session.execute(
            text(
                "INSERT INTO property_unit (brokerage_id, complex_id, unit_number)"
                " VALUES (:b, :c, '9001') RETURNING id"
            ),
            {"b": brokerage_id, "c": complex_id},
        ).scalar_one()
        listing_id = session.execute(
            text(
                "INSERT INTO property_listing (brokerage_id, unit_id, is_sale_available,"
                " sale_price) VALUES (:b, :u, true, 100) RETURNING id"
            ),
            {"b": brokerage_id, "u": unit_id},
        ).scalar_one()
        session.commit()

        with pytest.raises(IntegrityError):
            service.queue_cross_judgment_run(
                session,
                brokerage_id,
                requested_by=987_654_321,
                anchor_type=AnchorType.LISTING,
                anchor_id=listing_id,
            )

        assert stored_runs(session, brokerage_id) == []
