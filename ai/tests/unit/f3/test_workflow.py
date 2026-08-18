import json
from typing import Any

import pytest
from pydantic import BaseModel

from brokerage_ai.core.types import (
    ProviderDiagnostics,
    ProviderKind,
    StructuredGenerationRequest,
    StructuredGenerationResult,
    TokenUsage,
)
from brokerage_ai.f3 import workflow
from brokerage_ai.f3.contracts import (
    CandidateCardInput,
    ContactabilitySection,
    DealTypeSection,
    IntentSection,
    MatchVerdict,
    MatchVerdictList,
    PositionCard,
    PositionCardInput,
    PriceSection,
    SpeakerSection,
    UrgencySection,
)
from brokerage_ai.f3.prompts import PROMPT_VERSION
from brokerage_ai.providers.registry import ProviderRegistry

LISTING_LOG = "[26-06-11 19:42 주]①24.5억은 받아야 한다. 아래로는 생각 없다"
CUSTOMER_LOG = "[26-07-02 11:05 손]①23.5억까지는 올릴 수 있다"


def sample_card(price: float | None = 24.5) -> PositionCard:
    return PositionCard(
        intent=IntentSection(value="있음", evidence=LISTING_LOG, speaker="주①", note=None),
        price=PriceSection(
            estimated=price,
            basis=LISTING_LOG,
            concession=0.5,
            speaker="주①",
            conflict=None,
            stated_by_tenant=None,
        ),
        urgency=UrgencySection(value="보통", evidence=None),
        flexible=["잔금 시점", "명도 시점", "중도금"],
        inflexible=["24억 하한", "12월 명도", "확장 세대"],
        contactability=ContactabilitySection(status="양호", note=None, route="주①"),
        speakers=[SpeakerSection(key="주①", n=4, last="2026-06-11", contact=None, last_stmt=None)],
        deal_type_now=DealTypeSection(value="매매", ref=None),
    )


class FakeProvider:
    """호출 인자를 그대로 붙잡아 두는 대역. 모델 SDK 를 타지 않는다."""

    def __init__(self, outputs: list[BaseModel]) -> None:
        self._outputs = list(outputs)
        self.requests: list[StructuredGenerationRequest] = []
        self.schemas: list[type[BaseModel]] = []

    @property
    def kind(self) -> ProviderKind:
        return ProviderKind.OPENAI

    async def generate_structured(self, request: Any, output_schema: Any) -> Any:
        self.requests.append(request)
        self.schemas.append(output_schema)
        return StructuredGenerationResult(
            output=self._outputs.pop(0),
            diagnostics=ProviderDiagnostics(
                provider=ProviderKind.OPENAI,
                model=request.route.model,
                request_id="resp_test",
                latency_ms=12.5,
                usage=TokenUsage(input_tokens=100, output_tokens=40, total_tokens=140),
            ),
        )


def registry_for(*outputs: BaseModel) -> tuple[ProviderRegistry, FakeProvider]:
    provider = FakeProvider(list(outputs))
    return ProviderRegistry(llm_providers=[provider]), provider


async def test_listing_delegate_input_never_carries_customer_logs() -> None:
    """수용 기준 3 — 대리 격리는 프롬프트가 아니라 입력으로 한다."""
    registry, provider = registry_for(sample_card())

    await workflow.build_position_card(
        registry,
        PositionCardInput(
            side="매물",
            label="203동 1101호",
            pyeong=33.0,
            deal_type_book="매매",
            book_amount=22.3,
            logs=(LISTING_LOG,),
        ),
    )

    prompt = "\n".join(message.content for message in provider.requests[0].messages)
    assert LISTING_LOG in prompt
    assert CUSTOMER_LOG not in prompt
    assert json.loads(provider.requests[0].messages[1].content)["side"] == "매물"
    assert "매물 대리" in provider.requests[0].messages[0].content
    assert "손님 대리" not in provider.requests[0].messages[0].content


async def test_customer_delegate_gets_the_customer_system_prompt() -> None:
    registry, provider = registry_for(sample_card(price=23.5))

    await workflow.build_position_card(
        registry,
        PositionCardInput(side="손님", label="C01", book_amount=22.0, logs=(CUSTOMER_LOG,)),
    )

    assert "손님 대리" in provider.requests[0].messages[0].content
    assert LISTING_LOG not in provider.requests[0].messages[1].content


async def test_position_card_input_has_no_field_for_the_other_side() -> None:
    """격리가 프롬프트 문구가 아니라 타입으로 보장되는지 본다."""
    fields = set(PositionCardInput.model_fields)
    assert fields == {"side", "label", "pyeong", "deal_type_book", "book_amount", "note", "logs"}


async def test_delegate_route_is_recorded_in_the_trace() -> None:
    registry, _ = registry_for(sample_card())

    result = await workflow.build_position_card(
        registry, PositionCardInput(side="매물", label="203동 1101호", logs=(LISTING_LOG,))
    )

    assert result.trace.agent == "매물대리"
    assert result.trace.model == "gpt-4o-mini"
    assert result.trace.prompt_version == PROMPT_VERSION
    assert result.trace.input_tokens == 100


async def test_judge_matches_sends_one_call_for_anchor_and_all_candidates() -> None:
    """수용 기준 5 — 앵커 1 + 후보 N 을 한 번의 호출로 받는다."""
    verdicts = MatchVerdictList(
        verdicts=[
            MatchVerdict(id="M01", blocker="없음", concession="없음", action="주①에게 전화"),
            MatchVerdict(id="M04", blocker="가격", concession="0.5억", action="보류"),
        ]
    )
    registry, provider = registry_for(verdicts)

    result = await workflow.judge_matches(
        registry,
        anchor_label="C01",
        anchor_card=sample_card(price=23.5),
        candidates=(
            CandidateCardInput(id="M01", label="203동 1101호", card=sample_card()),
            CandidateCardInput(id="M04", label="106동 2104호", card=sample_card(price=25.8)),
        ),
    )

    assert len(provider.requests) == 1
    assert len(result.verdicts) == 2
    assert result.trace.model == "gpt-4o"


async def test_candidate_payload_is_slimmed_but_anchor_keeps_evidence() -> None:
    """후보 축약본에는 근거 원문이 없고 앵커에만 남는다."""
    registry, provider = registry_for(MatchVerdictList(verdicts=[]))

    await workflow.judge_matches(
        registry,
        anchor_label="C01",
        anchor_card=sample_card(),
        candidates=(CandidateCardInput(id="M01", label="203동 1101호", card=sample_card()),),
    )

    payload = json.loads(provider.requests[0].messages[1].content)
    assert payload["anchor"]["card"]["intent_evidence"] == LISTING_LOG
    assert "intent_evidence" not in payload["candidates"][0]
    assert "price_basis" not in payload["candidates"][0]
    assert len(payload["candidates"][0]["flexible"]) == 2


async def test_sampling_is_disabled_for_reproducibility() -> None:
    """F3-NF-08 — 같은 입력에 같은 카드가 나와야 등급 재현성을 검증할 수 있다."""
    registry, provider = registry_for(sample_card())

    await workflow.build_position_card(
        registry, PositionCardInput(side="매물", label="203동 1101호", logs=(LISTING_LOG,))
    )

    assert provider.requests[0].temperature == 0.0


async def test_unknown_side_is_rejected_before_any_model_call() -> None:
    registry, provider = registry_for(sample_card())

    with pytest.raises(ValueError):
        await workflow.build_position_card(
            registry,
            PositionCardInput.model_construct(side="중개사", label="x", logs=()),
        )

    assert provider.requests == []
