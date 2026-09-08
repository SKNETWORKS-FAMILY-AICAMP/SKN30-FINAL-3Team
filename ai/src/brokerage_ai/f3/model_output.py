"""모델이 실제로 판단하는 값만 담는 내부 구조화 출력 schema.

모델 출력에서 서버 소유 필드를 **아예 뺀다.** 받아 놓고 사후에 검증하는 구조는 모델이
`anchor_id`나 장부 표기 금액을 만들어낼 자리를 남긴다. 여기 없는 값은 만들 수 없다.

이 모듈은 AI 내부 구현이며 Backend 공개 계약이 아니다.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

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
    """금액 축이 하나인 거래(매매·전세·예산)에 대한 모델의 판단.

    장부 표기 금액은 여기에 없다. `price_kind` 도 없다. 어느 유형인지는 담기는 자리가 정한다.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    estimated_amount: int | None = Field(default=None, ge=0)
    basis: tuple[Evidence, ...] = ()


class ModelMonthlyRentOpinion(BaseModel):
    """월세만 보증금과 차임 두 축을 갖는다.

    `estimated_monthly_amount` 를 이 타입에만 두어 "월세가 아닌 유형에는 월 금액을 쓰지
    않는다"를 규칙이 아니라 **타입**으로 만든다.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    estimated_amount: int | None = Field(default=None, ge=0)
    estimated_monthly_amount: int | None = Field(default=None, ge=0)
    basis: tuple[Evidence, ...] = ()


class ModelPriceOpinions(BaseModel):
    """거래 유형별 판단. **유형마다 자리가 하나뿐이다.**

    이전에는 `price_kind` 를 든 항목의 배열이었고 "같은 유형을 두 번 담지 않는다"를
    `model_validator` 와 프롬프트 문장으로 막았다. JSON schema 에 그 규칙을 적을 자리가 없어
    모델은 스키마만 봐서는 그 존재를 알 수 없었고, 실제로 로컬 모델이 `["SALE", "SALE"]` 을
    결정론적으로 반복해 되먹임 3회로도 못 고치고 실행이 종료됐다.

    자리를 유형별로 나누면 중복이 **문법적으로 표현 불가능**해진다. 구조화 출력이 강제하므로
    모델이 규칙을 기억할 필요가 없다.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    sale: ModelPriceOpinion | None = None
    jeonse: ModelPriceOpinion | None = None
    monthly_rent: ModelMonthlyRentOpinion | None = None
    budget: ModelPriceOpinion | None = None


# 공개 계약의 `PriceKind` 와 위 자리를 잇는 유일한 표.
_PRICE_SLOTS: dict[PriceKind, str] = {
    PriceKind.SALE: "sale",
    PriceKind.JEONSE: "jeonse",
    PriceKind.MONTHLY_RENT: "monthly_rent",
    PriceKind.BUDGET: "budget",
}


class PositionCardModelOutput(BaseModel):
    """모델이 채우는 포지션 판단.

    `negotiation_side`, `anchor_id`, source identity, `contract_version`, 장부 표기 금액,
    cache key, `generated_at`, `run_id`, `brokerage_id`, `requested_by`, lease 정보는
    이 schema 에 존재하지 않는다.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    intent: IntentAssessment
    urgency: UrgencyAssessment
    price: ModelPriceOpinions = ModelPriceOpinions()
    timing: TimingAssessment
    flexible: tuple[PositionCondition, ...] = ()
    inflexible: tuple[PositionCondition, ...] = ()
    contactability: ContactabilityAssessment


def assemble_analysis(
    request: PositionCardGenerationRequest, output: PositionCardModelOutput
) -> PositionCardAnalysis:
    """모델 판단과 장부 표기 금액을 합쳐 공개 결과를 만든다.

    표기 금액은 요청의 anchor context 에서 결정적으로 복사한다. 장부가 열어 두지 않은 거래
    유형은 모델이 말해도 카드에 싣지 않는다. 열려 있는데 모델이 언급하지 않은 유형은 표기
    금액만 담은 항목으로 남겨 카드에서 통째로 사라지지 않게 한다.
    """
    enabled = enabled_price_kinds(request.anchor)

    prices: list[PriceAssessment] = []
    for kind in PriceKind:
        if kind not in enabled:
            continue
        stated_amount, stated_monthly = stated_price_for(request.anchor, kind)
        # 장부가 열지 않은 유형은 모델이 채웠어도 위 `continue` 에서 버려진다.
        opinion = getattr(output.price, _PRICE_SLOTS[kind])
        prices.append(
            PriceAssessment(
                price_kind=kind,
                stated_amount=stated_amount,
                stated_monthly_amount=stated_monthly,
                estimated_amount=opinion.estimated_amount if opinion else None,
                estimated_monthly_amount=(
                    opinion.estimated_monthly_amount
                    if isinstance(opinion, ModelMonthlyRentOpinion)
                    else None
                ),
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
