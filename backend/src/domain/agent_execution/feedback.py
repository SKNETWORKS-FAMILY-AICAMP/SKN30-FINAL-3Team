from __future__ import annotations

from enum import StrEnum

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from core.errors import NotFoundError
from domain.agent_execution import repository
from domain.agent_execution.models import AiDecisionFeedback

NOT_INTERESTED_FEEDBACK_TYPE = "NOT_INTERESTED"


class FeedbackTarget(StrEnum):
    POSITION_ANALYSIS = "POSITION_ANALYSIS"
    MATCH_CANDIDATE = "MATCH_CANDIDATE"


class FeedbackReason(StrEnum):
    CONDITION_MISMATCH = "CONDITION_MISMATCH"
    ALREADY_CONTACTED = "ALREADY_CONTACTED"
    WRONG_JUDGMENT = "WRONG_JUDGMENT"
    OTHER = "OTHER"


class FeedbackField(StrEnum):
    NEGOTIATION_INTENT = "negotiation_intent"
    URGENCY = "urgency"
    PREFERRED_TIMING = "preferred_timing"
    FLEXIBLE_CONDITIONS = "flexible_conditions"
    INFLEXIBLE_CONDITIONS = "inflexible_conditions"
    CONTACTABILITY_STATUS = "contactability_status"
    PRICE = "price"
    MATCH_GRADE = "match_grade"
    EVALUATION_BASIS = "evaluation_basis"
    PRIMARY_OBSTACLE = "primary_obstacle"
    POSSIBLE_CONCESSION = "possible_concession"
    RECOMMENDED_ACTION = "recommended_action"
    EXCLUSION_REASON = "exclusion_reason"


class FeedbackTargetError(RuntimeError):
    """저장된 피드백 대상이 없거나 둘이라 공개 대상으로 변환할 수 없다."""


def feedback_target_of(stored: AiDecisionFeedback) -> tuple[FeedbackTarget, int]:
    position_id = stored.position_analysis_id
    candidate_id = stored.match_candidate_evaluation_id
    if position_id is not None and candidate_id is None:
        return FeedbackTarget.POSITION_ANALYSIS, position_id
    if candidate_id is not None and position_id is None:
        return FeedbackTarget.MATCH_CANDIDATE, candidate_id
    raise FeedbackTargetError("feedback must target exactly one position or candidate")


def record_not_interested_feedback(
    session: Session,
    brokerage_id: int,
    created_by: int,
    target: FeedbackTarget,
    target_id: int,
    reason: FeedbackReason,
    field_name: FeedbackField | None,
) -> AiDecisionFeedback:
    """사무소 소유 대상을 확인하고 자유문자 없는 관심없음 피드백을 기록한다."""
    position_analysis_id: int | None = None
    candidate_evaluation_id: int | None = None

    if target is FeedbackTarget.POSITION_ANALYSIS:
        if repository.find_position_card(session, brokerage_id, target_id) is None:
            raise NotFoundError("position analysis is not found")
        position_analysis_id = target_id
    else:
        if repository.find_candidate_judgment(session, brokerage_id, target_id) is None:
            raise NotFoundError("match candidate evaluation is not found")
        candidate_evaluation_id = target_id

    feedback = AiDecisionFeedback(
        brokerage_id=brokerage_id,
        position_analysis_id=position_analysis_id,
        match_candidate_evaluation_id=candidate_evaluation_id,
        feedback_type=NOT_INTERESTED_FEEDBACK_TYPE,
        reason=reason.value,
        field_name=field_name.value if field_name is not None else None,
        original_value=None,
        corrected_value=None,
        detail=None,
        correction_interaction_id=None,
        created_by=created_by,
    )
    try:
        repository.add_decision_feedback(session, feedback)
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise

    session.refresh(feedback)
    return feedback
