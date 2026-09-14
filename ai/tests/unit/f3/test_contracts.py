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
    InferenceEvidence,
    InputPrivacyMode,
    IntentAssessment,
    ListingAnchorContext,
    NegotiationIntent,
    NegotiationSide,
    PositionCardAnalysis,
    PositionCardContractError,
    PositionCardGenerationRequest,
    PositionCardGenerationResult,
    PositionCardGenerator,
    PositionCardGeneratorVersions,
    PositionCardTarget,
    PositionCondition,
    PriceAssessment,
    PriceKind,
    QuoteEvidence,
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
        "input_privacy_mode": InputPrivacyMode.SYNTHETIC_PROTOTYPE,
        "negotiation_side": NegotiationSide.LISTING,
        "anchor_id": 51,
        "target_label": "검증단지 1801호",
        "source": source(),
        "anchor": listing_anchor(),
        "date_signals": signals(),
        "consultation_logs": (log(),),
    }
    values.update(overrides)
    return PositionCardGenerationRequest(**values)  # pyright: ignore[reportArgumentType]


def quote_evidence(interaction_id: int = 11, text: str = QUOTE) -> Evidence:
    return QuoteEvidence(interaction_id=interaction_id, quote_text=text)


def inference_evidence(note: str = "최근 6개월 접촉 이력이 없다") -> Evidence:
    return InferenceEvidence(note=note)


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


def test_input_privacy_mode_is_required() -> None:
    values = listing_request().model_dump()
    values.pop("input_privacy_mode")

    with pytest.raises(ValidationError):
        PositionCardGenerationRequest(**values)


# --- 입력 격리 -----------------------------------------------------------------


def test_listing_request_rejects_a_requirement_context() -> None:
    with pytest.raises(ValidationError):
        listing_request(anchor=requirement_anchor(requirement_id=51))


def test_requirement_request_rejects_a_listing_context() -> None:
    with pytest.raises(ValidationError):
        PositionCardGenerationRequest(
            input_privacy_mode=InputPrivacyMode.SYNTHETIC_PROTOTYPE,
            negotiation_side=NegotiationSide.REQUIREMENT,
            anchor_id=51,
            target_label="구입장 #51",
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


def test_evidence_missing_its_required_field_is_rejected() -> None:
    """필수 필드가 빠지면 거절한다. 예전의 네 가지 조합 검사를 대신한다.

    "INFERENCE 인데 인용을 들고 있다" 같은 잘못된 조합은 이제 타입에 자리가 없어 정적으로도
    거절되므로 실행 시 검사를 남겨 둘 이유가 없다.
    """
    with pytest.raises(ValidationError):
        QuoteEvidence.model_validate({"kind": "QUOTE", "quote_text": QUOTE})
    with pytest.raises(ValidationError):
        QuoteEvidence.model_validate({"kind": "QUOTE", "interaction_id": 11})
    with pytest.raises(ValidationError):
        InferenceEvidence.model_validate({"kind": "INFERENCE"})
    # 선언하지 않은 필드는 받지 않는다 (extra="forbid").
    with pytest.raises(ValidationError):
        InferenceEvidence.model_validate(
            {"kind": "INFERENCE", "note": "추정", "interaction_id": 11}
        )


def test_legacy_evidence_with_null_placeholders_still_revives() -> None:
    """예전 계약으로 저장된 카드가 지금도 읽혀야 한다.

    이전 `Evidence` 는 네 필드를 모두 담고 해당 없는 자리를 `null` 로 저장했다. 판정 단계는
    저장된 `analysis_snapshot` 을 되살려 입력으로 쓰므로, 이 관용이 없으면 기존 카드가 전부
    읽히지 않아 판정이 통째로 막힌다.
    """
    legacy_quote = {"kind": "QUOTE", "interaction_id": 11, "quote_text": QUOTE, "note": None}
    legacy_inference = {
        "kind": "INFERENCE",
        "interaction_id": None,
        "quote_text": None,
        "note": "정황",
    }

    assert QuoteEvidence.model_validate(legacy_quote).quote_text == QUOTE
    assert InferenceEvidence.model_validate(legacy_inference).note == "정황"


def test_legacy_tolerance_does_not_accept_a_value_in_the_wrong_slot() -> None:
    """`null` 자리 표시만 버린다. 값이 들어 있으면 예전에도 지금도 잘못된 근거다."""
    with pytest.raises(ValidationError):
        QuoteEvidence.model_validate(
            {"kind": "QUOTE", "interaction_id": 11, "quote_text": QUOTE, "note": "메모"}
        )
    with pytest.raises(ValidationError):
        InferenceEvidence.model_validate({"kind": "INFERENCE", "note": "정황", "quote_text": QUOTE})


def test_evidence_does_not_expose_quote_offsets() -> None:
    """offset 은 Backend 가 실제 원문에서 계산한다. 모델이 만들 자리가 없어야 한다."""
    for variant in (QuoteEvidence, InferenceEvidence):
        fields = set(variant.model_fields)

        assert "quote_start_offset" not in fields
        assert "quote_end_offset" not in fields


def test_evidence_variants_make_the_wrong_combination_unrepresentable() -> None:
    """종류별 필수 필드를 `model_validator` 가 아니라 타입이 강제한다.

    예전에는 네 필드를 모두 가진 하나의 `Evidence` 에 검증기를 걸었고, 그 규칙은 JSON schema
    로 표현할 수 없어 프롬프트 문장에만 의존했다. 로컬 모델이 `interaction_id` 를 비운 QUOTE
    를 반복해 되먹임 3회로도 못 고친 사례가 있다.
    """
    assert set(QuoteEvidence.model_fields) == {"kind", "interaction_id", "quote_text"}
    assert set(InferenceEvidence.model_fields) == {"kind", "note"}

    # 읽는 쪽은 종류를 나눠 보지 않아도 되도록 자리는 맞춰 둔다.
    assert QuoteEvidence(interaction_id=1, quote_text="원문").note is None
    assert InferenceEvidence(note="정황").interaction_id is None
    assert InferenceEvidence(note="정황").quote_text is None


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
            negotiation_side=NegotiationSide.LISTING,
            anchor_id=52,
            target_label="검증단지 1801호",
            source=source(),
        ),
    )
    with pytest.raises(PositionCardContractError, match="different anchor"):
        validate_generation_result(request, other_target)

    other_source = result_for(
        request,
        target=PositionCardTarget(
            negotiation_side=NegotiationSide.LISTING,
            anchor_id=51,
            target_label="검증단지 1801호",
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
        input_privacy_mode=InputPrivacyMode.SYNTHETIC_PROTOTYPE,
        negotiation_side=NegotiationSide.REQUIREMENT,
        anchor_id=91,
        target_label="구입장 #91",
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

        @property
        def versions(self) -> PositionCardGeneratorVersions:
            return PositionCardGeneratorVersions(
                prompt_version="fake-prompt:v1", workflow_version="fake-workflow:v1"
            )

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


def test_target_label_is_copied_from_the_request_and_cannot_be_changed() -> None:
    """라벨은 Backend 가 F1 구조화 값에서 만든다. 모델이 바꾸면 저장하지 않는다."""
    request = listing_request()

    assert PositionCardTarget.from_request(request).target_label == request.target_label
    validate_generation_result(request, result_for(request))

    tampered = result_for(request)
    tampered = tampered.model_copy(
        update={"target": tampered.target.model_copy(update={"target_label": "다른 라벨"})}
    )
    with pytest.raises(PositionCardContractError, match="target label"):
        validate_generation_result(request, tampered)


def test_a_blank_target_label_is_rejected() -> None:
    with pytest.raises(ValidationError):
        listing_request(target_label="   ")
