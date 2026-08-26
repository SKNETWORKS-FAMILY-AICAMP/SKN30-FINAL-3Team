"""모델 입력 지문의 결정성 검증.

지문이 흔들리면 캐시가 무의미해지거나(같은 입력이 매번 miss) 변경을 놓친다(다른 입력이
같은 지문). 둘 다 조용히 틀린 카드를 만든다.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from brokerage_ai.f3 import (
    ConsultationLogInput,
    DateSignals,
    InputPrivacyMode,
    ListingAnchorContext,
    NegotiationSide,
    PartyRoleContext,
    PositionCardGenerationRequest,
    RequirementAnchorContext,
    SourceIdentity,
)

from domain.agent_execution.fingerprint import (
    INPUT_FINGERPRINT_SCHEMA_VERSION,
    as_of_bucket,
    input_fingerprint,
)

AS_OF = datetime(2026, 8, 20, 1, 0, tzinfo=UTC)
LOG_AT = datetime(2026, 8, 19, 4, 0, tzinfo=UTC)


def log(interaction_id: int = 11) -> ConsultationLogInput:
    return ConsultationLogInput(
        interaction_id=interaction_id,
        interaction_at=LOG_AT,
        channel="CALL",
        counterparty_role="OWNER",
        masked_content="*** 통화. 급하지 않습니다.",
    )


def listing_request(**anchor_overrides: object) -> PositionCardGenerationRequest:
    values: dict[str, object] = {
        "listing_id": 51,
        "unit_id": 7,
        "listing_status": "RECEIVED",
        "is_sale_available": True,
        "sale_price": 2_880_000_000,
        "unit_number": "1801",
        "complex_name": "검증단지",
        "pyeong": Decimal("34.00"),
        "tenancy_expiry_date": date(2026, 11, 30),
        "party_roles": (
            PartyRoleContext(role="OWNER", is_primary=True, is_co_owner=False),
            PartyRoleContext(role="TENANT", is_primary=False, is_co_owner=False),
        ),
    }
    values.update(anchor_overrides)
    return PositionCardGenerationRequest(
        input_privacy_mode=InputPrivacyMode.SYNTHETIC_PROTOTYPE,
        negotiation_side=NegotiationSide.LISTING,
        anchor_id=51,
        target_label="검증단지 1801호",
        source=SourceIdentity(
            data_version=3, interaction_count=1, last_interaction_at=LOG_AT, max_interaction_id=11
        ),
        anchor=ListingAnchorContext(**values),  # pyright: ignore[reportArgumentType]
        date_signals=DateSignals(
            as_of=AS_OF,
            days_until_tenancy_expiry=102,
            hard_deadline_candidate=date(2026, 11, 30),
        ),
        consultation_logs=(log(),),
    )


def test_the_same_input_always_gives_the_same_fingerprint() -> None:
    assert input_fingerprint(listing_request()) == input_fingerprint(listing_request())
    assert input_fingerprint(listing_request()).startswith(f"{INPUT_FINGERPRINT_SCHEMA_VERSION}:")


def test_the_order_of_an_unordered_relation_set_does_not_matter() -> None:
    """당사자 역할은 집합이다. 조회 순서가 달라져도 같은 입력이다."""
    owner = PartyRoleContext(role="OWNER", is_primary=True, is_co_owner=False)
    tenant = PartyRoleContext(role="TENANT", is_primary=False, is_co_owner=False)

    forward = listing_request(party_roles=(owner, tenant))
    backward = listing_request(party_roles=(tenant, owner))

    assert input_fingerprint(forward) == input_fingerprint(backward)


def test_a_changed_party_role_changes_the_fingerprint() -> None:
    changed = listing_request(
        party_roles=(
            PartyRoleContext(role="OWNER", is_primary=True, is_co_owner=True),
            PartyRoleContext(role="TENANT", is_primary=False, is_co_owner=False),
        )
    )

    assert input_fingerprint(changed) != input_fingerprint(listing_request())


@pytest.mark.parametrize(
    "anchor_change",
    [
        {"complex_name": "다른단지"},
        {"unit_number": "1802"},
        {"sale_price": 2_700_000_000},
        {"tenancy_status": "임대차 있음"},
        {"pyeong": Decimal("25.00")},
        {"handover_condition": "즉시 명도"},
    ],
    ids=["단지명", "호수", "매매가", "임대차상태", "평형", "인도조건"],
)
def test_any_model_input_field_change_changes_the_fingerprint(
    anchor_change: dict[str, object],
) -> None:
    assert input_fingerprint(listing_request(**anchor_change)) != input_fingerprint(
        listing_request()
    )


def test_a_changed_consultation_log_changes_the_fingerprint() -> None:
    base = listing_request()
    other = base.model_copy(update={"consultation_logs": (log(interaction_id=11),)})
    assert input_fingerprint(other) == input_fingerprint(base)

    masked = ConsultationLogInput(
        interaction_id=11,
        interaction_at=LOG_AT,
        channel="CALL",
        counterparty_role="OWNER",
        masked_content="*** 통화. 이번 달 안에 정리하고 싶습니다.",
    )
    changed = base.model_copy(update={"consultation_logs": (masked,)})
    assert input_fingerprint(changed) != input_fingerprint(base)


def test_the_same_instant_in_another_timezone_keeps_the_bucket() -> None:
    """UTC 기준 같은 날이면 표기 시간대가 달라도 같은 bucket 이다."""
    elsewhere = AS_OF.astimezone(timezone(timedelta(hours=9)))
    request = listing_request()
    shifted = request.model_copy(
        update={"date_signals": request.date_signals.model_copy(update={"as_of": elsewhere})}
    )

    assert as_of_bucket(shifted) == as_of_bucket(request) == "2026-08-20"
    assert input_fingerprint(shifted) == input_fingerprint(request)


def test_a_different_instant_on_the_same_day_keeps_the_fingerprint() -> None:
    """같은 날 안의 시각 차이까지 지문에 넣으면 모든 실행이 cache miss 가 된다."""
    request = listing_request()
    later = request.model_copy(
        update={
            "date_signals": request.date_signals.model_copy(
                update={"as_of": AS_OF + timedelta(hours=6)}
            )
        }
    )

    assert input_fingerprint(later) == input_fingerprint(request)


def test_a_new_day_changes_the_fingerprint() -> None:
    request = listing_request()
    tomorrow = request.model_copy(
        update={
            "date_signals": request.date_signals.model_copy(
                update={"as_of": AS_OF + timedelta(days=1), "days_until_tenancy_expiry": 101}
            )
        }
    )

    assert as_of_bucket(tomorrow) == "2026-08-21"
    assert input_fingerprint(tomorrow) != input_fingerprint(request)


def test_the_fingerprint_is_a_digest_and_leaks_no_content() -> None:
    """지문은 digest 다. 상담 원문이나 라벨이 그대로 들어가면 저장·로그로 새어 나간다."""
    request = listing_request()

    fingerprint = input_fingerprint(request)

    digest = fingerprint.rsplit(":", 1)[1]
    assert len(digest) == 64
    assert all(character in "0123456789abcdef" for character in digest)
    for secret in ("급하지 않습니다", "검증단지", "1801"):
        assert secret not in fingerprint


def test_the_requirement_side_is_also_deterministic() -> None:
    def requirement_request(**overrides: object) -> PositionCardGenerationRequest:
        values: dict[str, object] = {
            "requirement_id": 91,
            "demand_type": "매수",
            "status": "ACTIVE",
            "max_budget_amount": 2_850_000_000,
            "desired_complex_names": ("가단지", "나단지"),
        }
        values.update(overrides)
        return PositionCardGenerationRequest(
            input_privacy_mode=InputPrivacyMode.SYNTHETIC_PROTOTYPE,
            negotiation_side=NegotiationSide.REQUIREMENT,
            anchor_id=91,
            target_label="구입장 #91",
            source=SourceIdentity(data_version=1, interaction_count=0),
            anchor=RequirementAnchorContext(**values),  # pyright: ignore[reportArgumentType]
            date_signals=DateSignals(as_of=AS_OF),
        )

    assert input_fingerprint(requirement_request()) == input_fingerprint(requirement_request())
    assert input_fingerprint(
        requirement_request(max_budget_amount=3_000_000_000)
    ) != input_fingerprint(requirement_request())
    # 희망 단지는 선호 순서가 의미를 갖는다. 순서가 바뀌면 다른 입력이다.
    assert input_fingerprint(
        requirement_request(desired_complex_names=("나단지", "가단지"))
    ) != input_fingerprint(requirement_request())
