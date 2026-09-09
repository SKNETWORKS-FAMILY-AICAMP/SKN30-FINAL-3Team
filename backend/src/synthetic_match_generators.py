"""Deterministic display fixtures for the explicitly requested synthetic match seed.

These generators implement the public AI DTO boundary without a provider, keys, or network.
Their rules demonstrate UI states; they are not model judgments or quality measurements.
"""

from __future__ import annotations

from decimal import Decimal

from brokerage_ai.f3 import (
    BROKERAGE_JUDGMENT_PROMPT_VERSION,
    BROKERAGE_JUDGMENT_WORKFLOW_VERSION,
    POSITION_CARD_PROMPT_VERSION,
    POSITION_CARD_WORKFLOW_VERSION,
    BrokerageJudgmentGeneratorVersions,
    BrokerageJudgmentRequest,
    BrokerageJudgmentResult,
    BrokerageJudgmentTarget,
    CandidateJudgment,
    ContactabilityAssessment,
    ContactabilityStatus,
    InferenceEvidence,
    IntentAssessment,
    JudgmentCard,
    JudgmentEvidence,
    MatchGrade,
    NegotiationIntent,
    NegotiationSide,
    PositionCardAnalysis,
    PositionCardGenerationRequest,
    PositionCardGenerationResult,
    PositionCardGeneratorVersions,
    PositionCardTarget,
    PositionCondition,
    PriceAssessment,
    PriceKind,
    QuoteEvidence,
    TimingAssessment,
    Urgency,
    UrgencyAssessment,
    stated_price_for,
)

SYNTHETIC_MATCH_FIXTURE = {
    "kind": "DETERMINISTIC_MATCH_SEED",
    "version": "v2",
    "model_inference": False,
}
_MOVE_IN_PREFIX = "합성 seed 희망 입주: 기준일로부터 "


class SyntheticPositionCards:
    @property
    def versions(self) -> PositionCardGeneratorVersions:
        return PositionCardGeneratorVersions(
            prompt_version=f"{POSITION_CARD_PROMPT_VERSION}:synthetic-seed-v2",
            workflow_version=f"{POSITION_CARD_WORKFLOW_VERSION}:synthetic-seed-v2",
        )

    async def generate_position_card(
        self, request: PositionCardGenerationRequest
    ) -> PositionCardGenerationResult:
        explanation = InferenceEvidence(
            note=(
                "합성 seed 표시 규칙으로 구성한 카드입니다. "
                "모델이 의사나 연락 가능성을 판정하지 않았습니다"
            )
        )
        evidence = (explanation,)
        if request.consultation_logs:
            log = request.consultation_logs[0]
            evidence += (
                QuoteEvidence(
                    interaction_id=log.interaction_id, quote_text=log.masked_content[:40]
                ),
            )
        prices = []
        for kind in PriceKind:
            amount, monthly = stated_price_for(request.anchor, kind)
            if amount is not None or monthly is not None:
                prices.append(
                    PriceAssessment(
                        price_kind=kind, stated_amount=amount, stated_monthly_amount=monthly
                    )
                )
        move_in_days = request.date_signals.days_until_desired_move_in
        timing = TimingAssessment()
        if move_in_days is not None:
            description = f"{_MOVE_IN_PREFIX}{move_in_days}일"
            timing = TimingAssessment(
                constraints=(
                    PositionCondition(
                        description=description,
                        evidence=(
                            InferenceEvidence(
                                note=(
                                    f"{description}. "
                                    "장부 희망일의 SQL 날짜 신호를 보존한 합성 예시입니다"
                                )
                            ),
                        ),
                    ),
                )
            )
        return PositionCardGenerationResult(
            target=PositionCardTarget.from_request(request),
            analysis=PositionCardAnalysis(
                intent=IntentAssessment(value=NegotiationIntent.UNKNOWN, evidence=evidence),
                urgency=UrgencyAssessment(value=Urgency.UNKNOWN, evidence=(explanation,)),
                price=tuple(prices),
                timing=timing,
                contactability=ContactabilityAssessment(
                    status=ContactabilityStatus.CAUTION,
                    note="합성 표시 데이터입니다. 실제 연락 가능 여부를 의미하지 않습니다",
                    evidence=(explanation,),
                ),
            ),
            prompt_version=self.versions.prompt_version,
            workflow_version=self.versions.workflow_version,
        )


def _budget_ratio(anchor: JudgmentCard, candidate: JudgmentCard) -> Decimal | None:
    listing, requirement = (
        (anchor, candidate)
        if anchor.negotiation_side is NegotiationSide.LISTING
        else (candidate, anchor)
    )
    # Public requirement cards expose BUDGET, not the listing's trade-specific price kind.
    # Multiple trade offers cannot be disambiguated from a JudgmentCard alone; keep those
    # examples WEAK instead of comparing a sale budget to a rent deposit arbitrarily.
    asks = [item.stated_amount for item in listing.analysis.price if item.stated_amount is not None]
    budget = next(
        (
            item.stated_amount
            for item in requirement.analysis.price
            if item.price_kind is PriceKind.BUDGET
        ),
        None,
    )
    if len(asks) != 1 or budget is None or asks[0] <= 0:
        return None
    return Decimal(budget) / Decimal(asks[0])


def _grade_and_reason(ratio: Decimal | None) -> tuple[MatchGrade, str]:
    if ratio is None:
        return MatchGrade.WEAK, "금액이 없거나 복수 거래 금액이 있어 추가 확인하는 약함 예시입니다"
    if ratio >= 1:
        return MatchGrade.STRONG, "표기 예산이 표기 가격 이상인 강함 예시입니다"
    if ratio >= Decimal("0.90"):
        return MatchGrade.WEAK, "표기 예산 부족분이 가격의 10% 이내인 약함 예시입니다"
    return MatchGrade.REJECTED, "표기 예산 부족분이 가격의 10%를 넘는 기각 예시입니다"


def _decision(anchor: JudgmentCard, candidate: JudgmentCard) -> tuple[MatchGrade, str, str]:
    requirement = anchor if anchor.negotiation_side is NegotiationSide.REQUIREMENT else candidate
    for condition in requirement.analysis.timing.constraints:
        if not condition.description.startswith(_MOVE_IN_PREFIX):
            continue
        try:
            days = int(condition.description.removeprefix(_MOVE_IN_PREFIX).removesuffix("일"))
        except ValueError:
            continue
        if days > 365:
            return (
                MatchGrade.REJECTED,
                "희망 입주가 기준일로부터 1년 뒤라 현재 추천에서 제외하는 합성 기각 예시입니다",
                "timing",
            )
    grade, reason = _grade_and_reason(_budget_ratio(anchor, candidate))
    return grade, reason, "price"


class SyntheticBrokerageJudgments:
    @property
    def versions(self) -> BrokerageJudgmentGeneratorVersions:
        return BrokerageJudgmentGeneratorVersions(
            prompt_version=f"{BROKERAGE_JUDGMENT_PROMPT_VERSION}:synthetic-seed-v2",
            workflow_version=f"{BROKERAGE_JUDGMENT_WORKFLOW_VERSION}:synthetic-seed-v2",
        )

    async def judge_candidates(self, request: BrokerageJudgmentRequest) -> BrokerageJudgmentResult:
        ordered = sorted(
            request.candidates,
            key=lambda candidate: (
                {MatchGrade.STRONG: 2, MatchGrade.WEAK: 1, MatchGrade.REJECTED: 0}[
                    _decision(request.anchor, candidate)[0]
                ],
                _budget_ratio(request.anchor, candidate) or Decimal(0),
                -candidate.card_id,
            ),
            reverse=True,
        )
        candidates = []
        for rank, card in enumerate(ordered, start=1):
            grade, reason, field = _decision(request.anchor, card)
            basis = f"[합성 seed 규칙] {reason} 모델 판정·성사 가능성 평가가 아닙니다"
            candidates.append(
                CandidateJudgment(
                    card_id=card.card_id,
                    grade=grade,
                    rank=rank,
                    comparison_basis=basis,
                    primary_obstacle=None
                    if grade is MatchGrade.STRONG
                    else ("희망 입주 시점 차이" if field == "timing" else "표기 금액 추가 확인"),
                    possible_concession=None,
                    rejection_reason=reason if grade is MatchGrade.REJECTED else None,
                    evidence=(
                        JudgmentEvidence(
                            evidence_side=NegotiationSide.REQUIREMENT,
                            field_name=field,
                            source=InferenceEvidence(note=basis),
                        ),
                    ),
                )
            )
        return BrokerageJudgmentResult(
            target=BrokerageJudgmentTarget.from_request(request),
            candidates=tuple(candidates),
            prompt_version=self.versions.prompt_version,
            workflow_version=self.versions.workflow_version,
        )
