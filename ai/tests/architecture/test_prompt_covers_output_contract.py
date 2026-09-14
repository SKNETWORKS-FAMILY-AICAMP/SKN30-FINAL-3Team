"""모델 출력 계약의 교차 필드 규칙이 프롬프트로 전달되는지 고정한다.

구조화 출력에서 우리가 강제하는 규칙은 두 종류다.

- **JSON schema 가 표현하는 것.** 타입, 열거값, `min_length`. 모델은 스키마만 보고도 안다.
- **`model_validator` 가 표현하는 것.** "마감일을 세우려면 근거 제약이 하나 이상 있어야 한다"
  같은 교차 필드 규칙. 스키마 문법에 자리가 없어 **모델이 그 존재를 알 방법이 없다.**

두 번째 종류는 프롬프트가 유일한 전달 경로다. 그런데 그 책임이 어디에도 기록되지 않아, 계약에
규칙을 더하면서 프롬프트를 안 고치는 일이 반복됐다. PR #38 과 #42 가 모두 운영에서 터진 뒤에
규칙 문장을 한 줄씩 메운 사고였다.

이 테스트는 그 책임을 표로 만들고 코드가 표를 벗어나지 못하게 한다. 깨지는 경우는 둘이다.

1. 새 `model_validator` 를 계약에 추가하고 아래 표에 등록하지 않았다 → 집합 비교가 깨진다.
   등록하려면 그 규칙을 프롬프트의 어느 문장이 전달하는지 정해야 한다.
2. 표에 적힌 문장이 프롬프트에서 사라지거나 바뀌었다 → 포함 검사가 깨진다.

`field_validator` 는 넣지 않는다. `min_length`·`max_length` 는 JSON schema 가 이미 표현하고 남는
것은 공백 문자열 정규화뿐이라, 넣으면 표가 잡음으로 차서 진짜 교차 필드 규칙이 묻힌다.

프롬프트 본문은 모듈 상수를 직접 가져오지 않고 **실제로 전송하는 메시지**에서 찾는다. 규칙이
상수에만 있고 메시지 조립에서 빠지면 모델은 여전히 못 본다.
"""

from __future__ import annotations

import typing
from datetime import UTC, datetime

from pydantic import BaseModel

from brokerage_ai.f3.contracts import (
    ContactabilityAssessment,
    ContactabilityStatus,
    DateSignals,
    InferenceEvidence,
    InputPrivacyMode,
    IntentAssessment,
    NegotiationIntent,
    NegotiationSide,
    PositionCardAnalysis,
    PositionCardGenerationRequest,
    RequirementAnchorContext,
    SourceIdentity,
    TimingAssessment,
    Urgency,
    UrgencyAssessment,
)
from brokerage_ai.f3.judgment_contracts import (
    BrokerageJudgmentRequest,
    CandidateJudgment,
    JudgmentCard,
)
from brokerage_ai.f3.judgment_model_output import BrokerageJudgmentModelOutput
from brokerage_ai.f3.judgment_prompts import build_brokerage_judgment_messages
from brokerage_ai.f3.model_output import PositionCardModelOutput
from brokerage_ai.f3.prompts import build_position_card_messages

# (schema 이름, validator 이름) → 그 규칙을 전달하는 프롬프트 문장.
#
# 루트는 모델이 직접 채우는 schema 와, 그 값으로 조립되는 결과 둘 다다. `PriceAssessment` 의
# 두 규칙은 `assemble_analysis()` 가 장부 표기 금액과 합칠 때에야 걸리므로 모델 출력 schema 만
# 훑으면 보이지 않는다.
POSITION_CARD_COVERAGE = {
    # `PositionCardModelOutput` 쪽 같은 이름의 validator 는 없앴다. price 를 거래 유형별 자리를
    # 가진 객체로 바꿔 중복이 문법적으로 불가능해졌기 때문이다. 아래 공개 계약 validator 는
    # 남아 있지만 모델 출력으로는 위반할 수 없고, 프롬프트는 그 자리 구조를 알려 준다.
    ("PositionCardAnalysis", "each_price_kind_appears_once"): (
        "price 는 거래 유형마다 자리가 하나뿐인 객체다"
    ),
    ("TimingAssessment", "a_deadline_requires_at_least_one_constraint"): (
        "hard_deadline 은 반드시 null 이다"
    ),
    ("PriceAssessment", "monthly_amounts_belong_to_monthly_rent_only"): (
        "보증금과 월 금액을 함께 쓰는 자리는 monthly_rent 뿐이다"
    ),
    ("PriceAssessment", "an_estimate_that_differs_requires_a_basis"): (
        "가격 추정은 장부 표기 금액과 다를 때만 낸다"
    ),
}

# 모델에게 요구하는 것이 없어 프롬프트로 전달할 문장도 없는 validator.
#
# ADR-0003 의 취지는 "모델이 지켜야 할 규칙이 프롬프트로 전달되는가"다. 저장된 예전 형식을
# 되살리는 정규화는 모델 출력에 대한 요구가 아니므로 전달할 것이 없다. 다만 그 판단을 사람이
# 한 번 내리고 **이름으로 남긴다.** 새 validator 가 생기면 이 목록에도 표에도 없어 아래
# 검사가 깨지고, 그때 어느 쪽인지 정해야 한다.
READ_COMPATIBILITY_ONLY = {
    # 예전 `Evidence` 는 네 필드를 모두 담고 해당 없는 자리를 null 로 채워 저장했다. 그 카드를
    # 판정 입력으로 되살리려면 null 자리 표시를 버려야 한다. 지금 모델 출력에는 그 자리가 아예
    # 없으므로 모델이 알아야 할 규칙이 아니다.
    ("QuoteEvidence", "drop_legacy_null_placeholders"),
    ("InferenceEvidence", "drop_legacy_null_placeholders"),
}

JUDGMENT_COVERAGE = {
    ("BrokerageJudgmentModelOutput", "each_candidate_appears_once"): (
        "같은 card_id 를 두 번 판정하지 않는다"
    ),
    ("CandidateJudgment", "a_rejection_requires_its_reason"): (
        "REJECTED 에는 rejection_reason 을 반드시 쓴다. REJECTED 가 아니면 쓰지 않는다"
    ),
}


def _nested_models(annotation: object) -> typing.Iterator[type[BaseModel]]:
    """타입 표기 안에 있는 Pydantic 모델. `tuple[X, ...]`, `X | None` 을 풀어 준다."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        yield annotation
        return
    for argument in typing.get_args(annotation):
        yield from _nested_models(argument)


def model_validators(*roots: type[BaseModel]) -> set[tuple[str, str]]:
    """루트에서 재귀적으로 도달 가능한 모든 `model_validator`.

    `mode` 로 거르지 않는다. ADR-0003 이 고정한 것은 "도달 가능한 **모든** validator 가 표에
    등록되어 있어야 한다"이고, `mode` 같은 기계적 성질로 예외를 만들면 앞으로 모델이 알아야
    할 교차 필드 규칙을 `before` 로 구현했을 때 이 검사가 조용히 놓친다. 전달할 문장이 없는
    validator 는 아래 `READ_COMPATIBILITY_ONLY` 에 이름을 적어 이유를 남긴다.
    """
    found: set[tuple[str, str]] = set()
    seen: set[type[BaseModel]] = set()

    def walk(model: type[BaseModel]) -> None:
        if model in seen:
            return
        seen.add(model)
        for name in model.__pydantic_decorators__.model_validators:
            found.add((model.__name__, name))
        for field in model.model_fields.values():
            for nested in _nested_models(field.annotation):
                walk(nested)

    for root in roots:
        walk(root)
    return found


def position_card_prompt() -> str:
    """실제로 전송하는 system 메시지. 규칙이 상수에만 있고 여기 없으면 모델은 못 본다."""
    request = PositionCardGenerationRequest(
        input_privacy_mode=InputPrivacyMode.SYNTHETIC_PROTOTYPE,
        negotiation_side=NegotiationSide.REQUIREMENT,
        anchor_id=1,
        target_label="구입장 #1",
        source=SourceIdentity(data_version=1, interaction_count=0),
        anchor=RequirementAnchorContext(requirement_id=1, demand_type="매수", status="ACTIVE"),
        date_signals=DateSignals(as_of=datetime(2026, 8, 27, tzinfo=UTC)),
        consultation_logs=(),
    )
    return build_position_card_messages(request)[0].content


def judgment_card(card_id: int, side: NegotiationSide) -> JudgmentCard:
    inferred = (InferenceEvidence(note="장부 값으로 판단"),)
    return JudgmentCard(
        card_id=card_id,
        negotiation_side=side,
        target_label=f"카드 #{card_id}",
        analysis=PositionCardAnalysis(
            intent=IntentAssessment(value=NegotiationIntent.UNKNOWN, evidence=inferred),
            urgency=UrgencyAssessment(value=Urgency.UNKNOWN, evidence=inferred),
            timing=TimingAssessment(),
            contactability=ContactabilityAssessment(
                status=ContactabilityStatus.UNKNOWN, evidence=inferred
            ),
        ),
    )


def judgment_prompt() -> str:
    request = BrokerageJudgmentRequest(
        input_privacy_mode=InputPrivacyMode.SYNTHETIC_PROTOTYPE,
        anchor=judgment_card(1, NegotiationSide.LISTING),
        candidates=(judgment_card(2, NegotiationSide.REQUIREMENT),),
    )
    return build_brokerage_judgment_messages(request)[0].content


def test_read_compatibility_exceptions_still_exist() -> None:
    """예외 목록이 낡지 않게 한다.

    validator 를 지우거나 이름을 바꾸고 목록을 그대로 두면, 그 자리가 조용히 남아 나중에
    같은 이름으로 만들어진 **다른** validator 를 면제해 준다.
    """
    reachable = model_validators(
        PositionCardModelOutput,
        PositionCardAnalysis,
        BrokerageJudgmentModelOutput,
        CandidateJudgment,
    )
    stale = READ_COMPATIBILITY_ONLY - reachable
    assert stale == set(), f"더 이상 존재하지 않는 validator 가 예외 목록에 남아 있다: {stale}"


def test_every_position_card_validator_is_carried_by_the_prompt() -> None:
    reachable = model_validators(PositionCardModelOutput, PositionCardAnalysis)

    assert reachable - READ_COMPATIBILITY_ONLY == set(POSITION_CARD_COVERAGE), (
        "모델 출력 계약의 교차 필드 규칙이 바뀌었다. 새 규칙은 프롬프트가 전달할 문장을 정해 "
        "위 표에 등록하고, 없어진 규칙은 표에서 지운다."
    )

    prompt = position_card_prompt()
    for (schema, validator), sentence in POSITION_CARD_COVERAGE.items():
        assert sentence in prompt, f"{schema}.{validator} 를 전달하는 문장이 프롬프트에 없다"


def test_every_judgment_validator_is_carried_by_the_prompt() -> None:
    reachable = model_validators(BrokerageJudgmentModelOutput, CandidateJudgment)

    assert reachable - READ_COMPATIBILITY_ONLY == set(JUDGMENT_COVERAGE)

    prompt = judgment_prompt()
    for (schema, validator), sentence in JUDGMENT_COVERAGE.items():
        assert sentence in prompt, f"{schema}.{validator} 를 전달하는 문장이 프롬프트에 없다"
