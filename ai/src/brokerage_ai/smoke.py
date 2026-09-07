"""Synthetic serving acceptance through the public AI workflows; no DB or user data."""

from __future__ import annotations

from datetime import UTC, datetime

from brokerage_ai.core.config import AiConfig
from brokerage_ai.core.types import ModelRoute
from brokerage_ai.f3 import (
    BrokerageJudgmentRequest,
    DateSignals,
    InputPrivacyMode,
    JudgmentCard,
    ListingAnchorContext,
    LlmBrokerageJudgmentGenerator,
    LlmPositionCardGenerator,
    NegotiationSide,
    PositionCardGenerationRequest,
    RequirementAnchorContext,
    SourceIdentity,
)
from brokerage_ai.runtime import create_ai_runtime


def synthetic_requests() -> tuple[PositionCardGenerationRequest, PositionCardGenerationRequest]:
    common = {
        "input_privacy_mode": InputPrivacyMode.SYNTHETIC_PROTOTYPE,
        "source": SourceIdentity(
            data_version=1, interaction_count=0, last_interaction_at=None, max_interaction_id=None
        ),
        "date_signals": DateSignals(as_of=datetime(2026, 9, 7, tzinfo=UTC)),
        "consultation_logs": (),
    }
    return (
        PositionCardGenerationRequest(
            **common,
            negotiation_side=NegotiationSide.LISTING,
            anchor_id=1,
            target_label="합성 검증 매물",
            anchor=ListingAnchorContext(
                listing_id=1,
                unit_id=1,
                unit_number="합성 101호",
                listing_status="RECEIVED",
                is_sale_available=True,
                sale_price=500_000_000,
            ),
        ),
        PositionCardGenerationRequest(
            **common,
            negotiation_side=NegotiationSide.REQUIREMENT,
            anchor_id=2,
            target_label="합성 검증 구입 요청",
            anchor=RequirementAnchorContext(
                requirement_id=2, demand_type="매수", status="ACTIVE", max_budget_amount=550_000_000
            ),
        ),
    )


async def smoke_general(config: AiConfig, route: ModelRoute) -> None:
    async with create_ai_runtime(config) as runtime:
        provider = runtime.providers.get_llm(route.provider, route.endpoint_alias)
        generator = LlmPositionCardGenerator(
            provider=provider, route=route, allow_synthetic_prototype=True
        )
        cards = []
        for index, request in enumerate(synthetic_requests(), start=1):
            result = await generator.generate_position_card(request)
            cards.append(
                JudgmentCard(
                    card_id=index,
                    negotiation_side=request.negotiation_side,
                    target_label=request.target_label,
                    analysis=result.analysis,
                )
            )
        judgment = LlmBrokerageJudgmentGenerator(
            provider=provider, route=route, allow_synthetic_prototype=True
        )
        await judgment.judge_candidates(
            BrokerageJudgmentRequest(
                input_privacy_mode=InputPrivacyMode.SYNTHETIC_PROTOTYPE,
                anchor=cards[0],
                candidates=(cards[1],),
            )
        )


if __name__ == "__main__":
    import asyncio

    from brokerage_ai import ProviderKind, load_ai_config

    try:
        asyncio.run(
            smoke_general(
                load_ai_config("local"),
                ModelRoute(
                    provider=ProviderKind.VLLM,
                    model="unsloth/Qwen3.8-27B-unsloth-bnb-4bit",
                    endpoint_alias="general-dev-gpu",
                ),
            )
        )
    except Exception:
        raise SystemExit(
            "General GPU smoke failed; check local connection and credentials."
        ) from None
    print("general synthetic workflows: OK")
