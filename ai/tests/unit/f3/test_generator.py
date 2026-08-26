"""포지션 카드 생성 구현 검증.

실제 Provider 도 네트워크도 쓰지 않는다. fake `LlmProvider` 로 무엇을 넘겼고 무엇을
조립했는지만 본다.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from brokerage_ai.core.errors import ProviderRateLimitError
from brokerage_ai.core.types import (
    ModelRoute,
    ProviderDiagnostics,
    ProviderKind,
    StructuredGenerationRequest,
    StructuredGenerationResult,
    TokenUsage,
)
from brokerage_ai.f3 import (
    POSITION_CARD_PROMPT_VERSION,
    POSITION_CARD_WORKFLOW_VERSION,
    ConsultationLogInput,
    ContactabilityAssessment,
    ContactabilityStatus,
    DateSignals,
    Evidence,
    EvidenceKind,
    InputPrivacyMode,
    IntentAssessment,
    ListingAnchorContext,
    LlmPositionCardGenerator,
    NegotiationIntent,
    NegotiationSide,
    PartyRoleContext,
    PositionCardContractError,
    PositionCardGenerationRequest,
    PositionCardTarget,
    PositionCondition,
    PriceKind,
    RequirementAnchorContext,
    SourceIdentity,
    TimingAssessment,
    Urgency,
    UrgencyAssessment,
    validate_generation_result,
)
from brokerage_ai.f3.model_output import ModelPriceOpinion, PositionCardModelOutput
from brokerage_ai.f3.prompts import build_position_card_messages

OLD_AT = datetime(2026, 8, 10, 1, 0, tzinfo=UTC)
NEW_AT = datetime(2026, 8, 19, 4, 0, tzinfo=UTC)
OLD_QUOTE = "28억 아래로는 안 판다"
NEW_QUOTE = "급하지 않습니다"
ROUTE = ModelRoute(provider=ProviderKind.VLLM, model="test-delegate")


class FakeProvider:
    """구조화 출력을 그대로 돌려주는 대역. 호출 인자를 전부 보관한다."""

    def __init__(self, output: PositionCardModelOutput | None = None) -> None:
        self.calls: list[StructuredGenerationRequest] = []
        self.schemas: list[type[BaseModel]] = []
        self.output = output or model_output()

    @property
    def kind(self) -> ProviderKind:
        return ProviderKind.VLLM

    async def generate_structured(
        self, request: StructuredGenerationRequest, output_schema: type[Any]
    ) -> StructuredGenerationResult[Any]:
        self.calls.append(request)
        self.schemas.append(output_schema)
        return StructuredGenerationResult(
            output=self.output,
            diagnostics=ProviderDiagnostics(
                provider=ProviderKind.VLLM,
                model="test-delegate",
                request_id="req-1",
                latency_ms=42.0,
                usage=TokenUsage(input_tokens=120, output_tokens=45, total_tokens=165),
            ),
        )


class ExplodingProvider:
    @property
    def kind(self) -> ProviderKind:
        return ProviderKind.VLLM

    async def generate_structured(
        self, request: StructuredGenerationRequest, output_schema: type[Any]
    ) -> StructuredGenerationResult[Any]:
        raise ProviderRateLimitError()


def quote(interaction_id: int = 12, text: str = NEW_QUOTE) -> Evidence:
    return Evidence(kind=EvidenceKind.QUOTE, interaction_id=interaction_id, quote_text=text)


def inference(note: str = "최근 접촉 이력이 짧다") -> Evidence:
    return Evidence(kind=EvidenceKind.INFERENCE, note=note)


def model_output(**overrides: object) -> PositionCardModelOutput:
    values: dict[str, object] = {
        "intent": IntentAssessment(value=NegotiationIntent.PRESENT, evidence=(quote(),)),
        "urgency": UrgencyAssessment(value=Urgency.RELAXED, evidence=(quote(),)),
        "price": (),
        "timing": TimingAssessment(),
        "contactability": ContactabilityAssessment(
            status=ContactabilityStatus.GOOD, evidence=(inference(),)
        ),
    }
    values.update(overrides)
    return PositionCardModelOutput(**values)  # pyright: ignore[reportArgumentType]


def logs() -> tuple[ConsultationLogInput, ...]:
    return (
        ConsultationLogInput(
            interaction_id=12,
            interaction_at=NEW_AT,
            channel="CALL",
            counterparty_role="OWNER",
            masked_content=f"소유자 통화. {NEW_QUOTE}.",
        ),
        ConsultationLogInput(
            interaction_id=5,
            interaction_at=OLD_AT,
            channel="VISIT",
            masked_content=f"방문 상담. {OLD_QUOTE}.",
        ),
    )


def source() -> SourceIdentity:
    return SourceIdentity(
        data_version=3, interaction_count=2, last_interaction_at=NEW_AT, max_interaction_id=12
    )


def listing_request(**anchor_overrides: object) -> PositionCardGenerationRequest:
    values: dict[str, object] = {
        "listing_id": 51,
        "unit_id": 7,
        "listing_status": "RECEIVED",
        "is_sale_available": True,
        "sale_price": 2_880_000_000,
        "unit_number": "1801",
        "party_roles": (PartyRoleContext(role="OWNER", is_primary=True, is_co_owner=True),),
        "client_party_role": "OWNER",
    }
    values.update(anchor_overrides)
    return PositionCardGenerationRequest(
        input_privacy_mode=InputPrivacyMode.SYNTHETIC_PROTOTYPE,
        negotiation_side=NegotiationSide.LISTING,
        anchor_id=51,
        target_label="검증단지 1801호",
        source=source(),
        anchor=ListingAnchorContext(**values),  # pyright: ignore[reportArgumentType]
        date_signals=DateSignals(
            as_of=datetime(2026, 8, 20, 1, 0, tzinfo=UTC),
            days_until_tenancy_expiry=102,
            hard_deadline_candidate=date(2026, 11, 30),
        ),
        consultation_logs=logs(),
    )


def requirement_request() -> PositionCardGenerationRequest:
    return PositionCardGenerationRequest(
        input_privacy_mode=InputPrivacyMode.SYNTHETIC_PROTOTYPE,
        negotiation_side=NegotiationSide.REQUIREMENT,
        anchor_id=91,
        target_label="구입장 #91",
        source=source(),
        anchor=RequirementAnchorContext(  # pyright: ignore[reportArgumentType]
            requirement_id=91,
            demand_type="매수",
            status="ACTIVE",
            max_budget_amount=2_850_000_000,
            has_co_broker=True,
        ),
        date_signals=DateSignals(as_of=datetime(2026, 8, 20, 1, 0, tzinfo=UTC)),
        consultation_logs=logs(),
    )


def generator(provider: FakeProvider) -> LlmPositionCardGenerator:
    return LlmPositionCardGenerator(
        provider=provider,
        route=ROUTE,
        allow_synthetic_prototype=True,
    )


# --- 호출 ---------------------------------------------------------------------


def test_generator_rejects_provider_and_route_mismatch() -> None:
    route = ModelRoute(provider=ProviderKind.OPENAI, model="test-model")

    with pytest.raises(ValueError, match="provider kind and model route provider must match"):
        LlmPositionCardGenerator(provider=FakeProvider(), route=route)


async def test_synthetic_prototype_input_requires_an_explicit_opt_in() -> None:
    provider = FakeProvider()
    subject = LlmPositionCardGenerator(provider=provider, route=ROUTE)

    with pytest.raises(PositionCardContractError, match="explicit generator opt-in"):
        await subject.generate_position_card(listing_request())

    assert provider.calls == []


async def test_masked_input_does_not_require_the_prototype_opt_in() -> None:
    provider = FakeProvider()
    subject = LlmPositionCardGenerator(provider=provider, route=ROUTE)
    request = listing_request().model_copy(update={"input_privacy_mode": InputPrivacyMode.MASKED})

    await subject.generate_position_card(request)

    assert len(provider.calls) == 1


async def test_listing_generation_calls_the_provider_exactly_once() -> None:
    provider = FakeProvider()
    request = listing_request()

    result = await generator(provider).generate_position_card(request)

    assert len(provider.calls) == 1
    assert provider.schemas == [PositionCardModelOutput]
    assert result.analysis.intent.value is NegotiationIntent.PRESENT


async def test_requirement_generation_calls_the_provider_exactly_once() -> None:
    provider = FakeProvider()

    result = await generator(provider).generate_position_card(requirement_request())

    assert len(provider.calls) == 1
    assert result.target.negotiation_side is NegotiationSide.REQUIREMENT


async def test_generation_is_deterministic_at_temperature_zero() -> None:
    provider = FakeProvider()

    await generator(provider).generate_position_card(listing_request())

    assert provider.calls[0].temperature == 0.0
    assert provider.calls[0].route == ROUTE


# --- 서버 소유 값 ---------------------------------------------------------------


async def test_target_and_source_are_copied_from_the_request() -> None:
    provider = FakeProvider()
    request = listing_request()

    result = await generator(provider).generate_position_card(request)

    assert result.target == PositionCardTarget.from_request(request)
    assert result.target.source == request.source
    assert result.contract_version == request.contract_version


async def test_stated_price_is_copied_from_the_ledger_not_the_model() -> None:
    """모델이 추정만 내도 표기 금액은 요청 장부값이 그대로 들어가야 한다."""
    provider = FakeProvider(
        model_output(
            price=(
                ModelPriceOpinion(
                    price_kind=PriceKind.SALE,
                    estimated_amount=2_700_000_000,
                    basis=(quote(interaction_id=5, text=OLD_QUOTE),),
                ),
            )
        )
    )
    request = listing_request()

    result = await generator(provider).generate_position_card(request)

    (sale,) = result.analysis.price
    assert sale.price_kind is PriceKind.SALE
    assert sale.stated_amount == 2_880_000_000
    assert sale.estimated_amount == 2_700_000_000
    validate_generation_result(request, result)


async def test_a_price_kind_the_ledger_does_not_offer_is_dropped() -> None:
    provider = FakeProvider(
        model_output(price=(ModelPriceOpinion(price_kind=PriceKind.JEONSE, estimated_amount=1),))
    )
    request = listing_request()

    result = await generator(provider).generate_position_card(request)

    assert [assessment.price_kind for assessment in result.analysis.price] == [PriceKind.SALE]
    validate_generation_result(request, result)


async def test_every_enabled_price_kind_survives_even_without_a_model_opinion() -> None:
    provider = FakeProvider()
    request = listing_request(
        is_jeonse_available=True,
        jeonse_deposit_amount=1_500_000_000,
        is_monthly_rent_available=True,
        monthly_rent_deposit_amount=100_000_000,
        monthly_rent_amount=3_000_000,
    )

    result = await generator(provider).generate_position_card(request)

    assert [assessment.price_kind for assessment in result.analysis.price] == [
        PriceKind.SALE,
        PriceKind.JEONSE,
        PriceKind.MONTHLY_RENT,
    ]
    monthly = result.analysis.price[2]
    assert monthly.stated_amount == 100_000_000
    assert monthly.stated_monthly_amount == 3_000_000
    validate_generation_result(request, result)


def test_model_output_schema_has_no_server_owned_fields() -> None:
    fields = set(PositionCardModelOutput.model_fields)
    forbidden = {
        "negotiation_side",
        "anchor_id",
        "source",
        "target",
        "contract_version",
        "cache_key",
        "generated_at",
        "run_id",
        "brokerage_id",
        "requested_by",
        "lease_owner",
        "attempt_count",
    }

    assert not fields & forbidden
    assert "stated_amount" not in set(ModelPriceOpinion.model_fields)
    assert "stated_monthly_amount" not in set(ModelPriceOpinion.model_fields)


# --- 버전과 진단 ---------------------------------------------------------------


async def test_prompt_and_workflow_versions_are_always_recorded() -> None:
    provider = FakeProvider()
    subject = generator(provider)

    result = await subject.generate_position_card(listing_request())

    assert result.prompt_version == POSITION_CARD_PROMPT_VERSION == "position-card-prompt:v2"
    assert result.workflow_version == POSITION_CARD_WORKFLOW_VERSION == "position-card-workflow:v1"
    # Backend 는 cache key 를 계산하기 전에 같은 값을 알 수 있어야 한다.
    assert subject.versions.prompt_version == result.prompt_version
    assert subject.versions.workflow_version == result.workflow_version


async def test_provider_diagnostics_reach_the_result() -> None:
    provider = FakeProvider()

    result = await generator(provider).generate_position_card(listing_request())

    assert result.diagnostics is not None
    assert result.diagnostics.request_id == "req-1"
    assert result.diagnostics.latency_ms == 42.0
    assert result.diagnostics.usage is not None
    assert result.diagnostics.usage.input_tokens == 120
    assert result.diagnostics.usage.output_tokens == 45


async def test_provider_errors_carry_no_prompt_or_raw_response() -> None:
    subject = LlmPositionCardGenerator(
        provider=ExplodingProvider(),
        route=ROUTE,
        allow_synthetic_prototype=True,
    )

    with pytest.raises(ProviderRateLimitError) as raised:
        await subject.generate_position_card(listing_request())

    rendered = str(raised.value)
    assert rendered == "provider rate limit exceeded"
    for secret in (NEW_QUOTE, OLD_QUOTE, "매물 대리", "1801"):
        assert secret not in rendered


# --- 프롬프트 ------------------------------------------------------------------


async def sent_prompt(
    request: PositionCardGenerationRequest, output: PositionCardModelOutput | None = None
) -> str:
    provider = FakeProvider(output)
    await generator(provider).generate_position_card(request)
    return "\n".join(message.content for message in provider.calls[0].messages)


async def test_every_consultation_log_is_sent_in_chronological_order() -> None:
    """최신 N건만 골라 보내지 않는다. 오래된 로그가 먼저 와야 철회 판정이 성립한다."""
    prompt = await sent_prompt(listing_request())

    assert prompt.index(OLD_QUOTE) < prompt.index(NEW_QUOTE)
    assert "[5]" in prompt and "[12]" in prompt
    assert "상담 로그 2건" in prompt


async def test_prompt_states_the_evidence_unknown_and_isolation_rules() -> None:
    prompt = await sent_prompt(listing_request())

    for rule in (
        "kind=QUOTE",
        "kind=INFERENCE",
        "UNKNOWN",
        "반대편 당사자의 데이터",
        "날짜 산수를 하지 않는다",
        "hard_deadline_candidate",
        "한국어",
        "최신 진술이 과거 진술을 이긴다",
        "개인정보를 생성하거나 복원하지 않는다",
        "inflexible",
        "해당하지 않는 필드는 반드시 null",
    ):
        assert rule in prompt


async def test_each_side_prompt_names_only_its_own_scope() -> None:
    listing_prompt = await sent_prompt(listing_request())
    requirement_prompt = await sent_prompt(requirement_request())

    assert "너는 매물 대리다" in listing_prompt
    assert "너는 손님 대리다" not in listing_prompt
    assert "너는 손님 대리다" in requirement_prompt
    assert "너는 매물 대리다" not in requirement_prompt


async def test_prompt_carries_the_role_context_but_no_identifiers() -> None:
    prompt = await sent_prompt(listing_request())

    assert "is_co_owner" in prompt
    assert "client_party_role" in prompt
    assert "party_id" not in prompt


async def test_prompt_does_not_ask_the_model_for_source_identity() -> None:
    prompt = await sent_prompt(listing_request())

    assert "interaction_count" not in prompt
    assert "contract_version" not in prompt


async def test_an_empty_log_set_still_produces_a_valid_prompt() -> None:
    request = PositionCardGenerationRequest(
        input_privacy_mode=InputPrivacyMode.SYNTHETIC_PROTOTYPE,
        negotiation_side=NegotiationSide.REQUIREMENT,
        anchor_id=91,
        target_label="구입장 #91",
        source=SourceIdentity(data_version=1, interaction_count=0),
        anchor=RequirementAnchorContext(  # pyright: ignore[reportArgumentType]
            requirement_id=91, demand_type="매수", status="ACTIVE"
        ),
        date_signals=DateSignals(as_of=datetime(2026, 8, 20, 1, 0, tzinfo=UTC)),
    )

    prompt = await sent_prompt(
        request,
        model_output(
            intent=IntentAssessment(
                value=NegotiationIntent.PRESENT,
                evidence=(inference("조건 입력에서 의향을 확인했다"),),
            ),
            urgency=UrgencyAssessment(
                value=Urgency.RELAXED,
                evidence=(inference("명시된 기한이 없다"),),
            ),
        ),
    )

    assert "상담 로그 0건" in prompt


# --- 조립 결과가 계약을 통과하는가 ------------------------------------------------


async def test_the_assembled_result_passes_the_shared_contract_validation() -> None:
    provider = FakeProvider(
        model_output(
            timing=TimingAssessment(
                constraints=(
                    PositionCondition(description="임대차 만기 전 명도", evidence=(quote(),)),
                ),
                hard_deadline=date(2026, 11, 30),
            ),
            inflexible=(
                PositionCondition(
                    description="공동명의라 단독 결정이 어렵다", evidence=(inference(),)
                ),
            ),
        )
    )
    request = listing_request()

    result = await generator(provider).generate_position_card(request)

    validate_generation_result(request, result)
    assert result.analysis.timing.hard_deadline == date(2026, 11, 30)


async def test_generator_rejects_a_quote_from_outside_the_request() -> None:
    provider = FakeProvider(
        model_output(
            intent=IntentAssessment(
                value=NegotiationIntent.PRESENT,
                evidence=(quote(interaction_id=999),),
            )
        )
    )

    with pytest.raises(PositionCardContractError, match="outside the request"):
        await generator(provider).generate_position_card(listing_request())


async def test_generator_rejects_a_quote_not_present_in_the_masked_content() -> None:
    provider = FakeProvider(
        model_output(
            intent=IntentAssessment(
                value=NegotiationIntent.PRESENT,
                evidence=(quote(text="본문에 없는 인용문"),),
            )
        )
    )

    with pytest.raises(PositionCardContractError, match="not present"):
        await generator(provider).generate_position_card(listing_request())


async def test_generator_rejects_a_deadline_outside_the_backend_date_signal() -> None:
    provider = FakeProvider(
        model_output(
            timing=TimingAssessment(
                constraints=(PositionCondition(description="명도 일정", evidence=(quote(),)),),
                hard_deadline=date(2026, 12, 1),
            )
        )
    )

    with pytest.raises(PositionCardContractError, match="backend date signal"):
        await generator(provider).generate_position_card(listing_request())


def test_model_output_rejects_a_repeated_price_kind() -> None:
    with pytest.raises(ValidationError):
        model_output(
            price=(
                ModelPriceOpinion(price_kind=PriceKind.SALE),
                ModelPriceOpinion(price_kind=PriceKind.SALE),
            )
        )


async def test_prompt_states_the_rules_the_schema_cannot_express() -> None:
    """JSON schema 로 표현되지 않는 교차 필드 규칙은 프롬프트가 책임진다.

    계약(`PositionCardModelOutput`)은 이 규칙들을 `model_validator` 로 강제하지만 strict schema
    에는 담기지 않는다. 프롬프트에도 없으면 모델은 규칙의 존재조차 모른 채 어기고, 그 출력이
    검증에서 걸려 실행이 실패한다. 실제로 `hard_deadline` 규칙이 빠져 있어 후보 카드 생성이
    반복 실패했다.

    새 교차 필드 규칙을 계약에 추가하면 이 테스트가 그것을 여기에 적도록 상기시킨다.
    """
    messages = build_position_card_messages(listing_request())
    prompt = "\n".join(message.content for message in messages)

    assert "hard_deadline" in prompt
    # 근거 없는 마감일을 세우지 말라는 규칙 (F3-PC-04).
    assert "null 이다" in prompt
    # 같은 price_kind 를 두 번 담지 말라는 규칙.
    assert "price_kind 를 두 번" in prompt
    # 월 차임은 MONTHLY_RENT 에서만 쓰라는 규칙.
    assert "MONTHLY_RENT" in prompt
    # 로그가 없으면 인용할 원문도 없다는 규칙. 실제로 모델이 앵커 장부 값을 인용으로 냈다.
    assert "kind=QUOTE 를 쓰지 않는다" in prompt
