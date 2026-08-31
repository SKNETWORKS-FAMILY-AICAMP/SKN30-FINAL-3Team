"""F3 실행 결과 조회 API 통합 테스트."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from ledger_fixtures import create_complex, create_unit, ledger_client, requires_database
from sqlalchemy import text
from sqlmodel import Session

from core.config import Config


def _queue_listing_run(
    client: TestClient, session: Session, brokerage_id: int
) -> tuple[dict, dict]:
    complex_id = create_complex(client, session, brokerage_id, "결과조회단지")
    unit = create_unit(client, complex_id)
    listing_response = client.post(
        f"/api/v1/property-units/{unit['unit']['id']}/listings",
        json={"is_sale_available": True, "sale_price": 2_880_000_000},
    )
    assert listing_response.status_code == 201, listing_response.text
    listing = listing_response.json()
    run_response = client.post(
        "/api/v1/f3/runs",
        json={"anchor_type": "LISTING", "anchor_id": listing["id"]},
    )
    assert run_response.status_code == 202, run_response.text
    return run_response.json(), listing


def _store_anchor_card(
    session: Session,
    brokerage_id: int,
    run_id: int,
    listing_id: int,
    *,
    privacy_mode: str | None = "SYNTHETIC_PROTOTYPE",
) -> int:
    unit_id = session.execute(
        text("SELECT unit_id FROM property_listing WHERE id = :id"), {"id": listing_id}
    ).scalar_one()
    snapshot = json.dumps(
        {
            "contract_version": "position-card:v1",
            "analysis": {
                "intent": {"value": "PRESENT", "evidence": []},
                "urgency": {"value": "NORMAL", "evidence": []},
            },
            # 공개 응답에서 빠져야 하는 내부 생성 진단이다.
            "prompt_version": "position-card-prompt:v1",
            "workflow_version": "position-card-workflow:v1",
            "diagnostics": {"model": "private-model"},
        }
    )
    card_id = session.execute(
        text(
            "INSERT INTO negotiation_position_analysis (brokerage_id, agent_run_id,"
            " negotiation_side, unit_id, listing_id, target_label, cache_key, data_version,"
            " analysis_snapshot) VALUES (:b, :r, 'LISTING', :u, :l, '결과조회단지 101호',"
            " :k, 1, CAST(:snapshot AS jsonb)) RETURNING id"
        ),
        {
            "b": brokerage_id,
            "r": run_id,
            "u": unit_id,
            "l": listing_id,
            "k": f"result-test:{uuid4().hex}",
            "snapshot": snapshot,
        },
    ).scalar_one()
    session.execute(
        text(
            "INSERT INTO negotiation_position_evidence (brokerage_id, position_analysis_id,"
            " field_name, evidence_type, note)"
            " VALUES (:b, :card, 'intent', 'INFERENCE', '상담 정황')"
        ),
        {"b": brokerage_id, "card": card_id},
    )
    output_snapshot = {"position_analysis_id": card_id}
    if privacy_mode is not None:
        output_snapshot["input_privacy_mode"] = privacy_mode
    session.execute(
        text(
            "UPDATE agent_run SET status = 'ANCHOR_READY', redacted_output_snapshot ="
            " CAST(:snapshot AS jsonb) WHERE id = :run"
        ),
        {"snapshot": json.dumps(output_snapshot), "run": run_id},
    )
    session.commit()
    return card_id


def _store_completed_judgment(
    session: Session,
    brokerage_id: int,
    user_id: int,
    run_id: int,
    anchor_card_id: int,
    *,
    selection_schema: str = "candidate-selection:v3",
) -> int:
    party_id = session.execute(
        text(
            "INSERT INTO party (brokerage_id, party_type, name, privacy_consent_at,"
            " privacy_consent_by) VALUES (:b, 'PERSON', '합성 손님', now(), :u) RETURNING id"
        ),
        {"b": brokerage_id, "u": user_id},
    ).scalar_one()
    requirement_id = session.execute(
        text(
            "INSERT INTO property_requirement (brokerage_id, party_id, demand_type,"
            " max_budget_amount) VALUES (:b, :p, '매수', 3000000000) RETURNING id"
        ),
        {"b": brokerage_id, "p": party_id},
    ).scalar_one()
    candidate_card_id = session.execute(
        text(
            "INSERT INTO negotiation_position_analysis (brokerage_id, agent_run_id,"
            " negotiation_side, requirement_id, cache_key, data_version)"
            " VALUES (:b, :r, 'REQUIREMENT', :q, :k, 1) RETURNING id"
        ),
        {
            "b": brokerage_id,
            "r": run_id,
            "q": requirement_id,
            "k": f"result-test:{uuid4().hex}",
        },
    ).scalar_one()
    selection = json.dumps(
        {
            "schema": selection_schema,
            "criteria": {
                "candidate_side": "REQUIREMENT",
                "price_kind": "SALE",
                "price_amount": 2_880_000_000,
                "price_source": "ESTIMATED",
            },
            "total_count": 2,
            "carded_count": 1,
            "remaining_count": 1,
            "candidates": [
                {
                    "candidate_id": requirement_id,
                    "rank": 1,
                    "selected_for_cards": True,
                    "score": "0.850000",
                    "price_amount": 3_000_000_000,
                    "monthly_amount": None,
                    "received_at": "2026-08-01",
                },
                {
                    "candidate_id": 999999,
                    "rank": 2,
                    "selected_for_cards": False,
                    "score": "0.100000",
                    "price_amount": None,
                    "monthly_amount": None,
                    "received_at": None,
                },
            ],
            "candidate_cards": [
                {
                    "candidate_id": requirement_id,
                    "position_analysis_id": candidate_card_id,
                    "cache_hit": False,
                }
            ],
        }
    )
    evaluation_id = session.execute(
        text(
            "INSERT INTO match_evaluation (brokerage_id, agent_run_id,"
            " anchor_position_analysis_id, candidate_count, data_version,"
            " candidate_selection_snapshot) VALUES (:b, :r, :anchor, 1, 1,"
            " CAST(:snapshot AS jsonb)) RETURNING id"
        ),
        {"b": brokerage_id, "r": run_id, "anchor": anchor_card_id, "snapshot": selection},
    ).scalar_one()
    candidate_evaluation_id = session.execute(
        text(
            "INSERT INTO match_candidate_evaluation (brokerage_id, match_evaluation_id,"
            " candidate_position_analysis_id, match_grade, match_rank, evaluation_basis,"
            " primary_obstacle, recommended_action) VALUES (:b, :evaluation, :card,"
            " 'STRONG', 1, '예산이 가깝다', '가격 차', CAST(:action AS jsonb)) RETURNING id"
        ),
        {
            "b": brokerage_id,
            "evaluation": evaluation_id,
            "card": candidate_card_id,
            "action": '{"channel": "MESSAGE", "message": "조건 확인"}',
        },
    ).scalar_one()
    session.execute(
        text(
            "INSERT INTO match_candidate_evidence (brokerage_id,"
            " match_candidate_evaluation_id, evidence_side, field_name, evidence_type, note)"
            " VALUES (:b, :candidate, 'LISTING', 'price', 'INFERENCE', '카드 값 비교')"
        ),
        {"b": brokerage_id, "candidate": candidate_evaluation_id},
    )
    session.execute(
        text("UPDATE agent_run SET status = 'COMPLETED', completed_at = now() WHERE id = :run"),
        {"run": run_id},
    )
    session.commit()
    return requirement_id


@requires_database
def test_queued_run_returns_an_empty_current_result(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _user_id):
        run, _listing = _queue_listing_run(client, session, brokerage_id)

        response = client.get(f"/api/v1/f3/runs/{run['run_id']}/result")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "QUEUED"
        assert body["anchor_card"] is None
        assert body["candidate_selection"] == {
            "criteria": None,
            "total_count": 0,
            "carded_count": 0,
            "remaining_count": 0,
        }
        assert body["candidates"] == []


@requires_database
def test_anchor_card_is_available_before_candidate_selection(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _user_id):
        run, listing = _queue_listing_run(client, session, brokerage_id)
        _store_anchor_card(session, brokerage_id, run["run_id"], listing["id"])

        response = client.get(f"/api/v1/f3/runs/{run['run_id']}/result")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "ANCHOR_READY"
        assert body["anchor_card"]["target_label"] == "결과조회단지 101호"
        assert body["anchor_card"]["analysis"]["intent"]["value"] == "PRESENT"
        assert body["anchor_card"]["evidence"][0]["evidence_type"] == "INFERENCE"
        assert body["candidates"] == []


@requires_database
@pytest.mark.parametrize("privacy_mode", [None, "MASKED"])
def test_unverified_privacy_mode_returns_status_without_card_content(
    config: Config, privacy_mode: str | None
) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _user_id):
        run, listing = _queue_listing_run(client, session, brokerage_id)
        _store_anchor_card(
            session,
            brokerage_id,
            run["run_id"],
            listing["id"],
            privacy_mode=privacy_mode,
        )

        response = client.get(f"/api/v1/f3/runs/{run['run_id']}/result")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "ANCHOR_READY"
        assert body["anchor_card"] is None
        assert body["candidate_selection"]["criteria"] is None
        assert body["candidates"] == []
        assert "private-model" not in response.text


@requires_database
def test_completed_result_contains_all_sql_candidates_and_judgment(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, user_id):
        run, listing = _queue_listing_run(client, session, brokerage_id)
        anchor_card_id = _store_anchor_card(session, brokerage_id, run["run_id"], listing["id"])
        requirement_id = _store_completed_judgment(
            session, brokerage_id, user_id, run["run_id"], anchor_card_id
        )

        response = client.get(f"/api/v1/f3/runs/{run['run_id']}/result")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "COMPLETED"
        assert body["candidate_selection"]["total_count"] == 2
        assert body["candidate_selection"]["carded_count"] == 1
        judged = next(item for item in body["candidates"] if item["candidate_id"] == requirement_id)
        assert judged["match_grade"] == "STRONG"
        assert judged["rank"] == 1
        assert judged["evaluation_basis"] == "예산이 가깝다"
        assert judged["evidence"][0]["evidence_side"] == "LISTING"
        uncarded = next(item for item in body["candidates"] if item["candidate_id"] == 999999)
        assert uncarded["selected_for_cards"] is False
        assert uncarded["match_grade"] is None
        # 판정 전 후보에는 피드백 대상이 없다. 화면은 이 값으로 [관심없음]을 막는다.
        assert uncarded["judgment_id"] is None
        assert body["candidates_total"] == 2


@requires_database
def test_completed_v2_candidate_result_remains_readable(config: Config) -> None:
    """상한 조정 전에 완료된 판정 이력은 v3 배포 후에도 조회한다."""
    with ledger_client(config) as (client, session, brokerage_id, user_id):
        run, listing = _queue_listing_run(client, session, brokerage_id)
        anchor_card_id = _store_anchor_card(session, brokerage_id, run["run_id"], listing["id"])
        _store_completed_judgment(
            session,
            brokerage_id,
            user_id,
            run["run_id"],
            anchor_card_id,
            selection_schema="candidate-selection:v2",
        )

        body = client.get(f"/api/v1/f3/runs/{run['run_id']}/result").json()

        assert body["candidate_selection"]["total_count"] == 2
        assert len(body["candidates"]) == 2


@requires_database
def test_candidate_judgment_id_is_usable_as_a_feedback_target(config: Config) -> None:
    """결과 조회의 ``judgment_id``가 관심없음 피드백의 ``target_id``와 같은 식별자다."""
    with ledger_client(config) as (client, session, brokerage_id, user_id):
        run, listing = _queue_listing_run(client, session, brokerage_id)
        anchor_card_id = _store_anchor_card(session, brokerage_id, run["run_id"], listing["id"])
        requirement_id = _store_completed_judgment(
            session, brokerage_id, user_id, run["run_id"], anchor_card_id
        )

        result = client.get(f"/api/v1/f3/runs/{run['run_id']}/result").json()
        judged = next(
            item for item in result["candidates"] if item["candidate_id"] == requirement_id
        )

        response = client.post(
            "/api/v1/f3/feedback",
            json={
                "target": "MATCH_CANDIDATE",
                "target_id": judged["judgment_id"],
                "reason": "WRONG_JUDGMENT",
                "field_name": "match_grade",
            },
        )

        assert response.status_code == 201, response.text
        assert response.json()["target_id"] == judged["judgment_id"]


@requires_database
def test_result_candidate_pagination_and_bounds(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, user_id):
        run, listing = _queue_listing_run(client, session, brokerage_id)
        anchor_card_id = _store_anchor_card(session, brokerage_id, run["run_id"], listing["id"])
        _store_completed_judgment(session, brokerage_id, user_id, run["run_id"], anchor_card_id)

        response = client.get(f"/api/v1/f3/runs/{run['run_id']}/result?limit=1&offset=1")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["limit"] == 1
        assert body["offset"] == 1
        assert body["candidates_total"] == 2
        assert len(body["candidates"]) == 1
        assert client.get(f"/api/v1/f3/runs/{run['run_id']}/result?limit=101").status_code == 422
        assert client.get(f"/api/v1/f3/runs/{run['run_id']}/result?offset=-1").status_code == 422


@requires_database
def test_result_is_tenant_scoped_and_hides_internal_fields(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _user_id):
        run, listing = _queue_listing_run(client, session, brokerage_id)
        _store_anchor_card(session, brokerage_id, run["run_id"], listing["id"])
        response = client.get(f"/api/v1/f3/runs/{run['run_id']}/result")
        assert response.status_code == 200, response.text
        assert set(response.json()) == {
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
            "anchor_card",
            "candidate_selection",
            "candidates",
            "candidates_total",
            "limit",
            "offset",
        }
        raw = response.text
        for forbidden in (
            "brokerage_id",
            "requested_by",
            "run_group_id",
            "parent_run_id",
            "lease_owner",
            "model_snapshot",
            "model_config_id",
            "prompt_version",
            "workflow_version",
            "private-model",
        ):
            assert forbidden not in raw

        other_brokerage_id = session.execute(
            text("INSERT INTO brokerage (name) VALUES ('다른 결과 사무소') RETURNING id")
        ).scalar_one()
        other_user_id = session.execute(
            text(
                "INSERT INTO app_user (brokerage_id, login_id, password_hash, display_name, role)"
                " VALUES (:b, :login, 'unused', '다른 사용자', 'OWNER') RETURNING id"
            ),
            {"b": other_brokerage_id, "login": f"other-{uuid4().hex}"},
        ).scalar_one()
        foreign_run_id = session.execute(
            text(
                "INSERT INTO agent_run (brokerage_id, run_group_id, run_type, agent_type,"
                " status, trigger_type, requested_by) VALUES (:b, :group, 'CROSS_JUDGMENT',"
                " 'BROKERAGE_WORKFLOW', 'QUEUED', 'USER_REQUEST', :user) RETURNING id"
            ),
            {"b": other_brokerage_id, "group": str(uuid4()), "user": other_user_id},
        ).scalar_one()
        session.commit()

        hidden = client.get(f"/api/v1/f3/runs/{foreign_run_id}/result")
        assert hidden.status_code == 404
        assert hidden.json()["code"] == "NOT_FOUND"


@requires_database
def test_result_requires_authentication_but_not_csrf(config: Config) -> None:
    with ledger_client(config, authenticate=False) as (client, _session, _brokerage, _user):
        response = client.get("/api/v1/f3/runs/1/result")
        assert response.status_code == 401

    with ledger_client(config, csrf_token="result-token") as (
        client,
        session,
        brokerage_id,
        user_id,
    ):
        party_id = session.execute(
            text(
                "INSERT INTO party (brokerage_id, party_type, name)"
                " VALUES (:b, 'PERSON', 'CSRF 조회 손님') RETURNING id"
            ),
            {"b": brokerage_id},
        ).scalar_one()
        requirement_id = session.execute(
            text(
                "INSERT INTO property_requirement (brokerage_id, party_id, demand_type)"
                " VALUES (:b, :party, '매수') RETURNING id"
            ),
            {"b": brokerage_id, "party": party_id},
        ).scalar_one()
        run_id = session.execute(
            text(
                "INSERT INTO agent_run (brokerage_id, run_group_id, run_type, agent_type,"
                " status, trigger_type, requested_by, target_requirement_id, input_data_version)"
                " VALUES (:b, :group, 'CROSS_JUDGMENT', 'BROKERAGE_WORKFLOW', 'QUEUED',"
                " 'USER_REQUEST', :user, :requirement, 1) RETURNING id"
            ),
            {
                "b": brokerage_id,
                "group": str(uuid4()),
                "user": user_id,
                "requirement": requirement_id,
            },
        ).scalar_one()
        session.commit()

        # X-CSRF-Token 없이도 상태를 변경하지 않는 GET은 허용된다.
        response = client.get(f"/api/v1/f3/runs/{run_id}/result")
        assert response.status_code == 200
