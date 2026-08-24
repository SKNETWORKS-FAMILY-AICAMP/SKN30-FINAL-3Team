"""AI 판정에 대한 사용자 피드백 (F3-TR-03, F3-CR-17).

대리가 엉뚱한 포지션을 두 번 세우면 아무도 보지 않는다. 「관심없음」과 정정을 사유와 함께
받아 어느 판정이 자주 틀리는지 볼 수 있게 한다.

저장은 기존 `ai_decision_feedback`(migration 007)을 그대로 쓴다. 새 테이블을 만들지 않는다.

`created_by` 와 `brokerage_id` 는 **세션에서만** 도출한다. 요청 본문으로 받으면 남의 사무소
결과에 남의 이름으로 피드백을 남길 수 있다. 정정 상담 로그 생성(F3-TR-02)은 이번 범위가
아니라 `correction_interaction_id` 는 항상 비어 있다.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from enum import StrEnum
from typing import NoReturn

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

# 정정값 상한. 정정은 카드 항목 하나를 고치는 일이라 작은 구조면 충분하다. 상한이 없으면
# 임의 크기 JSON 이 판정 기록에 그대로 들어간다.
CORRECTED_VALUE_MAX_BYTES = 4096
CORRECTED_VALUE_MAX_DEPTH = 4
CORRECTED_VALUE_MAX_NODES = 50

# 정정값이 담을 수 있는 JSON leaf 타입. bool 을 int 보다 먼저 본다. `isinstance(True, int)`
# 가 참이라 순서를 뒤집으면 참·거짓이 숫자로 분류된다.
_ALLOWED_LEAF_TYPES = (bool, int, float, str)


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


# 정정 가능한 필드. **공개 계약에 실제로 노출되는 항목**에서 뽑는다. 임의의 DB 컬럼 이름을
# 받으면 내부 스키마가 정정 대상처럼 보이고, 나중에 정정값을 반영할 때 그대로 쓸 수 없다.
#
# 포지션 카드는 F3-PC-01 의 카드 항목이고 (결과 조회의 `anchor_card.analysis` 키),
# 중개 판정은 후보 응답이 싣는 항목이다.
CORRECTABLE_FIELDS: dict[FeedbackTarget, frozenset[str]] = {
    FeedbackTarget.POSITION_ANALYSIS: frozenset(
        {"intent", "price", "urgency", "timing", "flexible", "inflexible", "contactability"}
    ),
    FeedbackTarget.MATCH_CANDIDATE: frozenset(
        {
            "match_grade",
            "evaluation_basis",
            "primary_obstacle",
            "possible_concession",
            "recommended_action",
            "exclusion_reason",
        }
    ),
}


def _reject(message: str, code: str = "VALIDATION_FAILED") -> NoReturn:
    raise ValidationError(message, code=code)


def _walk_corrected_value(
    value: object, path: str, depth: int, budget: list[int]
) -> Iterator[tuple[str, str]]:
    """정정값을 훑으며 문자열 leaf 를 `(경로, 값)` 으로 낸다.

    같은 순회에서 깊이·항목 수·허용 타입을 함께 본다. 두 번 걷지 않는다.
    """
    if depth > CORRECTED_VALUE_MAX_DEPTH:
        _reject("corrected_value is nested too deeply")
    budget[0] -= 1
    if budget[0] < 0:
        _reject("corrected_value has too many entries")

    if value is None or isinstance(value, bool):
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or not key.strip():
                _reject("corrected_value keys must be non-blank strings")
            yield from _walk_corrected_value(item, f"{path}.{key}", depth + 1, budget)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_corrected_value(item, f"{path}.{index}", depth + 1, budget)
        return
    if isinstance(value, str):
        yield path, value
        return
    if not isinstance(value, _ALLOWED_LEAF_TYPES):
        _reject("corrected_value may only contain JSON values")


def validate_corrected_value(value: dict[str, object]) -> None:
    """정정값의 크기·구조·개인정보를 확인한다.

    문자열 leaf 는 **전부** 개인정보 패턴 검사를 지난다. 최상위만 보면 중첩 객체나 배열
    안에 연락처를 숨길 수 있다.

    이름은 패턴으로 잡히지 않는다. 마스킹 대상 식별값 목록은 앵커별로 다시 조립해야 얻는데,
    사용자가 직접 쓴 짧은 정정값에 그 비용을 들이지 않는다. 연락처·생년월일·주민등록번호
    형태만 막고 그 한계를 개인정보 정본에 적어 둔다.
    """
    try:
        serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as error:
        raise ValidationError("corrected_value must be JSON serializable") from error
    if len(serialized.encode("utf-8")) > CORRECTED_VALUE_MAX_BYTES:
        _reject("corrected_value is too large")

    budget = [CORRECTED_VALUE_MAX_NODES]
    for path, text in _walk_corrected_value(value, "corrected_value", 0, budget):
        _assert_no_personal_data(path, text)


def _assert_no_personal_data(field: str, text: str) -> None:
    """개인정보가 있으면 422 로 바꾼다. 발견한 값 자체는 응답에 넣지 않는다."""
    try:
        assert_no_personal_data_in_text(field, text)
    except ModelOutputPrivacyError as error:
        raise ValidationError(PERSONAL_DATA_MESSAGE, code=PERSONAL_DATA_CODE) from error


def _validate_correction_shape(
    target: FeedbackTarget,
    feedback_type: FeedbackType,
    field_name: str | None,
    corrected_value: dict[str, object] | None,
) -> None:
    """정정과 관심없음은 실을 수 있는 것이 다르다.

    정정인데 무엇을 어떻게 고칠지가 없으면 다음 판정의 입력이 되지 못한다 (F3-TR-02).
    관심없음은 사유만 남기는 피드백이라 정정 대상과 정정값을 받지 않는다.
    """
    if feedback_type is FeedbackType.CORRECTION:
        if field_name is None:
            _reject("a CORRECTION requires field_name")
        if corrected_value is None:
            _reject("a CORRECTION requires corrected_value")
    else:
        if field_name is not None:
            _reject("only a CORRECTION may carry field_name")
        if corrected_value is not None:
            _reject("only a CORRECTION may carry corrected_value")

    if field_name is not None:
        if not field_name.strip():
            _reject("field_name must not be blank")
        if field_name not in CORRECTABLE_FIELDS[target]:
            # 내부 컬럼 이름을 정정 대상으로 받지 않는다.
            _reject("field_name is not correctable for this target")


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
    _validate_correction_shape(target, feedback_type, field_name, corrected_value)
    if detail is not None:
        # 자유문에는 성명·연락처가 섞일 수 있다. 저장 전에 막는다. 사용자 입력 오류이므로
        # 500 이 아니라 422 로 돌려주되 무엇을 발견했는지는 알리지 않는다.
        _assert_no_personal_data("detail", detail)
    if corrected_value is not None:
        validate_corrected_value(corrected_value)

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
    "CORRECTABLE_FIELDS",
    "CORRECTED_VALUE_MAX_BYTES",
    "CORRECTED_VALUE_MAX_DEPTH",
    "CORRECTED_VALUE_MAX_NODES",
    "DETAIL_MAX_LENGTH",
    "PERSONAL_DATA_CODE",
    "PERSONAL_DATA_MESSAGE",
    "FeedbackReason",
    "FeedbackTarget",
    "FeedbackType",
    "record_feedback",
    "validate_corrected_value",
]
