"""모델이 실제로 판단하는 값만 담는 내부 구조화 출력 schema.

모델 출력에서 서버 소유 필드를 **아예 뺀다.** 받아 놓고 사후에 검증하는 구조는 모델이
`anchor_id`나 장부 표기 금액을 만들어낼 자리를 남긴다. 여기 없는 값은 만들 수 없다.

이 모듈은 AI 내부 구현이며 Backend 공개 계약이 아니다.
"""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from brokerage_ai.f3.contracts import (
    ContactabilityAssessment,
    Evidence,
    IntentAssessment,
    PositionCardAnalysis,
    PositionCardGenerationRequest,
    PositionCondition,
    PriceAssessment,
    PriceKind,
    TimingAssessment,
    UrgencyAssessment,
    enabled_price_kinds,
    stated_price_for,
)


class ModelPriceOpinion(BaseModel):
    """가격에 대한 모델의 판단만. 장부 표기 금액은 여기에 없다."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    price_kind: PriceKind
    estimated_amount: int | None = Field(default=None, ge=0)
    estimated_monthly_amount: int | None = Field(default=None, ge=0)
    basis: tuple[Evidence, ...] = ()


class PositionCardModelOutput(BaseModel):
    """모델이 채우는 포지션 판단.

    `negotiation_side`, `anchor_id`, source identity, `contract_version`, 장부 표기 금액,
    cache key, `generated_at`, `run_id`, `brokerage_id`, `requested_by`, lease 정보는
    이 schema 에 존재하지 않는다.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    intent: IntentAssessment
    urgency: UrgencyAssessment
    price: tuple[ModelPriceOpinion, ...] = ()
    timing: TimingAssessment
    flexible: tuple[PositionCondition, ...] = ()
    inflexible: tuple[PositionCondition, ...] = ()
    contactability: ContactabilityAssessment

    @model_validator(mode="after")
    def each_price_kind_appears_once(self) -> Self:
        kinds = [opinion.price_kind for opinion in self.price]
        if len(set(kinds)) != len(kinds):
            raise ValueError("price must not repeat a price_kind")
        return self


def assemble_analysis(
    request: PositionCardGenerationRequest, output: PositionCardModelOutput
) -> PositionCardAnalysis:
    """모델 판단과 장부 표기 금액을 합쳐 공개 결과를 만든다.

    표기 금액은 요청의 anchor context 에서 결정적으로 복사한다. 장부가 열어 두지 않은 거래
    유형은 모델이 말해도 카드에 싣지 않는다. 열려 있는데 모델이 언급하지 않은 유형은 표기
    금액만 담은 항목으로 남겨 카드에서 통째로 사라지지 않게 한다.
    """
    enabled = enabled_price_kinds(request.anchor)
    opinions = {
        opinion.price_kind: opinion for opinion in output.price if opinion.price_kind in enabled
    }

    prices: list[PriceAssessment] = []
    for kind in PriceKind:
        if kind not in enabled:
            continue
        stated_amount, stated_monthly = stated_price_for(request.anchor, kind)
        opinion = opinions.get(kind)
        prices.append(
            PriceAssessment(
                price_kind=kind,
                stated_amount=stated_amount,
                stated_monthly_amount=stated_monthly,
                estimated_amount=opinion.estimated_amount if opinion else None,
                estimated_monthly_amount=opinion.estimated_monthly_amount if opinion else None,
                basis=opinion.basis if opinion else (),
            )
        )

    return PositionCardAnalysis(
        intent=output.intent,
        price=tuple(prices),
        urgency=output.urgency,
        timing=output.timing,
        flexible=output.flexible,
        inflexible=output.inflexible,
        contactability=output.contactability,
    )
