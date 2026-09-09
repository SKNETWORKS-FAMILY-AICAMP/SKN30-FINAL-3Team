"""Reuse validated persisted judgments only for an identical final AI request and binding."""

from __future__ import annotations

from brokerage_ai.f3 import (
    BrokerageJudgmentContractError,
    BrokerageJudgmentRequest,
    BrokerageJudgmentResult,
    BrokerageJudgmentTarget,
    validate_judgment_result,
)
from pydantic import ValidationError
from sqlalchemy import text
from sqlmodel import Session

from domain.agent_execution import repository
from domain.agent_execution.freshness import digest


def request_identity(request: BrokerageJudgmentRequest, binding_snapshot: dict) -> str:
    return digest([request.model_dump(mode="json"), binding_snapshot])


def find_reusable_judgment(
    session: Session, brokerage_id: int, request: BrokerageJudgmentRequest, binding_snapshot: dict
) -> BrokerageJudgmentResult | None:
    identity = request_identity(request, binding_snapshot)
    result_id = session.execute(
        text("""SELECT m.id FROM match_evaluation m
        JOIN agent_run r ON r.brokerage_id=m.brokerage_id AND r.id=m.agent_run_id
        WHERE r.brokerage_id=:tenant AND r.status='COMPLETED'
          AND r.parent_run_id IS NULL AND r.run_type='CROSS_JUDGMENT'
          AND r.redacted_output_snapshot->'judgment'->>'input_identity'=:identity
        ORDER BY r.id DESC LIMIT 1"""),
        {"tenant": brokerage_id, "identity": identity},
    ).scalar_one_or_none()
    if result_id is None:
        return None
    judgments = repository.list_candidate_judgments(session, brokerage_id, result_id)
    evidence = repository.list_candidate_judgment_evidence(
        session, brokerage_id, [item.id or 0 for item in judgments]
    )
    candidates = []
    for item in judgments:
        sources = []
        for row in evidence:
            if row.match_candidate_evaluation_id != item.id:
                continue
            source = (
                {
                    "kind": "QUOTE",
                    "interaction_id": row.interaction_id,
                    "quote_text": row.quote_text,
                }
                if row.evidence_type == "QUOTE"
                else {"kind": "INFERENCE", "note": row.note}
            )
            sources.append(
                {"evidence_side": row.evidence_side, "field_name": row.field_name, "source": source}
            )
        candidates.append(
            {
                "card_id": item.candidate_position_analysis_id,
                "grade": item.match_grade,
                "rank": item.match_rank,
                "comparison_basis": item.evaluation_basis,
                "primary_obstacle": item.primary_obstacle,
                "possible_concession": item.possible_concession,
                "recommended_action": item.recommended_action or None,
                "rejection_reason": item.exclusion_reason,
                "evidence": sources,
            }
        )
    try:
        result = BrokerageJudgmentResult.model_validate(
            {
                "target": BrokerageJudgmentTarget.from_request(request),
                "candidates": candidates,
                "prompt_version": binding_snapshot["prompt_version"],
                "workflow_version": binding_snapshot["workflow_version"],
            }
        )
        validate_judgment_result(request, result)
    except (ValidationError, BrokerageJudgmentContractError):
        return None  # Invalid persisted content cannot become a cache hit.
    return result  # No provider usage is charged again; diagnostics intentionally stays None.
