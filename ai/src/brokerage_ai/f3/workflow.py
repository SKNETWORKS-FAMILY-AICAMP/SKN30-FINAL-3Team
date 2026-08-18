"""F3 워크플로 facade — Backend 가 부르는 유일한 진입점.

여기서 하는 것은 모델 호출과 프롬프트 조립뿐이다. 후보 추출, 날짜 산수, 등급 산출, 카드 캐시와
영속화는 전부 Backend 에 있다. 이 모듈은 DB 를 모르고 Backend 는 프롬프트를 모른다.

호출 횟수 계약 (F3 수용 기준 5)
  포지션 카드  대상 1건당 1회
  중개 판정    앵커 1 + 후보 N 을 통틀어 1회
"""

from __future__ import annotations

import json

from brokerage_ai.core.types import (
    ChatMessage,
    MessageRole,
    ProviderDiagnostics,
    StructuredGenerationRequest,
)
from brokerage_ai.f3.contracts import (
    AgentCallTrace,
    CandidateCardInput,
    MatchJudgementResult,
    MatchVerdictList,
    PositionCard,
    PositionCardInput,
    PositionCardResult,
)
from brokerage_ai.f3.prompts import PROMPT_VERSION, SYSTEM_BROKER, delegate_system_prompt
from brokerage_ai.f3.routes import BROKER_ROUTE, DELEGATE_ROUTE, TEMPERATURE
from brokerage_ai.providers.registry import ProviderRegistry


def _dump(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=1)


def _trace(agent: str, diagnostics: ProviderDiagnostics) -> AgentCallTrace:
    usage = diagnostics.usage
    return AgentCallTrace(
        agent=agent,
        prompt_version=PROMPT_VERSION,
        provider=diagnostics.provider.value,
        model=diagnostics.model,
        latency_ms=diagnostics.latency_ms,
        input_tokens=usage.input_tokens if usage is not None else None,
        output_tokens=usage.output_tokens if usage is not None else None,
        request_id=diagnostics.request_id,
    )


def delegate_user_payload(card_input: PositionCardInput) -> dict[str, object]:
    """대리에게 실제로 보내는 입력. 반대편 항목이 여기 들어올 자리가 없다."""
    return {
        "side": card_input.side,
        "label": card_input.label,
        "pyeong": card_input.pyeong,
        "deal_type_book": card_input.deal_type_book,
        "book_amount": card_input.book_amount,
        "note": card_input.note,
        "logs": list(card_input.logs),
    }


def slim_card(card: PositionCard, *, full: bool = False) -> dict[str, object]:
    """판정 입력용 축약. 근거 원문은 화면용이므로 후보 축약본에서 뺀다."""
    payload: dict[str, object] = {
        "intent": card.intent.value,
        "price_est": card.price.estimated,
        "concession": card.price.concession or 0,
        "urgency": card.urgency.value,
        "flexible": card.flexible[:2],
        "inflexible": card.inflexible[:2],
        "contact": card.contactability.status,
        "contact_route": card.contactability.route,
        "deal_type_now": card.deal_type_now.value,
    }
    if full:
        payload["intent_evidence"] = card.intent.evidence
        payload["price_basis"] = card.price.basis
        payload["speakers"] = [speaker.key for speaker in card.speakers]
    return payload


async def build_position_card(
    registry: ProviderRegistry,
    card_input: PositionCardInput,
) -> PositionCardResult:
    """대리 1회 호출. 매물 대리와 손님 대리는 입력 자체가 달라 서로의 로그를 볼 수 없다."""
    request = StructuredGenerationRequest(
        route=DELEGATE_ROUTE,
        messages=(
            ChatMessage(role=MessageRole.SYSTEM, content=delegate_system_prompt(card_input.side)),
            ChatMessage(role=MessageRole.USER, content=_dump(delegate_user_payload(card_input))),
        ),
        temperature=TEMPERATURE,
    )
    result = await registry.generate_structured(request, PositionCard)
    agent = "매물대리" if card_input.side == "매물" else "손님대리"
    return PositionCardResult(card=result.output, trace=_trace(agent, result.diagnostics))


async def judge_matches(
    registry: ProviderRegistry,
    *,
    anchor_label: str,
    anchor_card: PositionCard,
    candidates: tuple[CandidateCardInput, ...],
) -> MatchJudgementResult:
    """중개 판정 1회. 후보를 나눠 부르지 않는다 — 상호 비교 근거가 나오려면 한 프롬프트여야 한다."""
    payload = {
        "anchor": {"label": anchor_label, "card": slim_card(anchor_card, full=True)},
        "candidates": [
            {"id": candidate.id, "label": candidate.label, **slim_card(candidate.card)}
            for candidate in candidates
        ],
    }
    request = StructuredGenerationRequest(
        route=BROKER_ROUTE,
        messages=(
            ChatMessage(role=MessageRole.SYSTEM, content=SYSTEM_BROKER),
            ChatMessage(role=MessageRole.USER, content=_dump(payload)),
        ),
        temperature=TEMPERATURE,
    )
    result = await registry.generate_structured(request, MatchVerdictList)
    return MatchJudgementResult(
        verdicts=tuple(result.output.verdicts),
        trace=_trace("중개판정", result.diagnostics),
    )
