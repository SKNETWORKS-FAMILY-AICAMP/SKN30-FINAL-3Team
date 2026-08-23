"""F3 실행 재사용, 결과 조회와 피드백 API.

실제 PostgreSQL 과 실제 인증 경로를 쓴다. 확인하는 것은 넷이다. 같은 앵커를 다시 눌러도
실행이 하나인가, 결과 응답이 무엇을 싣고 무엇을 싣지 않는가, 다른 사무소가 격리되는가,
그리고 피드백이 세션에서만 작성자를 도출하는가.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from ledger_fixtures import create_complex, create_unit, ledger_client, requires_database
from sqlalchemy import text
from sqlmodel import Session

from core.config import Config

CSRF_TOKEN = "f3-result-csrf"


def create_listing(client: TestClient, complex_id: int, **overrides: object) -> dict:
    unit = create_unit(client, complex_id, **overrides)
    unit_id = unit["unit"]["id"]
    response = client.post(
        f"/api/v1/property-units/{unit_id}/listings",
        json={"is_sale_available": True, "sale_price": 2_880_000_000},
    )
    assert response.status_code == 201, response.text
    return response.json()


def queue(client: TestClient, listing_id: int) -> dict:
    response = client.post(
        "/api/v1/f3/runs", json={"anchor_type": "LISTING", "anchor_id": listing_id}
    )
    assert response.status_code == 202, response.text
    return response.json()


def run_count(session: Session, brokerage_id: int) -> int:
    return session.execute(
        text("SELECT count(*) FROM agent_run WHERE brokerage_id = :b"), {"b": brokerage_id}
    ).scalar_one()


def store_card(session: Session, brokerage_id: int, run_id: int, listing_id: int) -> int:
    """앵커 카드와 근거를 직접 넣는다. 이 테스트가 보는 것은 조회 경로다."""
    unit_id = session.execute(
        text("SELECT unit_id FROM property_listing WHERE id = :i"), {"i": listing_id}
    ).scalar_one()
    snapshot = (
        '{"contract_version": "position-card:v1",'
        ' "target": {"negotiation_side": "LISTING", "anchor_id": 1,'
        ' "target_label": "검증단지 1801호", "source": {"data_version": 1,'
        ' "interaction_count": 0, "last_interaction_at": null, "max_interaction_id": null}},'
        ' "analysis": {"intent": {"value": "PRESENT", "evidence": []},'
        ' "urgency": {"value": "NORMAL", "evidence": []}},'
        ' "prompt_version": "position-card-prompt:v1",'
        ' "workflow_version": "position-card-workflow:v1",'
        ' "diagnostics": {"provider": "vllm", "model": "secret-model", "latency_ms": 1.0}}'
    )
    card_id = session.execute(
        text(
            "INSERT INTO negotiation_position_analysis (brokerage_id, agent_run_id,"
            " negotiation_side, unit_id, listing_id, target_label, cache_key, data_version,"
            " analysis_snapshot)"
            " VALUES (:b, :r, 'LISTING', :u, :l, '검증단지 1801호', :k, 1, CAST(:s AS jsonb))"
            " RETURNING id"
        ),
        {
            "b": brokerage_id,
            "r": run_id,
            "u": unit_id,
            "l": listing_id,
            "k": f"test:{uuid4().hex}",
            "s": snapshot,
        },
    ).scalar_one()
    session.execute(
        text(
            "INSERT INTO negotiation_position_evidence (brokerage_id, position_analysis_id,"
            " field_name, evidence_type, note) VALUES (:b, :p, 'intent', 'INFERENCE', '정황')"
        ),
        {"b": brokerage_id, "p": card_id},
    )
    session.execute(
        text(
            "UPDATE agent_run SET status = 'ANCHOR_READY', redacted_output_snapshot ="
            " jsonb_build_object('position_analysis_id', :c) WHERE id = :r"
        ),
        {"c": card_id, "r": run_id},
    )
    session.commit()
    return card_id


def store_judgment(
    session: Session, brokerage_id: int, run_id: int, anchor_card_id: int
) -> tuple[int, int]:
    """후보 카드 1장, 판정 헤더와 후보 판정을 직접 넣는다."""
    consent_by = session.execute(
        text("SELECT id FROM app_user WHERE brokerage_id = :b LIMIT 1"), {"b": brokerage_id}
    ).scalar_one()
    party_id = session.execute(
        text(
            "INSERT INTO party (brokerage_id, party_type, name, privacy_consent_at,"
            " privacy_consent_by) VALUES (:b, 'PERSON', '박손님', now(), :u) RETURNING id"
        ),
        {"b": brokerage_id, "u": consent_by},
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
        {"b": brokerage_id, "r": run_id, "q": requirement_id, "k": f"test:{uuid4().hex}"},
    ).scalar_one()
    selection = json.dumps(
        {
            "schema": "candidate-selection:v1",
            "criteria": {
                "candidate_side": "REQUIREMENT",
                "price_kind": "SALE",
                "price_amount": 2_800_000_000,
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
                    "received_at": "2026-08-01",
                },
                # 카드화되지 않은 나머지 후보. 목록에서 사라지면 안 된다 (F3-BR-14).
                {
                    "candidate_id": 999999,
                    "rank": 2,
                    "selected_for_cards": False,
                    "score": "0.100000",
                    "price_amount": None,
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
    header_id = session.execute(
        text(
            "INSERT INTO match_evaluation (brokerage_id, agent_run_id,"
            " anchor_position_analysis_id, candidate_count, data_version,"
            " candidate_selection_snapshot)"
            " VALUES (:b, :r, :a, 1, 1, CAST(:s AS jsonb)) RETURNING id"
        ),
        {"b": brokerage_id, "r": run_id, "a": anchor_card_id, "s": selection},
    ).scalar_one()
    candidate_evaluation_id = session.execute(
        text(
            "INSERT INTO match_candidate_evaluation (brokerage_id, match_evaluation_id,"
            " candidate_position_analysis_id, match_grade, match_rank, evaluation_basis,"
            " primary_obstacle, exclusion_reason, recommended_action)"
            " VALUES (:b, :m, :c, 'STRONG', 1, '예산이 가장 가깝다', '가격 차', null,"
            " CAST(:a AS jsonb)) RETURNING id"
        ),
        {
            "b": brokerage_id,
            "m": header_id,
            "c": candidate_card_id,
            "a": '{"contact_side": "REQUIREMENT", "channel": "MESSAGE", "message": "먼저 확인"}',
        },
    ).scalar_one()
    session.execute(
        text(
            "INSERT INTO match_candidate_evidence (brokerage_id,"
            " match_candidate_evaluation_id, evidence_side, field_name, evidence_type, note)"
            " VALUES (:b, :c, 'LISTING', 'price', 'INFERENCE', '카드 값을 비교했다')"
        ),
        {"b": brokerage_id, "c": candidate_evaluation_id},
    )
    session.execute(
        text("UPDATE agent_run SET status = 'COMPLETED', completed_at = now() WHERE id = :r"),
        {"r": run_id},
    )
    session.commit()
    return candidate_evaluation_id, requirement_id


def foreign_run(session: Session) -> int:
    """다른 사무소의 실행 하나. 바깥 transaction 이 끝나며 함께 롤백된다."""
    other = session.execute(
        text("INSERT INTO brokerage (name) VALUES (:n) RETURNING id"),
        {"n": f"다른 사무소 {uuid4().hex[:6]}"},
    ).scalar_one()
    other_user = session.execute(
        text(
            "INSERT INTO app_user (brokerage_id, login_id, password_hash, display_name, role)"
            " VALUES (:b, :l, 'unused', '남', 'OWNER') RETURNING id"
        ),
        {"b": other, "l": f"other-{uuid4().hex[:8]}"},
    ).scalar_one()
    party_id = session.execute(
        text(
            "INSERT INTO party (brokerage_id, party_type, name, privacy_consent_at,"
            " privacy_consent_by) VALUES (:b, 'PERSON', '남의손님', now(), :u) RETURNING id"
        ),
        {"b": other, "u": other_user},
    ).scalar_one()
    requirement_id = session.execute(
        text(
            "INSERT INTO property_requirement (brokerage_id, party_id, demand_type)"
            " VALUES (:b, :p, '매수') RETURNING id"
        ),
        {"b": other, "p": party_id},
    ).scalar_one()
    stored = session.execute(
        text(
            "INSERT INTO agent_run (brokerage_id, run_group_id, run_type, agent_type, status,"
            " trigger_type, requested_by, target_requirement_id, input_data_version)"
            " VALUES (:b, :g, 'CROSS_JUDGMENT', 'BROKERAGE_WORKFLOW', 'QUEUED',"
            " 'USER_REQUEST', :u, :q, 1) RETURNING id"
        ),
        {"b": other, "g": str(uuid4()), "u": other_user, "q": requirement_id},
    ).scalar_one()
    session.commit()
    return stored


def foreign_card(session: Session) -> int:
    """다른 사무소의 포지션 카드 하나."""
    run_id = foreign_run(session)
    row = session.execute(
        text("SELECT brokerage_id, target_requirement_id FROM agent_run WHERE id = :i"),
        {"i": run_id},
    ).one()
    stored = session.execute(
        text(
            "INSERT INTO negotiation_position_analysis (brokerage_id, agent_run_id,"
            " negotiation_side, requirement_id, cache_key, data_version)"
            " VALUES (:b, :r, 'REQUIREMENT', :q, :k, 1) RETURNING id"
        ),
        {"b": row[0], "r": run_id, "q": row[1], "k": f"test:{uuid4().hex}"},
    ).scalar_one()
    session.commit()
    return stored


# ── 실행 재사용 ────────────────────────────────────────────────────────────────


@requires_database
def test_the_same_anchor_and_version_reuses_the_active_run(config: Config) -> None:
    """데이터 변경 없이 반복 진입하면 새 실행을 만들지 않는다 (F3-CR-12)."""
    with ledger_client(config) as (client, session, brokerage_id, _user):
        complex_id = create_complex(client, session, brokerage_id, "재사용단지")
        listing = create_listing(client, complex_id)

        first = queue(client, listing["id"])
        second = queue(client, listing["id"])

        assert second["run_id"] == first["run_id"]
        assert run_count(session, brokerage_id) == 1


@requires_database
def test_a_completed_run_of_the_same_version_is_reused(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _user):
        complex_id = create_complex(client, session, brokerage_id, "완료단지")
        listing = create_listing(client, complex_id)
        first = queue(client, listing["id"])
        session.execute(
            text("UPDATE agent_run SET status = 'COMPLETED' WHERE id = :i"),
            {"i": first["run_id"]},
        )
        session.commit()

        second = queue(client, listing["id"])

        assert second["run_id"] == first["run_id"]
        assert run_count(session, brokerage_id) == 1


@requires_database
def test_a_changed_input_version_creates_a_new_run(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _user):
        complex_id = create_complex(client, session, brokerage_id, "변경단지")
        listing = create_listing(client, complex_id)
        first = queue(client, listing["id"])

        updated = client.patch(
            f"/api/v1/property-listings/{listing['id']}",
            json={"row_version": listing["row_version"], "sale_price": 2_700_000_000},
        )
        assert updated.status_code == 200, updated.text
        second = queue(client, listing["id"])

        assert second["run_id"] != first["run_id"]
        assert second["input_data_version"] != first["input_data_version"]
        assert run_count(session, brokerage_id) == 2


@requires_database
def test_a_failed_run_is_not_reused(config: Config) -> None:
    """실패한 실행을 재사용하면 다시 눌러도 영영 같은 실패만 보인다."""
    with ledger_client(config) as (client, session, brokerage_id, _user):
        complex_id = create_complex(client, session, brokerage_id, "실패단지")
        listing = create_listing(client, complex_id)
        first = queue(client, listing["id"])
        session.execute(
            text("UPDATE agent_run SET status = 'FAILED_TERMINAL' WHERE id = :i"),
            {"i": first["run_id"]},
        )
        session.commit()

        second = queue(client, listing["id"])

        assert second["run_id"] != first["run_id"]


# ── 결과 조회 ──────────────────────────────────────────────────────────────────


@requires_database
def test_a_queued_run_result_is_empty_but_valid(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _user):
        complex_id = create_complex(client, session, brokerage_id, "대기단지")
        listing = create_listing(client, complex_id)
        run = queue(client, listing["id"])

        response = client.get(f"/api/v1/f3/runs/{run['run_id']}/result")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "QUEUED"
        assert body["anchor_card"] is None
        assert body["candidate_selection"]["criteria"] is None
        assert body["candidates"] == []


@requires_database
def test_the_anchor_card_appears_before_the_candidates(config: Config) -> None:
    """5초를 넘길 것 같으면 앵커 카드를 먼저 표시한다 (F3-CR-09)."""
    with ledger_client(config) as (client, session, brokerage_id, _user):
        complex_id = create_complex(client, session, brokerage_id, "앵커단지")
        listing = create_listing(client, complex_id)
        run = queue(client, listing["id"])
        store_card(session, brokerage_id, run["run_id"], listing["id"])

        body = client.get(f"/api/v1/f3/runs/{run['run_id']}/result").json()

        assert body["status"] == "ANCHOR_READY"
        assert body["anchor_card"]["target_label"] == "검증단지 1801호"
        assert body["anchor_card"]["analysis"]["intent"]["value"] == "PRESENT"
        assert body["anchor_card"]["evidence"][0]["evidence_type"] == "INFERENCE"
        assert body["candidates"] == []


@requires_database
def test_a_completed_result_carries_grades_ranks_and_evidence(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _user):
        complex_id = create_complex(client, session, brokerage_id, "완료조회단지")
        listing = create_listing(client, complex_id)
        run = queue(client, listing["id"])
        card_id = store_card(session, brokerage_id, run["run_id"], listing["id"])
        _, requirement_id = store_judgment(session, brokerage_id, run["run_id"], card_id)

        body = client.get(f"/api/v1/f3/runs/{run['run_id']}/result").json()

        assert body["status"] == "COMPLETED"
        selection = body["candidate_selection"]
        assert selection["criteria"]["price_source"] == "ESTIMATED"
        assert selection["total_count"] == 2
        assert selection["carded_count"] == 1
        assert selection["remaining_count"] == 1

        judged = next(c for c in body["candidates"] if c["candidate_id"] == requirement_id)
        assert judged["match_grade"] == "STRONG"
        assert judged["rank"] == 1
        assert judged["evaluation_basis"] == "예산이 가장 가깝다"
        assert judged["primary_obstacle"] == "가격 차"
        assert judged["recommended_action"]["channel"] == "MESSAGE"
        assert judged["evidence"][0]["evidence_side"] == "LISTING"

        # 15건 이후 후보도 목록에서 사라지지 않는다 (F3-BR-14).
        remaining = next(c for c in body["candidates"] if c["candidate_id"] == 999999)
        assert remaining["selected_for_cards"] is False
        assert remaining["match_grade"] is None, "판정하지 않은 후보에 등급을 붙이지 않는다"
        assert body["candidates_total"] == 2


@requires_database
def test_the_result_hides_tenant_model_and_prompt_details(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _user):
        complex_id = create_complex(client, session, brokerage_id, "비공개단지")
        listing = create_listing(client, complex_id)
        run = queue(client, listing["id"])
        card_id = store_card(session, brokerage_id, run["run_id"], listing["id"])
        store_judgment(session, brokerage_id, run["run_id"], card_id)

        response = client.get(f"/api/v1/f3/runs/{run['run_id']}/result")
        body = response.json()

        assert set(body) == {
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
            "secret-model",
        ):
            assert forbidden not in raw, forbidden


@requires_database
def test_the_candidate_list_is_paginated(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _user):
        complex_id = create_complex(client, session, brokerage_id, "페이지단지")
        listing = create_listing(client, complex_id)
        run = queue(client, listing["id"])
        card_id = store_card(session, brokerage_id, run["run_id"], listing["id"])
        store_judgment(session, brokerage_id, run["run_id"], card_id)

        body = client.get(f"/api/v1/f3/runs/{run['run_id']}/result?limit=1&offset=1").json()

        assert body["limit"] == 1
        assert body["offset"] == 1
        assert len(body["candidates"]) == 1
        assert body["candidates_total"] == 2


@requires_database
def test_a_missing_run_result_is_not_found(config: Config) -> None:
    with ledger_client(config) as (client, _session, _brokerage_id, _user):
        assert client.get("/api/v1/f3/runs/999999/result").status_code == 404


@requires_database
def test_another_brokerage_run_result_is_not_found(config: Config) -> None:
    with ledger_client(config) as (client, session, _brokerage_id, _user):
        stranger = foreign_run(session)

        assert client.get(f"/api/v1/f3/runs/{stranger}/result").status_code == 404


# ── 피드백 ─────────────────────────────────────────────────────────────────────


@requires_database
def test_feedback_is_stored_with_the_session_user(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, user_id):
        complex_id = create_complex(client, session, brokerage_id, "피드백단지")
        listing = create_listing(client, complex_id)
        run = queue(client, listing["id"])
        card_id = store_card(session, brokerage_id, run["run_id"], listing["id"])
        candidate_evaluation_id, _ = store_judgment(session, brokerage_id, run["run_id"], card_id)

        response = client.post(
            "/api/v1/f3/feedback",
            json={
                "target": "MATCH_CANDIDATE",
                "target_id": candidate_evaluation_id,
                "feedback_type": "NOT_INTERESTED",
                "reason": "ALREADY_CONTACTED",
                "detail": "어제 통화했습니다",
            },
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["reason"] == "ALREADY_CONTACTED"
        # 작성자와 사무소는 응답에 싣지 않는다.
        assert set(body) == {
            "feedback_id",
            "target",
            "target_id",
            "feedback_type",
            "reason",
            "created_at",
        }

        stored = (
            session.execute(
                text("SELECT * FROM ai_decision_feedback WHERE id = :i"), {"i": body["feedback_id"]}
            )
            .mappings()
            .one()
        )
        assert stored["created_by"] == user_id
        assert stored["brokerage_id"] == brokerage_id
        assert stored["match_candidate_evaluation_id"] == candidate_evaluation_id
        assert stored["correction_interaction_id"] is None


@requires_database
def test_position_card_feedback_targets_the_card(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _user):
        complex_id = create_complex(client, session, brokerage_id, "카드피드백단지")
        listing = create_listing(client, complex_id)
        run = queue(client, listing["id"])
        card_id = store_card(session, brokerage_id, run["run_id"], listing["id"])

        response = client.post(
            "/api/v1/f3/feedback",
            json={
                "target": "POSITION_ANALYSIS",
                "target_id": card_id,
                "feedback_type": "CORRECTION",
                "reason": "WRONG_JUDGMENT",
                "field_name": "intent",
                "corrected_value": {"value": "WITHDRAWN"},
            },
        )

        assert response.status_code == 201, response.text
        assert response.json()["target"] == "POSITION_ANALYSIS"


@requires_database
def test_feedback_requires_the_csrf_token(config: Config) -> None:
    """상태를 바꾸는 요청이므로 CSRF 를 적용한다."""
    with ledger_client(config, csrf_token=CSRF_TOKEN) as (client, session, brokerage_id, _user):
        # 준비 요청도 같은 검사를 지난다. 기본 헤더로 통과시킨 뒤 검증에서만 뺀다.
        client.headers["X-CSRF-Token"] = CSRF_TOKEN
        complex_id = create_complex(client, session, brokerage_id, "csrf단지")
        listing = create_listing(client, complex_id)
        run = queue(client, listing["id"])
        card_id = store_card(session, brokerage_id, run["run_id"], listing["id"])
        payload = {
            "target": "POSITION_ANALYSIS",
            "target_id": card_id,
            "feedback_type": "CORRECTION",
            "reason": "OTHER",
        }

        wrong = client.post("/api/v1/f3/feedback", json=payload, headers={"X-CSRF-Token": "wrong"})
        del client.headers["X-CSRF-Token"]
        missing = client.post("/api/v1/f3/feedback", json=payload)
        correct = client.post(
            "/api/v1/f3/feedback", json=payload, headers={"X-CSRF-Token": CSRF_TOKEN}
        )

        assert wrong.status_code == 403
        assert missing.status_code == 403
        assert missing.json()["code"] == "INVALID_CSRF_TOKEN"
        assert correct.status_code == 201, correct.text


@requires_database
def test_feedback_on_another_brokerage_result_is_not_found(config: Config) -> None:
    with ledger_client(config) as (client, session, _brokerage_id, _user):
        stranger = foreign_card(session)

        response = client.post(
            "/api/v1/f3/feedback",
            json={
                "target": "POSITION_ANALYSIS",
                "target_id": stranger,
                "feedback_type": "CORRECTION",
                "reason": "OTHER",
            },
        )

        assert response.status_code == 404, response.text
        assert response.json()["code"] == "NOT_FOUND"


@requires_database
@pytest.mark.parametrize(
    "detail",
    ["연락처는 010-1234-5678 입니다", "메일은 buyer@example.com 으로 주세요"],
)
def test_personal_data_in_the_free_text_is_refused(config: Config, detail: str) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _user):
        complex_id = create_complex(client, session, brokerage_id, f"개인정보단지{uuid4().hex[:4]}")
        listing = create_listing(client, complex_id)
        run = queue(client, listing["id"])
        card_id = store_card(session, brokerage_id, run["run_id"], listing["id"])

        response = client.post(
            "/api/v1/f3/feedback",
            json={
                "target": "POSITION_ANALYSIS",
                "target_id": card_id,
                "feedback_type": "CORRECTION",
                "reason": "OTHER",
                "detail": detail,
            },
        )

        assert response.status_code == 422, response.text
        body = response.json()
        assert body["code"] == "PERSONAL_DATA_NOT_ALLOWED"
        # 발견한 값 자체를 응답에 되돌려 주지 않는다.
        assert "010-1234-5678" not in response.text
        assert "buyer@example.com" not in response.text
        assert (
            session.execute(
                text("SELECT count(*) FROM ai_decision_feedback WHERE brokerage_id = :b"),
                {"b": brokerage_id},
            ).scalar_one()
            == 0
        )


@requires_database
def test_an_unknown_reason_is_refused(config: Config) -> None:
    """사유는 고정 어휘다. 자유 문자열로 받으면 집계가 성립하지 않는다 (F3-TR-07)."""
    with ledger_client(config) as (client, session, brokerage_id, _user):
        complex_id = create_complex(client, session, brokerage_id, "어휘단지")
        listing = create_listing(client, complex_id)
        run = queue(client, listing["id"])
        card_id = store_card(session, brokerage_id, run["run_id"], listing["id"])

        response = client.post(
            "/api/v1/f3/feedback",
            json={
                "target": "POSITION_ANALYSIS",
                "target_id": card_id,
                "feedback_type": "CORRECTION",
                "reason": "그냥 별로",
            },
        )

        assert response.status_code == 422


@requires_database
def test_the_body_cannot_carry_a_tenant_or_author(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _user):
        complex_id = create_complex(client, session, brokerage_id, "본문단지")
        listing = create_listing(client, complex_id)
        run = queue(client, listing["id"])
        card_id = store_card(session, brokerage_id, run["run_id"], listing["id"])

        response = client.post(
            "/api/v1/f3/feedback",
            json={
                "target": "POSITION_ANALYSIS",
                "target_id": card_id,
                "feedback_type": "CORRECTION",
                "reason": "OTHER",
                "brokerage_id": 1,
                "created_by": 1,
            },
        )

        assert response.status_code == 422, "선언하지 않은 필드는 거절한다"
