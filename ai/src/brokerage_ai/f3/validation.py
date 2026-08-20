"""요청과 결과 사이의 순수 검증.

Pydantic이 잡는 것은 결과 하나의 구조다. 여기서 잡는 것은 그 결과가 **이 요청**에 대한
것이 맞는지다. 없는 상담 로그를 인용하거나, 대상이 바뀌었거나, 장부 표기 금액이 달라진
결과는 구조가 멀쩡해도 저장하면 안 된다.

이 모듈은 Session, Repository, DB를 알지 않는다. Backend는 여기를 통과한 결과에 대해
DB 현재 상태, lease와 source identity를 다시 검증한다.
"""

from __future__ import annotations

from collections.abc import Iterator

from brokerage_ai.core.errors import AiError
from brokerage_ai.f3.contracts import (
    ALLOWED_PRICE_KINDS,
    Evidence,
    EvidenceKind,
    ListingAnchorContext,
    NegotiationSide,
    PositionCardGenerationRequest,
    PositionCardGenerationResult,
    PriceAssessment,
    PriceKind,
)


class PositionCardContractError(AiError):
    """결과가 요청과 맞지 않는다. 이 결과로 카드를 저장하면 안 된다."""


def _evidence(result: PositionCardGenerationResult) -> Iterator[Evidence]:
    analysis = result.analysis
    yield from analysis.intent.evidence
    yield from analysis.urgency.evidence
    yield from analysis.contactability.evidence
    for assessment in analysis.price:
        yield from assessment.basis
    for condition in (*analysis.timing.constraints, *analysis.flexible, *analysis.inflexible):
        yield from condition.evidence


def _stated_amounts(
    request: PositionCardGenerationRequest, kind: PriceKind
) -> tuple[int | None, int | None]:
    """장부가 실제로 갖고 있는 금액. (주 금액, 월 차임) 순서다."""
    anchor = request.anchor
    if isinstance(anchor, ListingAnchorContext):
        if kind is PriceKind.SALE:
            return anchor.sale_price, None
        if kind is PriceKind.JEONSE:
            return anchor.jeonse_deposit_amount, None
        return anchor.monthly_rent_deposit_amount, anchor.monthly_rent_amount
    # 구입장의 표기 가격은 예산 상한이다. 하한은 조건 조회용이라 카드 금액으로 쓰지 않는다.
    return anchor.max_budget_amount, None


def _check_price(
    request: PositionCardGenerationRequest, side: NegotiationSide, assessment: PriceAssessment
) -> None:
    if assessment.price_kind not in ALLOWED_PRICE_KINDS[side]:
        raise PositionCardContractError(
            f"price kind {assessment.price_kind} is not valid for {side}"
        )
    anchor = request.anchor
    if isinstance(anchor, ListingAnchorContext):
        enabled = {
            PriceKind.SALE: anchor.is_sale_available,
            PriceKind.JEONSE: anchor.is_jeonse_available,
            PriceKind.MONTHLY_RENT: anchor.is_monthly_rent_available,
        }
        if not enabled[assessment.price_kind]:
            raise PositionCardContractError(
                f"price kind {assessment.price_kind} is not enabled by the listing"
            )
    stated_amount, stated_monthly = _stated_amounts(request, assessment.price_kind)
    if assessment.stated_amount != stated_amount:
        raise PositionCardContractError(
            f"stated amount for {assessment.price_kind} does not match the ledger"
        )
    if assessment.stated_monthly_amount != stated_monthly:
        raise PositionCardContractError(
            f"stated monthly amount for {assessment.price_kind} does not match the ledger"
        )


def validate_generation_result(
    request: PositionCardGenerationRequest, result: PositionCardGenerationResult
) -> None:
    """결과가 이 요청에 대한 것인지 확인한다. 어긋나면 첫 번째 문제에서 멈춘다."""
    if result.contract_version != request.contract_version:
        raise PositionCardContractError("result contract version does not match the request")

    target = result.target
    if target.negotiation_side is not request.negotiation_side:
        raise PositionCardContractError("result targets a different negotiation side")
    if target.anchor_id != request.anchor_id:
        raise PositionCardContractError("result targets a different anchor")
    if target.source != request.source:
        raise PositionCardContractError("result carries a different source identity")

    hard_deadline = result.analysis.timing.hard_deadline
    if hard_deadline is not None and hard_deadline != request.date_signals.hard_deadline_candidate:
        raise PositionCardContractError("hard deadline does not match the backend date signal")

    contents = request.log_contents()
    for evidence in _evidence(result):
        if evidence.kind is not EvidenceKind.QUOTE:
            continue
        # QUOTE 의 두 값은 Pydantic 이 이미 강제했다. 여기서는 요청 범위만 본다.
        assert evidence.interaction_id is not None
        assert evidence.quote_text is not None
        content = contents.get(evidence.interaction_id)
        if content is None:
            raise PositionCardContractError(
                f"quote references interaction {evidence.interaction_id} outside the request"
            )
        if evidence.quote_text not in content:
            raise PositionCardContractError(
                f"quote is not present in interaction {evidence.interaction_id}"
            )

    for assessment in result.analysis.price:
        _check_price(request, request.negotiation_side, assessment)
