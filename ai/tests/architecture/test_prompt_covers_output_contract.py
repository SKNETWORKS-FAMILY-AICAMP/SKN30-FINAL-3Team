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
    Evidence,
    EvidenceKind,
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
    ("PositionCardModelOutput", "each_price_kind_appears_once"): (
        "price 에 같은 price_kind 를 두 번 담지 않는다"
    ),
    ("PositionCardAnalysis", "each_price_kind_appears_once"): (
        "price 에 같은 price_kind 를 두 번 담지 않는다"
    ),
    ("TimingAssessment", "a_deadline_requires_at_least_one_constraint"): (
        "hard_deadline 은 반드시 null 이다"
    ),
    ("Evidence", "evidence_must_carry_what_its_kind_requires"): (
        "kind=QUOTE 이면 interaction_id 와 quote_text 를 채우고"
    ),
    ("PriceAssessment", "monthly_amounts_belong_to_monthly_rent_only"): (
        "estimated_monthly_amount 는 price_kind 가 MONTHLY_RENT 일 때만 쓴다"
    ),
    ("PriceAssessment", "an_estimate_that_differs_requires_a_basis"): (
        "가격 추정은 장부 표기 금액과 다를 때만 낸다"
    ),
}

JUDGMENT_COVERAGE = {
    ("BrokerageJudgmentModelOutput", "each_candidate_appears_once"): (
        "같은 card_id 를 두 번 판정하지 않는다"
    ),
    ("CandidateJudgment", "a_rejection_requires_its_reason"): (
        "REJECTED 에는 rejection_reason 을 반드시 쓴다. REJECTED 가 아니면 쓰지 않는다"
    ),
    ("Evidence", "evidence_must_carry_what_its_kind_requires"): (
        "kind=QUOTE 이면 interaction_id 와 quote_text 를 채우고"
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
    """루트에서 재귀적으로 도달 가능한 모든 `model_validator`."""
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
    inferred = (Evidence(kind=EvidenceKind.INFERENCE, note="장부 값으로 판단"),)
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


def test_every_position_card_validator_is_carried_by_the_prompt() -> None:
    reachable = model_validators(PositionCardModelOutput, PositionCardAnalysis)

    assert reachable == set(POSITION_CARD_COVERAGE), (
        "모델 출력 계약의 교차 필드 규칙이 바뀌었다. 새 규칙은 프롬프트가 전달할 문장을 정해 "
        "위 표에 등록하고, 없어진 규칙은 표에서 지운다."
    )

    prompt = position_card_prompt()
    for (schema, validator), sentence in POSITION_CARD_COVERAGE.items():
        assert sentence in prompt, f"{schema}.{validator} 를 전달하는 문장이 프롬프트에 없다"


def test_every_judgment_validator_is_carried_by_the_prompt() -> None:
    reachable = model_validators(BrokerageJudgmentModelOutput, CandidateJudgment)

    assert reachable == set(JUDGMENT_COVERAGE)

    prompt = judgment_prompt()
    for (schema, validator), sentence in JUDGMENT_COVERAGE.items():
        assert sentence in prompt, f"{schema}.{validator} 를 전달하는 문장이 프롬프트에 없다"
