"""요청과 중개 판정 결과 사이의 순수 검증.

Pydantic 이 잡는 것은 결과 하나의 구조다. 여기서 잡는 것은 그 결과가 **이 요청**에 대한
것이 맞는지다. 후보가 빠졌거나 없던 후보가 늘었거나 순위가 어긋난 결과는 구조가 멀쩡해도
저장하면 안 된다.

이 모듈은 Session, Repository, DB 를 알지 않는다. Backend 는 여기를 통과한 결과에 대해
DB 현재 상태, lease, tenant 와 후보 집합을 다시 검증한다.
"""

from __future__ import annotations

from brokerage_ai.core.errors import OutputContractError
from brokerage_ai.f3.contracts import EvidenceKind
from brokerage_ai.f3.judgment_contracts import (
    BrokerageJudgmentRequest,
    BrokerageJudgmentResult,
    CandidateJudgment,
    JudgmentCard,
    MatchGrade,
)


class BrokerageJudgmentContractError(OutputContractError):
    """결과가 요청과 맞지 않는다. 이 결과로 판정을 저장하면 안 된다."""


def _check_target(request: BrokerageJudgmentRequest, result: BrokerageJudgmentResult) -> None:
    target = result.target
    if target.anchor_card_id != request.anchor.card_id:
        raise BrokerageJudgmentContractError("result targets a different anchor card")
    if target.anchor_side is not request.anchor.negotiation_side:
        raise BrokerageJudgmentContractError("result targets a different negotiation side")
    if set(target.candidate_card_ids) != {card.card_id for card in request.candidates}:
        raise BrokerageJudgmentContractError("result targets a different candidate set")


def _check_candidate_set(
    request: BrokerageJudgmentRequest, result: BrokerageJudgmentResult
) -> None:
    """요청 후보 집합과 결과 후보 집합이 **정확히** 같아야 한다.

    빠지면 조용히 사라진 후보가 생기고, 늘면 존재하지 않는 카드를 가리키는 판정이 저장된다.
    중복은 같은 후보에 두 등급을 남긴다.
    """
    judged = [candidate.card_id for candidate in result.candidates]
    if len(set(judged)) != len(judged):
        raise BrokerageJudgmentContractError("result repeats a candidate card")

    requested = {card.card_id for card in request.candidates}
    missing = requested - set(judged)
    if missing:
        raise BrokerageJudgmentContractError(
            f"result is missing {len(missing)} requested candidates"
        )
    unknown = set(judged) - requested
    if unknown:
        raise BrokerageJudgmentContractError("result judges a candidate that was not requested")


def _check_ranks(result: BrokerageJudgmentResult) -> None:
    """순위는 양수이고 중복되지 않으며 1부터 연속이어야 한다.

    구멍이 있거나 1에서 시작하지 않으면 "몇 번째로 보여줄 것인가"라는 질문에 답할 수 없다.
    """
    ranks = sorted(candidate.rank for candidate in result.candidates)
    if ranks != list(range(1, len(ranks) + 1)):
        raise BrokerageJudgmentContractError("candidate ranks must be 1..N without gaps")


def _check_evidence(
    request: BrokerageJudgmentRequest, candidate: CandidateJudgment, card: JudgmentCard
) -> None:
    """근거가 실제로 존재하는 카드의 것인지 확인한다.

    판정 단계에는 상담 원문이 없다. 그러므로 인용은 **이미 카드가 갖고 있던 인용**만
    허용한다. 카드에 없는 `(interaction_id, quote_text)` 쌍은 모델이 만들어 낸 것이다.
    """
    anchor_side = request.anchor.negotiation_side
    allowed = {anchor_side: request.anchor.quoted(), card.negotiation_side: card.quoted()}

    for item in candidate.evidence:
        if item.evidence_side not in allowed:
            raise BrokerageJudgmentContractError(
                "evidence claims a side that is not part of this judgment"
            )
        if item.source.kind is not EvidenceKind.QUOTE:
            continue
        # QUOTE 의 두 값은 Pydantic 이 이미 강제했다. 여기서는 출처 범위만 본다.
        assert item.source.interaction_id is not None
        assert item.source.quote_text is not None
        pair = (item.source.interaction_id, item.source.quote_text)
        if pair not in allowed[item.evidence_side]:
            raise BrokerageJudgmentContractError(
                "evidence quotes something the position card does not contain"
            )


def validate_judgment_result(
    request: BrokerageJudgmentRequest, result: BrokerageJudgmentResult
) -> None:
    """결과가 이 요청에 대한 것인지 확인한다. 어긋나면 첫 번째 문제에서 멈춘다."""
    if result.contract_version != request.contract_version:
        raise BrokerageJudgmentContractError("result contract version does not match the request")

    _check_target(request, result)
    _check_candidate_set(request, result)
    _check_ranks(result)

    cards = {card.card_id: card for card in request.candidates}
    for candidate in result.candidates:
        card = cards[candidate.card_id]
        _check_evidence(request, candidate, card)
        # 기각 사유와 근거 최소 1건은 Pydantic 이 이미 강제한다. 여기서는 등급이 실제 어휘에
        # 있는지만 다시 확인해 저장 직전에 새 값이 끼어들지 않게 한다.
        if candidate.grade not in MatchGrade:  # pragma: no cover - 방어
            raise BrokerageJudgmentContractError("unknown match grade")
