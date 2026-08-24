"""F3 구조화 관심없음 피드백 API 통합 테스트."""

from __future__ import annotations

from uuid import uuid4

import pytest
from ledger_fixtures import ledger_client, requires_database
from sqlalchemy import text
from sqlmodel import Session

from core.config import Config


def _store_feedback_targets(
    session: Session, brokerage_id: int, user_id: int
) -> tuple[int, int]:
    party_id = session.execute(
        text(
            "INSERT INTO party (brokerage_id, party_type, name)"
            " VALUES (:b, 'PERSON', '합성 피드백 손님') RETURNING id"
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
            " status, trigger_type, requested_by, target_requirement_id)"
            " VALUES (:b, :group, 'CROSS_JUDGMENT', 'BROKERAGE_WORKFLOW', 'COMPLETED',"
            " 'USER_REQUEST', :user, :requirement) RETURNING id"
        ),
        {
            "b": brokerage_id,
            "group": str(uuid4()),
            "user": user_id,
            "requirement": requirement_id,
        },
    ).scalar_one()
    anchor_card_id = session.execute(
        text(
            "INSERT INTO negotiation_position_analysis (brokerage_id, agent_run_id,"
            " negotiation_side, requirement_id, cache_key, data_version)"
            " VALUES (:b, :run, 'REQUIREMENT', :requirement, :cache, 1) RETURNING id"
        ),
        {
            "b": brokerage_id,
            "run": run_id,
            "requirement": requirement_id,
            "cache": f"feedback-anchor:{uuid4().hex}",
        },
    ).scalar_one()
    candidate_card_id = session.execute(
        text(
            "INSERT INTO negotiation_position_analysis (brokerage_id, agent_run_id,"
            " negotiation_side, requirement_id, cache_key, data_version)"
            " VALUES (:b, :run, 'REQUIREMENT', :requirement, :cache, 1) RETURNING id"
        ),
        {
            "b": brokerage_id,
            "run": run_id,
            "requirement": requirement_id,
            "cache": f"feedback-candidate:{uuid4().hex}",
        },
    ).scalar_one()
    match_evaluation_id = session.execute(
        text(
            "INSERT INTO match_evaluation (brokerage_id, agent_run_id,"
            " anchor_position_analysis_id, data_version)"
            " VALUES (:b, :run, :anchor, 1) RETURNING id"
        ),
        {"b": brokerage_id, "run": run_id, "anchor": anchor_card_id},
    ).scalar_one()
    candidate_evaluation_id = session.execute(
        text(
            "INSERT INTO match_candidate_evaluation (brokerage_id, match_evaluation_id,"
            " candidate_position_analysis_id, match_grade, match_rank, evaluation_basis)"
            " VALUES (:b, :evaluation, :card, 'WEAK', 1, '합성 판정') RETURNING id"
        ),
        {
            "b": brokerage_id,
            "evaluation": match_evaluation_id,
            "card": candidate_card_id,
        },
    ).scalar_one()
    session.commit()
    return anchor_card_id, candidate_evaluation_id


@requires_database
@pytest.mark.parametrize(
    ("target", "target_index", "reason", "field_name"),
    [
        ("POSITION_ANALYSIS", 0, "CONDITION_MISMATCH", None),
        ("MATCH_CANDIDATE", 1, "WRONG_JUDGMENT", "match_grade"),
    ],
)
def test_feedback_is_stored_for_a_tenant_owned_target(
    config: Config,
    target: str,
    target_index: int,
    reason: str,
    field_name: str | None,
) -> None:
    with ledger_client(config) as (client, session, brokerage_id, user_id):
        targets = _store_feedback_targets(session, brokerage_id, user_id)
        target_id = targets[target_index]

        response = client.post(
            "/api/v1/f3/feedback",
            json={
                "target": target,
                "target_id": target_id,
                "reason": reason,
                "field_name": field_name,
            },
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body.keys() == {
            "feedback_id",
            "target",
            "target_id",
            "feedback_type",
            "reason",
            "field_name",
            "created_at",
        }
        assert body["created_at"] is not None
        assert {key: value for key, value in body.items() if key != "created_at"} == {
            "feedback_id": body["feedback_id"],
            "target": target,
            "target_id": target_id,
            "feedback_type": "NOT_INTERESTED",
            "reason": reason,
            "field_name": field_name,
        }
        stored = session.execute(
            text(
                "SELECT brokerage_id, position_analysis_id, match_candidate_evaluation_id,"
                " feedback_type, reason, field_name, original_value, corrected_value, detail,"
                " correction_interaction_id, created_by FROM ai_decision_feedback WHERE id = :id"
            ),
            {"id": body["feedback_id"]},
        ).one()
        assert stored.brokerage_id == brokerage_id
        assert stored.position_analysis_id == (target_id if target_index == 0 else None)
        assert stored.match_candidate_evaluation_id == (target_id if target_index == 1 else None)
        assert stored.feedback_type == "NOT_INTERESTED"
        assert stored.reason == reason
        assert stored.field_name == field_name
        assert stored.original_value is None
        assert stored.corrected_value is None
        assert stored.detail is None
        assert stored.correction_interaction_id is None
        assert stored.created_by == user_id


@requires_database
def test_feedback_hides_another_brokerages_target(config: Config) -> None:
    with ledger_client(config) as (client, session, _brokerage_id, _user_id):
        other_brokerage_id = session.execute(
            text("INSERT INTO brokerage (name) VALUES ('다른 피드백 사무소') RETURNING id")
        ).scalar_one()
        other_user_id = session.execute(
            text(
                "INSERT INTO app_user (brokerage_id, login_id, password_hash, display_name, role)"
                " VALUES (:b, :login, 'unused', '다른 사용자', 'OWNER') RETURNING id"
            ),
            {"b": other_brokerage_id, "login": f"feedback-{uuid4().hex}"},
        ).scalar_one()
        foreign_card_id, _ = _store_feedback_targets(
            session, other_brokerage_id, other_user_id
        )

        response = client.post(
            "/api/v1/f3/feedback",
            json={
                "target": "POSITION_ANALYSIS",
                "target_id": foreign_card_id,
                "reason": "OTHER",
            },
        )

        assert response.status_code == 404
        assert response.json()["code"] == "NOT_FOUND"


@requires_database
@pytest.mark.parametrize(
    "extra",
    [
        {"feedback_type": "CORRECTION"},
        {"detail": "전화번호 010-0000-0000"},
        {"corrected_value": "임의 정정"},
        {"brokerage_id": 999},
        {"created_by": 999},
    ],
)
def test_feedback_rejects_server_owned_or_free_text_fields(
    config: Config, extra: dict[str, object]
) -> None:
    with ledger_client(config) as (client, session, brokerage_id, user_id):
        card_id, _ = _store_feedback_targets(session, brokerage_id, user_id)
        payload = {
            "target": "POSITION_ANALYSIS",
            "target_id": card_id,
            "reason": "OTHER",
        }
        payload.update(extra)

        response = client.post("/api/v1/f3/feedback", json=payload)

        assert response.status_code == 422


@requires_database
@pytest.mark.parametrize(
    "payload",
    [
        {"target": "POSITION_ANALYSIS", "target_id": 0, "reason": "OTHER"},
        {"target": "POSITION_ANALYSIS", "target_id": 1, "reason": "FREE_TEXT"},
        {
            "target": "POSITION_ANALYSIS",
            "target_id": 1,
            "reason": "OTHER",
            "field_name": "전화번호 입력",
        },
    ],
)
def test_feedback_validates_fixed_vocabulary(config: Config, payload: dict[str, object]) -> None:
    with ledger_client(config) as (client, _session, _brokerage_id, _user_id):
        response = client.post("/api/v1/f3/feedback", json=payload)
        assert response.status_code == 422


@requires_database
def test_feedback_requires_authentication(config: Config) -> None:
    with ledger_client(config, authenticate=False) as (client, _session, _brokerage, _user):
        response = client.post(
            "/api/v1/f3/feedback",
            json={"target": "POSITION_ANALYSIS", "target_id": 1, "reason": "OTHER"},
        )
        assert response.status_code == 401


@requires_database
def test_feedback_requires_a_matching_csrf_token(config: Config) -> None:
    token = "feedback-csrf"
    with ledger_client(config, csrf_token=token) as (
        client,
        session,
        brokerage_id,
        user_id,
    ):
        card_id, _ = _store_feedback_targets(session, brokerage_id, user_id)
        payload = {
            "target": "POSITION_ANALYSIS",
            "target_id": card_id,
            "reason": "ALREADY_CONTACTED",
        }

        missing = client.post("/api/v1/f3/feedback", json=payload)
        assert missing.status_code == 403
        assert missing.json()["code"] == "INVALID_CSRF_TOKEN"

        accepted = client.post(
            "/api/v1/f3/feedback",
            json=payload,
            headers={"X-CSRF-Token": token},
        )
        assert accepted.status_code == 201
