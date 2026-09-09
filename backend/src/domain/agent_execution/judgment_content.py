"""저장된 판정의 공개 내용 조립. HTTP와 모델 실행에 의존하지 않는다."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlmodel import Session

from domain.agent_execution import repository, results
from domain.agent_execution.judgment_targets import TargetLabel
from domain.agent_execution.models import AnchorType, MatchEvaluation
from domain.agent_execution.results import CandidateView, CardView


def safe_evidence(item: Any, allowed_ids: set[int]) -> dict[str, Any] | None:
    interaction_id = item.interaction_id
    if interaction_id is not None and interaction_id not in allowed_ids:
        return None
    return {
        "field_name": item.field_name,
        "evidence_type": item.evidence_type,
        "interaction_id": interaction_id,
        "quote_text": item.quote_text,
        "quote_start_offset": item.quote_start_offset,
        "quote_end_offset": item.quote_end_offset,
        "note": item.note,
        "evidence_side": getattr(item, "evidence_side", None),
    }


def allowed_logs(session: Session, b: int, label: TargetLabel) -> list[Any]:
    scope = repository.build_interaction_scope(session, b, label.anchor_type, label.anchor_id)
    return repository.list_scoped_interactions(session, scope)


def _safe_analysis(value: Any, allowed_ids: set[int]) -> Any:
    if isinstance(value, dict):
        reference = value.get("interaction_id")
        if reference is not None and reference not in allowed_ids:
            return None
        return {key: _safe_analysis(item, allowed_ids) for key, item in value.items()}
    if isinstance(value, list):
        return [clean for item in value if (clean := _safe_analysis(item, allowed_ids)) is not None]
    return value


def public_card(card: CardView | None, allowed_ids: set[int]) -> dict[str, Any] | None:
    if card is None:
        return None
    return {
        "position_analysis_id": card.position_analysis_id,
        "negotiation_side": card.negotiation_side,
        "target_label": card.target_label,
        "generated_at": card.generated_at,
        "analysis": _safe_analysis(card.analysis, allowed_ids),
        "evidence": [
            value
            for item in card.evidence
            if (value := safe_evidence(item, allowed_ids)) is not None
        ],
    }


def candidate_summary(view: CandidateView, label: TargetLabel) -> dict[str, Any]:
    judgment = view.judgment
    return {
        "candidate_id": view.candidate_id,
        "current_eligibility": label.eligibility,
        "rank": view.rank,
        "selected_for_cards": view.selected_for_cards,
        "sql_score": view.score,
        "price_amount": view.price_amount,
        "monthly_amount": view.monthly_amount,
        "received_at": view.received_at,
        "judgment_id": judgment.id if judgment else None,
        "match_grade": judgment.match_grade if judgment else None,
        "evaluation_basis": judgment.evaluation_basis if judgment else None,
        "primary_obstacle": judgment.primary_obstacle if judgment else None,
        "possible_concession": judgment.possible_concession if judgment else None,
        "recommended_action": judgment.recommended_action if judgment else None,
        "exclusion_reason": judgment.exclusion_reason if judgment else None,
        "evidence": [],
        "target": label.public(),
        "position_card": None,
        "recent_records": [],
    }


def pair_feedback(
    session: Session, brokerage_id: int, anchor: TargetLabel, candidate: TargetLabel
) -> list[dict[str, Any]]:
    listing_id = (
        anchor.anchor_id if anchor.anchor_type is AnchorType.LISTING else candidate.anchor_id
    )
    requirement_id = (
        candidate.anchor_id if anchor.anchor_type is AnchorType.LISTING else anchor.anchor_id
    )
    rows = session.execute(
        text("""
        SELECT f.id, f.created_at, f.reason
        FROM ai_decision_feedback f
        JOIN match_candidate_evaluation j
          ON (j.brokerage_id,j.id)=(f.brokerage_id,f.match_candidate_evaluation_id)
        JOIN match_evaluation h ON (h.brokerage_id,h.id)=(j.brokerage_id,j.match_evaluation_id)
        JOIN negotiation_position_analysis ac
          ON (ac.brokerage_id,ac.id)=(h.brokerage_id,h.anchor_position_analysis_id)
        JOIN negotiation_position_analysis cc
          ON (cc.brokerage_id,cc.id)=(j.brokerage_id,j.candidate_position_analysis_id)
        WHERE f.brokerage_id=:b AND
          ((ac.listing_id=:l AND cc.requirement_id=:r) OR
           (cc.listing_id=:l AND ac.requirement_id=:r))
        ORDER BY f.created_at DESC, f.id DESC LIMIT 5
    """),
        {"b": brokerage_id, "l": listing_id, "r": requirement_id},
    ).mappings()
    reasons = {"ALREADY_CONTACTED", "CONDITION_MISMATCH", "WRONG_JUDGMENT", "OTHER"}
    return [
        {
            "record_id": row["id"],
            "record_type": "FEEDBACK",
            "created_at": row["created_at"],
            "scope": "PAIR",
            "anchor_type": candidate.anchor_type.value,
            "anchor_id": candidate.anchor_id,
            "interaction_id": None,
            "reason": row["reason"] if row["reason"] in reasons else "OTHER",
        }
        for row in rows
    ]


def enrich_selected(
    session: Session,
    brokerage_id: int,
    header: MatchEvaluation,
    view: CandidateView,
    anchor: TargetLabel,
    label: TargetLabel,
    anchor_log_ids: set[int],
) -> dict[str, Any]:
    value = candidate_summary(view, label)
    logs = allowed_logs(session, brokerage_id, label)
    ids = {item.id for item in logs if item.id is not None}
    value["evidence"] = [
        clean
        for item in view.evidence
        if (
            clean := safe_evidence(
                item, anchor_log_ids if item.evidence_side == anchor.anchor_type.value else ids
            )
        )
        is not None
    ]
    card_id = view.judgment.candidate_position_analysis_id if view.judgment else None
    if card_id is not None:
        card = repository.find_position_card(session, brokerage_id, card_id)
        if card is not None and card.invalidated_at is None:
            value["position_card"] = public_card(results._card_view(session, card), ids)
    records = pair_feedback(session, brokerage_id, anchor, label)
    records.extend(
        {
            "record_id": item.id,
            "record_type": "INTERACTION",
            "created_at": item.interaction_at,
            "scope": "GENERAL",
            "anchor_type": label.anchor_type.value,
            "anchor_id": label.anchor_id,
            "interaction_id": item.id,
            "reason": None,
        }
        for item in logs[-3:]
    )
    value["recent_records"] = sorted(
        records, key=lambda row: str(row["created_at"] or ""), reverse=True
    )
    return value
