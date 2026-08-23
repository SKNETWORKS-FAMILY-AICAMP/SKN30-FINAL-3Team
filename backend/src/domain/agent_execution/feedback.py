"""AI 판정에 대한 사용자 피드백 (F3-TR-03, F3-CR-17).

대리가 엉뚱한 포지션을 두 번 세우면 아무도 보지 않는다. 「관심없음」과 정정을 사유와 함께
받아 어느 판정이 자주 틀리는지 볼 수 있게 한다.

저장은 기존 `ai_decision_feedback`(migration 007)을 그대로 쓴다. 새 테이블을 만들지 않는다.

`created_by` 와 `brokerage_id` 는 **세션에서만** 도출한다. 요청 본문으로 받으면 남의 사무소
결과에 남의 이름으로 피드백을 남길 수 있다. 정정 상담 로그 생성(F3-TR-02)은 이번 범위가
아니라 `correction_interaction_id` 는 항상 비어 있다.
"""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from core.errors import NotFoundError, ValidationError
from domain.agent_execution import repository
from domain.agent_execution.models import AiDecisionFeedback
from domain.agent_execution.pii_guard import (
    ModelOutputPrivacyError,
    assert_no_personal_data_in_text,
)

# 자유문에 개인정보가 섞였을 때의 공개 오류 코드. 발견한 값 자체는 응답에 넣지 않는다.
PERSONAL_DATA_CODE = "PERSONAL_DATA_NOT_ALLOWED"
PERSONAL_DATA_MESSAGE = "의견에는 성명·연락처·생년월일을 넣을 수 없습니다"

# 자유문 상한. 피드백은 한두 문장이면 충분하고, 길수록 개인정보가 섞일 자리가 늘어난다.
DETAIL_MAX_LENGTH = 500


class FeedbackTarget(StrEnum):
    """피드백 대상. 포지션 카드 한 장이거나 중개 판정 후보 한 건이다."""

    POSITION_ANALYSIS = "POSITION_ANALYSIS"
    MATCH_CANDIDATE = "MATCH_CANDIDATE"


class FeedbackType(StrEnum):
    """무엇을 하는 피드백인가."""

    NOT_INTERESTED = "NOT_INTERESTED"
    CORRECTION = "CORRECTION"


class FeedbackReason(StrEnum):
    """사유 (F3-TR-03). 자유 문자열로 받지 않는다.

    「판정이 틀림」을 대상·항목별로 집계하려면 값이 고정돼 있어야 한다 (F3-TR-07).
    """

    CONDITION_MISMATCH = "CONDITION_MISMATCH"
    ALREADY_CONTACTED = "ALREADY_CONTACTED"
    WRONG_JUDGMENT = "WRONG_JUDGMENT"
    OTHER = "OTHER"


def record_feedback(
    session: Session,
    brokerage_id: int,
    created_by: int,
    *,
    target: FeedbackTarget,
    target_id: int,
    feedback_type: FeedbackType,
    reason: FeedbackReason,
    field_name: str | None = None,
    corrected_value: dict[str, object] | None = None,
    detail: str | None = None,
) -> AiDecisionFeedback:
    """피드백 1건을 저장한다. 대상이 이 사무소의 것이 아니면 404 로 답한다.

    남의 사무소 결과는 존재 여부를 드러내지 않고 없는 것과 **같은 오류**로 거절한다.
    """
    if detail is not None:
        # 자유문에는 성명·연락처가 섞일 수 있다. 저장 전에 막는다. 사용자 입력 오류이므로
        # 500 이 아니라 422 로 돌려주되 무엇을 발견했는지는 알리지 않는다.
        try:
            assert_no_personal_data_in_text("detail", detail)
        except ModelOutputPrivacyError as error:
            raise ValidationError(PERSONAL_DATA_MESSAGE, code=PERSONAL_DATA_CODE) from error

    if target is FeedbackTarget.POSITION_ANALYSIS:
        if repository.find_position_card(session, brokerage_id, target_id) is None:
            raise NotFoundError("position analysis is not found")
        position_analysis_id, candidate_id = target_id, None
    else:
        if repository.find_candidate_judgment(session, brokerage_id, target_id) is None:
            raise NotFoundError("match candidate evaluation is not found")
        position_analysis_id, candidate_id = None, target_id

    feedback = AiDecisionFeedback(
        brokerage_id=brokerage_id,
        position_analysis_id=position_analysis_id,
        match_candidate_evaluation_id=candidate_id,
        feedback_type=feedback_type.value,
        reason=reason.value,
        field_name=field_name,
        corrected_value=corrected_value,
        detail=detail,
        # 정정 상담 로그 생성은 이번 범위가 아니다.
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


__all__ = [
    "DETAIL_MAX_LENGTH",
    "PERSONAL_DATA_CODE",
    "PERSONAL_DATA_MESSAGE",
    "FeedbackReason",
    "FeedbackTarget",
    "FeedbackType",
    "record_feedback",
]
