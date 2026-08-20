"""F3 포지션 카드 공개 계약 검증.

모델도 네트워크도 쓰지 않는다. 여기서 확인하는 것은 어휘가 하나로 고정되는가, 반대편
데이터가 타입 수준에서 막히는가, 근거 없는 판정이 거절되는가, 그리고 결과가 요청 범위를
벗어나면 잡히는가다.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from brokerage_ai.core.types import ProviderDiagnostics, ProviderKind
from brokerage_ai.f3 import (
    POSITION_CARD_CONTRACT_VERSION,
    ConsultationLogInput,
    ContactabilityAssessment,
    ContactabilityStatus,
    DateSignals,
    Evidence,
    EvidenceKind,
    IntentAssessment,
    ListingAnchorContext,
    NegotiationIntent,
    NegotiationSide,
    PositionCardAnalysis,
    PositionCardContractError,
    PositionCardGenerationRequest,
    PositionCardGenerationResult,
    PositionCardGenerator,
    PositionCardTarget,
    PositionCondition,
    PriceAssessment,
    PriceKind,
    RequirementAnchorContext,
    SourceIdentity,
    TimingAssessment,
    Urgency,
    UrgencyAssessment,
    validate_generation_result,
)

LOG_AT = datetime(2026, 8, 19, 4, 0, tzinfo=UTC)
QUOTE = "급하지 않습니다"
LOG_CONTENT = f"소유자 통화. {QUOTE}. 연락은 [고객1]에게."


def log(interaction_id: int = 11, content: str = LOG_CONTENT) -> ConsultationLogInput:
    return ConsultationLogInput(
        interaction_id=interaction_id,
        interaction_at=LOG_AT,
        channel="CALL",
        counterparty_role="OWNER",
        interaction_result="ANSWERED",
        masked_content=content,
    )


def source() -> SourceIdentity:
    return SourceIdentity(
        data_version=3,
        interaction_count=1,
        last_interaction_at=LOG_AT,
        max_interaction_id=11,
    )


def listing_anchor(**overrides: object) -> ListingAnchorContext:
    values: dict[str, object] = {
        "listing_id": 51,
        "unit_id": 7,
        "listing_status": "RECEIVED",
        "is_sale_available": True,
        "sale_price": 2_880_000_000,
        "unit_number": "1801",
        "pyeong": Decimal("34.00"),
        "tenancy_expiry_date": date(2026, 11, 30),
    }
    values.update(overrides)
    return ListingAnchorContext(**values)  # pyright: ignore[reportArgumentType]


def requirement_anchor(**overrides: object) -> RequirementAnchorContext:
    values: dict[str, object] = {
        "requirement_id": 91,
        "demand_type": "매수",
        "status": "ACTIVE",
        "max_budget_amount": 2_850_000_000,
    }
    values.update(overrides)
    return RequirementAnchorContext(**values)  # pyright: ignore[reportArgumentType]


def signals() -> DateSignals:
    return DateSignals(
        as_of=datetime(2026, 8, 20, 1, 0, tzinfo=UTC),
        days_until_tenancy_expiry=102,
        days_since_last_contact=1,
        hard_deadline_candidate=date(2026, 11, 30),
    )


def listing_request(**overrides: object) -> PositionCardGenerationRequest:
    values: dict[str, object] = {
        "negotiation_side": NegotiationSide.LISTING,
        "anchor_id": 51,
        "source": source(),
        "anchor": listing_anchor(),
        "date_signals": signals(),
        "consultation_logs": (log(),),
    }
    values.update(overrides)
    return PositionCardGenerationRequest(**values)  # pyright: ignore[reportArgumentType]


def quote_evidence(interaction_id: int = 11, text: str = QUOTE) -> Evidence:
    return Evidence(kind=EvidenceKind.QUOTE, interaction_id=interaction_id, quote_text=text)


def inference_evidence(note: str = "최근 6개월 접촉 이력이 없다") -> Evidence:
    return Evidence(kind=EvidenceKind.INFERENCE, note=note)


def analysis(**overrides: object) -> PositionCardAnalysis:
    values: dict[str, object] = {
        "intent": IntentAssessment(value=NegotiationIntent.PRESENT, evidence=(quote_evidence(),)),
        "price": (PriceAssessment(price_kind=PriceKind.SALE, stated_amount=2_880_000_000),),
        "urgency": UrgencyAssessment(value=Urgency.RELAXED, evidence=(quote_evidence(),)),
        "timing": TimingAssessment(),
        "contactability": ContactabilityAssessment(
            status=ContactabilityStatus.GOOD, evidence=(inference_evidence(),)
        ),
    }
    values.update(overrides)
    return PositionCardAnalysis(**values)  # pyright: ignore[reportArgumentType]


def result_for(
    request: PositionCardGenerationRequest, **overrides: object
) -> PositionCardGenerationResult:
    values: dict[str, object] = {
        "target": PositionCardTarget.from_request(request),
        "analysis": analysis(),
    }
    values.update(overrides)
    return PositionCardGenerationResult(**values)  # pyright: ignore[reportArgumentType]


# --- 어휘 ---------------------------------------------------------------------


def test_negotiation_side_allows_exactly_listing_and_requirement() -> None:
    assert [side.value for side in NegotiationSide] == ["LISTING", "REQUIREMENT"]

    for rejected in ("CUSTOMER", "BUYER", "SELLER", "PROPERTY", "매물", "손님"):
        with pytest.raises(ValueError):
            NegotiationSide(rejected)


def test_judgement_vocabularies_match_the_stored_defaults() -> None:
    """DB 기본값이 그대로 유효한 계약값이어야 저장 시 어휘가 갈라지지 않는다."""
    assert NegotiationIntent.UNKNOWN.value == "UNKNOWN"
    assert Urgency.UNKNOWN.value == "UNKNOWN"
    assert ContactabilityStatus.CAUTION.value == "CAUTION"
    assert ContactabilityStatus.UNKNOWN.value == "UNKNOWN"
    assert EvidenceKind.INFERENCE.value == "INFERENCE"


def test_contract_version_is_position_card_v1() -> None:
    assert POSITION_CARD_CONTRACT_VERSION == "position-card:v1"
    assert listing_request().contract_version == "position-card:v1"


# --- 입력 격리 -----------------------------------------------------------------


def test_listing_request_rejects_a_requirement_context() -> None:
    with pytest.raises(ValidationError):
        listing_request(anchor=requirement_anchor(requirement_id=51))


def test_requirement_request_rejects_a_listing_context() -> None:
    with pytest.raises(ValidationError):
        PositionCardGenerationRequest(
            negotiation_side=NegotiationSide.REQUIREMENT,
            anchor_id=51,
            source=source(),
            anchor=listing_anchor(),  # pyright: ignore[reportArgumentType]
            date_signals=signals(),
        )


def test_anchor_id_must_match_the_context_target() -> None:
    with pytest.raises(ValidationError):
        listing_request(anchor_id=52)


def test_listing_context_rejects_requirement_fields() -> None:
    with pytest.raises(ValidationError):
        listing_anchor(max_budget_amount=2_850_000_000)


def test_requirement_context_rejects_listing_fields() -> None:
    with pytest.raises(ValidationError):
        requirement_anchor(sale_price=2_880_000_000)


# --- 공통 DTO 규칙 -------------------------------------------------------------


def test_extra_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        listing_request(requested_by=7)


def test_blank_strings_are_rejected() -> None:
    with pytest.raises(ValidationError):
        log(content="   ")
    with pytest.raises(ValidationError):
        listing_anchor(listing_status="  ")
    with pytest.raises(ValidationError):
        PositionCondition(description="  ", evidence=(inference_evidence(),))


@pytest.mark.parametrize(
    "overrides",
    [
        {"listing_id": -1},
        {"unit_id": 0},
        {"sale_price": -1},
        {"current_deposit_amount": -1},
        {"pyeong": Decimal("-1")},
    ],
    ids=["매물ID", "세대ID", "매매가", "보증금", "평형"],
)
def test_negative_identifiers_and_amounts_are_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        listing_anchor(**overrides)


@pytest.mark.parametrize(
    "overrides",
    [{"data_version": 0}, {"interaction_count": -1}, {"max_interaction_id": 0}],
    ids=["버전", "건수", "최대ID"],
)
def test_negative_source_identity_values_are_rejected(overrides: dict[str, object]) -> None:
    values: dict[str, object] = {
        "data_version": 1,
        "interaction_count": 1,
        "last_interaction_at": LOG_AT,
        "max_interaction_id": 11,
    }
    values.update(overrides)
    with pytest.raises(ValidationError):
        SourceIdentity(**values)  # pyright: ignore[reportArgumentType]


def test_a_non_empty_source_identity_requires_its_last_moment_and_maximum_id() -> None:
    with pytest.raises(ValidationError):
        SourceIdentity(data_version=1, interaction_count=1)


@pytest.mark.parametrize(
    ("source_override", "logs"),
    [
        ({"interaction_count": 2}, (log(),)),
        ({"max_interaction_id": 99}, (log(),)),
        (
            {"last_interaction_at": datetime(2026, 8, 18, 4, 0, tzinfo=UTC)},
            (log(),),
        ),
    ],
    ids=["건수", "최대ID", "마지막시각"],
)
def test_consultation_logs_must_match_the_source_identity(
    source_override: dict[str, object], logs: tuple[ConsultationLogInput, ...]
) -> None:
    source_values: dict[str, object] = {
        "data_version": 3,
        "interaction_count": 1,
        "last_interaction_at": LOG_AT,
        "max_interaction_id": 11,
    }
    source_values.update(source_override)

    with pytest.raises(ValidationError):
        listing_request(
            source=SourceIdentity(**source_values),  # pyright: ignore[reportArgumentType]
            consultation_logs=logs,
        )


def test_naive_datetimes_are_rejected() -> None:
    """timezone 이 없으면 서버 로컬 시각으로 암묵 해석되어 cache key 가 갈라진다."""
    naive = datetime(2026, 8, 19, 4, 0)

    with pytest.raises(ValidationError):
        ConsultationLogInput(
            interaction_id=11,
            interaction_at=naive,
            channel="CALL",
            masked_content=LOG_CONTENT,
        )
    with pytest.raises(ValidationError):
        SourceIdentity(data_version=1, interaction_count=1, last_interaction_at=naive)
    with pytest.raises(ValidationError):
        DateSignals(as_of=naive)


def test_unknown_values_round_trip_as_explicit_results() -> None:
    """판단 불가는 필드 누락이 아니라 명시적 UNKNOWN 으로 직렬화된다 (F3-PC-01)."""
    unknown = analysis(
        intent=IntentAssessment(
            value=NegotiationIntent.UNKNOWN, evidence=(inference_evidence("로그가 없다"),)
        ),
        urgency=UrgencyAssessment(
            value=Urgency.UNKNOWN, evidence=(inference_evidence("로그가 없다"),)
        ),
        contactability=ContactabilityAssessment(
            status=ContactabilityStatus.UNKNOWN,
            evidence=(inference_evidence("접촉 이력이 없다"),),
        ),
    )

    payload = unknown.model_dump(mode="json")

    assert payload["intent"]["value"] == "UNKNOWN"
    assert payload["urgency"]["value"] == "UNKNOWN"
    assert payload["contactability"]["status"] == "UNKNOWN"


# --- Evidence -----------------------------------------------------------------


def test_quote_evidence_requires_an_interaction_id() -> None:
    with pytest.raises(ValidationError):
        Evidence(kind=EvidenceKind.QUOTE, quote_text=QUOTE)


def test_quote_evidence_requires_quote_text() -> None:
    with pytest.raises(ValidationError):
        Evidence(kind=EvidenceKind.QUOTE, interaction_id=11)


def test_inference_evidence_requires_a_note() -> None:
    with pytest.raises(ValidationError):
        Evidence(kind=EvidenceKind.INFERENCE)


def test_inference_evidence_must_not_carry_a_quote() -> None:
    with pytest.raises(ValidationError):
        Evidence(kind=EvidenceKind.INFERENCE, note="추정", interaction_id=11, quote_text=QUOTE)


def test_evidence_does_not_expose_quote_offsets() -> None:
    """offset 은 Backend 가 실제 원문에서 계산한다. 모델이 만들 자리가 없어야 한다."""
    fields = set(Evidence.model_fields)

    assert "quote_start_offset" not in fields
    assert "quote_end_offset" not in fields


def test_conditions_without_evidence_are_rejected() -> None:
    with pytest.raises(ValidationError):
        PositionCondition(description="잔금일 조정 가능", evidence=())
    with pytest.raises(ValidationError):
        IntentAssessment(value=NegotiationIntent.PRESENT, evidence=())
    with pytest.raises(ValidationError):
        UrgencyAssessment(value=Urgency.NORMAL, evidence=())
    with pytest.raises(ValidationError):
        ContactabilityAssessment(status=ContactabilityStatus.GOOD, evidence=())


# --- 가격과 시점 ---------------------------------------------------------------


def test_an_estimate_that_differs_from_the_stated_price_requires_a_basis() -> None:
    with pytest.raises(ValidationError):
        PriceAssessment(
            price_kind=PriceKind.SALE,
            stated_amount=2_880_000_000,
            estimated_amount=2_750_000_000,
        )

    allowed = PriceAssessment(
        price_kind=PriceKind.SALE,
        stated_amount=2_880_000_000,
        estimated_amount=2_750_000_000,
        basis=(quote_evidence(text="27억대면 정리한다"),),
    )
    assert allowed.estimated_amount == 2_750_000_000


def test_an_estimate_equal_to_the_stated_price_needs_no_basis() -> None:
    assessment = PriceAssessment(
        price_kind=PriceKind.SALE,
        stated_amount=2_880_000_000,
        estimated_amount=2_880_000_000,
    )

    assert assessment.basis == ()


def test_monthly_amounts_belong_to_monthly_rent_only() -> None:
    with pytest.raises(ValidationError):
        PriceAssessment(price_kind=PriceKind.SALE, stated_amount=1, stated_monthly_amount=1_000_000)

    assessment = PriceAssessment(
        price_kind=PriceKind.MONTHLY_RENT,
        stated_amount=100_000_000,
        stated_monthly_amount=1_000_000,
    )
    assert assessment.stated_monthly_amount == 1_000_000


def test_price_kinds_are_not_repeated() -> None:
    with pytest.raises(ValidationError):
        analysis(
            price=(
                PriceAssessment(price_kind=PriceKind.SALE, stated_amount=1),
                PriceAssessment(price_kind=PriceKind.SALE, stated_amount=2),
            )
        )


def test_a_hard_deadline_requires_at_least_one_constraint() -> None:
    with pytest.raises(ValidationError):
        TimingAssessment(hard_deadline=date(2026, 11, 30))

    timing = TimingAssessment(
        constraints=(
            PositionCondition(description="임대차 만기 전 명도", evidence=(quote_evidence(),)),
        ),
        hard_deadline=date(2026, 11, 30),
    )
    assert timing.hard_deadline == date(2026, 11, 30)


# --- 요청·결과 교차 검증 --------------------------------------------------------


def test_a_matching_result_passes_validation() -> None:
    request = listing_request()

    validate_generation_result(request, result_for(request))


def test_a_result_that_quotes_an_unknown_interaction_is_rejected() -> None:
    request = listing_request()
    stray = result_for(
        request,
        analysis=analysis(
            intent=IntentAssessment(
                value=NegotiationIntent.PRESENT, evidence=(quote_evidence(interaction_id=999),)
            )
        ),
    )

    with pytest.raises(PositionCardContractError, match="outside the request"):
        validate_generation_result(request, stray)


def test_a_quote_that_is_not_in_the_masked_content_is_rejected() -> None:
    request = listing_request()
    invented = result_for(
        request,
        analysis=analysis(
            intent=IntentAssessment(
                value=NegotiationIntent.PRESENT,
                evidence=(quote_evidence(text="당장 팔겠습니다"),),
            )
        ),
    )

    with pytest.raises(PositionCardContractError, match="not present in interaction"):
        validate_generation_result(request, invented)


def test_a_result_that_changes_the_stated_price_is_rejected() -> None:
    request = listing_request()
    rewritten = result_for(
        request,
        analysis=analysis(
            price=(PriceAssessment(price_kind=PriceKind.SALE, stated_amount=9_000_000_000),)
        ),
    )

    with pytest.raises(PositionCardContractError, match="does not match the ledger"):
        validate_generation_result(request, rewritten)


@pytest.mark.parametrize(
    ("price_kind", "anchor_overrides", "assessment_kwargs"),
    [
        (PriceKind.SALE, {"is_sale_available": False}, {"stated_amount": 2_880_000_000}),
        (
            PriceKind.JEONSE,
            {"is_jeonse_available": False, "jeonse_deposit_amount": 1_000_000_000},
            {"stated_amount": 1_000_000_000},
        ),
        (
            PriceKind.MONTHLY_RENT,
            {
                "is_monthly_rent_available": False,
                "monthly_rent_deposit_amount": 100_000_000,
                "monthly_rent_amount": 1_000_000,
            },
            {"stated_amount": 100_000_000, "stated_monthly_amount": 1_000_000},
        ),
    ],
    ids=["매매", "전세", "월세"],
)
def test_a_listing_price_kind_must_be_enabled(
    price_kind: PriceKind,
    anchor_overrides: dict[str, object],
    assessment_kwargs: dict[str, object],
) -> None:
    request = listing_request(anchor=listing_anchor(**anchor_overrides))
    inactive = result_for(
        request,
        analysis=analysis(
            price=(PriceAssessment.model_validate({"price_kind": price_kind, **assessment_kwargs}),)
        ),
    )

    with pytest.raises(PositionCardContractError, match="not enabled"):
        validate_generation_result(request, inactive)


def test_a_price_kind_from_the_other_side_is_rejected() -> None:
    request = listing_request()
    crossed = result_for(
        request,
        analysis=analysis(
            price=(PriceAssessment(price_kind=PriceKind.BUDGET, stated_amount=None),)
        ),
    )

    with pytest.raises(PositionCardContractError, match="not valid for"):
        validate_generation_result(request, crossed)


def test_a_result_for_a_different_target_or_source_is_rejected() -> None:
    request = listing_request()

    other_target = result_for(
        request,
        target=PositionCardTarget(
            negotiation_side=NegotiationSide.LISTING, anchor_id=52, source=source()
        ),
    )
    with pytest.raises(PositionCardContractError, match="different anchor"):
        validate_generation_result(request, other_target)

    other_source = result_for(
        request,
        target=PositionCardTarget(
            negotiation_side=NegotiationSide.LISTING,
            anchor_id=51,
            source=SourceIdentity(
                data_version=4,
                interaction_count=1,
                last_interaction_at=LOG_AT,
                max_interaction_id=11,
            ),
        ),
    )
    with pytest.raises(PositionCardContractError, match="different source identity"):
        validate_generation_result(request, other_source)


def test_a_hard_deadline_must_match_the_backend_date_signal() -> None:
    request = listing_request()
    invented = result_for(
        request,
        analysis=analysis(
            timing=TimingAssessment(
                constraints=(
                    PositionCondition(description="임의 조건", evidence=(inference_evidence(),)),
                ),
                hard_deadline=date(2099, 1, 1),
            )
        ),
    )

    with pytest.raises(PositionCardContractError, match="backend date signal"):
        validate_generation_result(request, invented)


def test_the_requirement_side_uses_the_budget_price_kind() -> None:
    request = PositionCardGenerationRequest(
        negotiation_side=NegotiationSide.REQUIREMENT,
        anchor_id=91,
        source=source(),
        anchor=requirement_anchor(),  # pyright: ignore[reportArgumentType]
        date_signals=signals(),
        consultation_logs=(log(),),
    )
    result = result_for(
        request,
        target=PositionCardTarget.from_request(request),
        analysis=analysis(
            price=(
                PriceAssessment(
                    price_kind=PriceKind.BUDGET,
                    stated_amount=2_850_000_000,
                    estimated_amount=3_000_000_000,
                    basis=(quote_evidence(text=QUOTE),),
                ),
            )
        ),
    )

    validate_generation_result(request, result)


# --- 직렬화와 진단 -------------------------------------------------------------


def test_result_survives_a_json_round_trip() -> None:
    request = listing_request()
    original = result_for(
        request,
        analysis=analysis(
            timing=TimingAssessment(
                constraints=(
                    PositionCondition(
                        description="임대차 만기 전 명도", evidence=(quote_evidence(),)
                    ),
                ),
                hard_deadline=date(2026, 11, 30),
            ),
            flexible=(
                PositionCondition(description="잔금일 조정", evidence=(inference_evidence(),)),
            ),
        ),
        prompt_version="listing-delegate:2026-08-20",
        workflow_version="position-card:2026-08-20",
    )

    restored = PositionCardGenerationResult.model_validate_json(original.model_dump_json())

    assert restored == original
    assert restored.analysis.intent.value is NegotiationIntent.PRESENT
    assert restored.analysis.timing.hard_deadline == date(2026, 11, 30)
    assert restored.analysis.price[0].stated_amount == 2_880_000_000
    assert isinstance(restored.analysis.flexible, tuple)
    validate_generation_result(request, restored)


def test_diagnostics_carry_no_prompt_or_raw_response() -> None:
    fields = set(ProviderDiagnostics.model_fields)

    assert fields == {"provider", "model", "request_id", "latency_ms", "usage"}
    assert not fields & {"prompt", "messages", "response", "raw_response", "completion"}


def test_result_carries_no_execution_control_or_personal_fields() -> None:
    request_fields = set(PositionCardGenerationRequest.model_fields)
    result_fields = set(PositionCardGenerationResult.model_fields)
    forbidden = {
        "run_id",
        "lease_owner",
        "lease_expires_at",
        "attempt_count",
        "requested_by",
        "brokerage_id",
        "cache_key",
        "generated_at",
    }

    assert not request_fields & forbidden
    assert not result_fields & forbidden


# --- Protocol -----------------------------------------------------------------


async def test_a_fake_generator_satisfies_the_protocol_without_any_sdk() -> None:
    """Backend 는 Provider SDK 나 LangGraph 없이 이 계약만으로 테스트를 쓸 수 있어야 한다."""

    class FakeGenerator:
        def __init__(self) -> None:
            self.seen: list[PositionCardGenerationRequest] = []

        async def generate_position_card(
            self, request: PositionCardGenerationRequest
        ) -> PositionCardGenerationResult:
            self.seen.append(request)
            return result_for(
                request,
                diagnostics=ProviderDiagnostics(
                    provider=ProviderKind.OPENAI, model="fake", latency_ms=1.0
                ),
            )

    generator: PositionCardGenerator = FakeGenerator()
    request = listing_request()

    produced = await generator.generate_position_card(request)

    assert produced.target == PositionCardTarget.from_request(request)
    validate_generation_result(request, produced)
