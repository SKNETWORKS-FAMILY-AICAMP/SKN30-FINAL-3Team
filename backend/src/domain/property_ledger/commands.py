from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlmodel import Session, col, delete, select

from core.config import AppEnvironment, Config
from core.errors import ConfigurationError
from domain.property_ledger.models import (
    ClientInteraction,
    Party,
    PartyContact,
    PropertyComplex,
    PropertyListing,
    PropertyRequirement,
    PropertyRequirementComplex,
    PropertyUnit,
    PropertyUnitPartyRelation,
)

# 연락처와 이름은 실제 값을 쓰지 않는다. 개인정보 정책에 따라 명백한 예시 값만 둔다.
SAMPLE_PHONE_PREFIX = "010-0000-"


def require_local(config: Config) -> None:
    if config.app.environment is not AppEnvironment.LOCAL:
        raise ConfigurationError("sample ledger data can only be seeded in local environment")


def clear_sample_ledger(db: Session, brokerage_id: int) -> None:
    """해당 사무소의 장부 데이터를 지운다. 참조 순서를 거슬러 삭제한다."""
    db.execute(delete(ClientInteraction).where(col(ClientInteraction.brokerage_id) == brokerage_id))
    db.execute(
        delete(PropertyRequirementComplex).where(
            col(PropertyRequirementComplex.brokerage_id) == brokerage_id
        )
    )
    db.execute(
        delete(PropertyRequirement).where(col(PropertyRequirement.brokerage_id) == brokerage_id)
    )
    db.execute(
        delete(PropertyUnitPartyRelation).where(
            col(PropertyUnitPartyRelation.brokerage_id) == brokerage_id
        )
    )
    db.execute(delete(PropertyListing).where(col(PropertyListing.brokerage_id) == brokerage_id))
    db.execute(delete(PropertyUnit).where(col(PropertyUnit.brokerage_id) == brokerage_id))
    db.execute(delete(PartyContact).where(col(PartyContact.brokerage_id) == brokerage_id))
    db.execute(delete(Party).where(col(Party.brokerage_id) == brokerage_id))
    db.execute(delete(PropertyComplex).where(col(PropertyComplex.brokerage_id) == brokerage_id))
    db.flush()


def has_sample_ledger(db: Session, brokerage_id: int) -> bool:
    statement = select(PropertyComplex.id).where(col(PropertyComplex.brokerage_id) == brokerage_id)
    return db.execute(statement).first() is not None


def seed_sample_ledger(
    db: Session, config: Config, brokerage_id: int, user_id: int
) -> dict[str, int]:
    """F1 요구사항의 실제 표기를 반영한 예시 장부를 만든다."""
    require_local(config)

    now = datetime.now(UTC)
    counts = {"complexes": 0, "units": 0, "listings": 0, "parties": 0, "requirements": 0, "logs": 0}

    apartment = PropertyComplex(
        brokerage_id=brokerage_id,
        name="한강래미안",
        property_type="APARTMENT",
        road_address="서울특별시 예시구 예시로 100",
    )
    officetel = PropertyComplex(
        brokerage_id=brokerage_id,
        name="역삼푸르지오",
        property_type="OFFICETEL",
        road_address="서울특별시 예시구 예시로 200",
    )
    db.add(apartment)
    db.add(officetel)
    db.flush()
    counts["complexes"] = 2

    # 매물이 아닌 세대가 다수인 것이 정상이다 (F1-GR-01).
    units = [
        PropertyUnit(
            brokerage_id=brokerage_id,
            complex_id=apartment.id or 0,
            building_number="101",
            unit_number="1201",
            floor_number="12",
            orientation="남",
            unit_type="J1",
            pyeong=Decimal("33.45"),
            exclusive_area_sqm=Decimal("110.58"),
            tenancy_status="입주",
            current_deposit_amount=945_000_000,
            tenancy_expiry_date=date(2027, 7, 26),
            tenancy_raw_text="만=27, 기=07, 일=26",
            is_expanded=True,
            built_in_features="에5",
            facility_condition="수납장",
            assigned_user_id=user_id,
        ),
        PropertyUnit(
            brokerage_id=brokerage_id,
            complex_id=apartment.id or 0,
            building_number="101",
            unit_number="902",
            floor_number="9",
            orientation="남남동",
            unit_type="J2",
            pyeong=Decimal("25.70"),
            tenancy_status="경신",
            current_deposit_amount=2_150_000_000,
            tenancy_expiry_date=date(2026, 11, 30),
            is_expanded=False,
        ),
        PropertyUnit(
            brokerage_id=brokerage_id,
            complex_id=apartment.id or 0,
            building_number="102",
            unit_number="501",
            floor_number="5",
            pyeong=Decimal("33.45"),
            unit_type="J1",
        ),
        PropertyUnit(
            brokerage_id=brokerage_id,
            complex_id=apartment.id or 0,
            building_number="102",
            unit_number="1802",
            floor_number="18",
            pyeong=Decimal("44.20"),
        ),
        PropertyUnit(
            brokerage_id=brokerage_id,
            complex_id=officetel.id or 0,
            unit_number="203",
            floor_number="2",
            pyeong=Decimal("18.10"),
            tenancy_status="월환",
            current_deposit_amount=50_000_000,
            current_monthly_rent_amount=3_800_000,
            tenancy_raw_text="5000/380",
        ),
    ]
    for unit in units:
        db.add(unit)
    db.flush()
    counts["units"] = len(units)

    listings = [
        PropertyListing(
            brokerage_id=brokerage_id,
            unit_id=units[0].id or 0,
            received_at=date(2026, 8, 10),
            status="RECEIVED",
            is_sale_available=True,
            sale_price=2_880_000_000,
            price_raw_text="28,8",
            handover_condition="협의",
            assigned_user_id=user_id,
        ),
        PropertyListing(
            brokerage_id=brokerage_id,
            unit_id=units[0].id or 0,
            received_at=date(2023, 5, 1),
            status="CLOSED",
            is_jeonse_available=True,
            jeonse_deposit_amount=1_800_000_000,
            price_raw_text="18억",
            handover_condition="만기후",
        ),
        PropertyListing(
            brokerage_id=brokerage_id,
            unit_id=units[1].id or 0,
            received_at=date(2026, 8, 14),
            status="RECEIVED",
            is_jeonse_available=True,
            jeonse_deposit_amount=2_150_000_000,
            price_raw_text="21,5",
            handover_condition="즉시",
        ),
        PropertyListing(
            brokerage_id=brokerage_id,
            unit_id=units[4].id or 0,
            received_at=date(2026, 8, 16),
            status="RECEIVED",
            is_monthly_rent_available=True,
            monthly_rent_deposit_amount=50_000_000,
            monthly_rent_amount=3_800_000,
            price_raw_text="5000/380",
        ),
    ]
    for listing in listings:
        db.add(listing)
    db.flush()
    counts["listings"] = len(listings)

    # 공동명의 임대인 2인은 세대당 1행으로 접어 표시한다 (F1-GR-06).
    landlord_first = Party(brokerage_id=brokerage_id, party_type="PERSON", name="예시임대인일")
    landlord_second = Party(brokerage_id=brokerage_id, party_type="PERSON", name="예시임대인이")
    tenant = Party(brokerage_id=brokerage_id, party_type="PERSON", name="예시임차인")
    buyer_consented = Party(
        brokerage_id=brokerage_id,
        party_type="PERSON",
        name="인천사모님",
        alternate_name="30억이하 엄마",
        privacy_consent_at=now,
        privacy_consent_by=user_id,
    )
    buyer_without_consent = Party(
        brokerage_id=brokerage_id, party_type="PERSON", name="414동세입자"
    )
    co_broker = Party(brokerage_id=brokerage_id, party_type="ORGANIZATION", name="예시공인중개사")
    parties = [
        landlord_first,
        landlord_second,
        tenant,
        buyer_consented,
        buyer_without_consent,
        co_broker,
    ]
    for party in parties:
        db.add(party)
    db.flush()
    counts["parties"] = len(parties)

    for index, party in enumerate(parties, start=1):
        db.add(
            PartyContact(
                brokerage_id=brokerage_id,
                party_id=party.id or 0,
                contact_method="PHONE",
                contact_value=f"{SAMPLE_PHONE_PREFIX}{index:04d}",
                normalized_contact_value=f"01000000{index:04d}",
                is_primary=True,
            )
        )

    relations = [
        (units[0].id or 0, landlord_first.id or 0, "LANDLORD", 1, True, True),
        (units[0].id or 0, landlord_second.id or 0, "LANDLORD", 2, False, True),
        (units[0].id or 0, tenant.id or 0, "TENANT", 1, True, False),
        (units[1].id or 0, landlord_first.id or 0, "LANDLORD", 1, True, False),
    ]
    for unit_id, party_id, role, role_index, is_primary, is_co_owner in relations:
        db.add(
            PropertyUnitPartyRelation(
                brokerage_id=brokerage_id,
                unit_id=unit_id,
                party_id=party_id,
                role=role,
                role_index=role_index,
                is_primary=is_primary,
                is_co_owner=is_co_owner,
                valid_from=date(2024, 3, 1),
            )
        )
    db.flush()

    requirement = PropertyRequirement(
        brokerage_id=brokerage_id,
        party_id=buyer_consented.id or 0,
        received_at=date(2026, 8, 12),
        demand_type="매수",
        desired_pyeongs=[Decimal("25"), Decimal("33")],
        min_budget_amount=2_500_000_000,
        max_budget_amount=2_880_000_000,
        budget_raw_text="28억선",
        desired_move_in_date=date(2027, 1, 15),
        move_in_date_raw_text="1월중",
        current_tenancy_expiry_date=date(2026, 12, 31),
        co_broker_party_id=co_broker.id or 0,
        classification="일반",
        workflow_stage="방문예정",
        status="ACTIVE",
        assigned_user_id=user_id,
        last_contact_at=now,
    )
    db.add(requirement)
    db.flush()
    db.add(
        PropertyRequirementComplex(
            brokerage_id=brokerage_id,
            requirement_id=requirement.id or 0,
            complex_id=apartment.id or 0,
            preference_order=1,
        )
    )
    counts["requirements"] = 1

    logs = [
        ClientInteraction(
            brokerage_id=brokerage_id,
            interaction_at=now,
            interaction_channel="CALL",
            communication_direction="OUTBOUND",
            interaction_result="CONNECTED",
            counterparty_role="LANDLORD",
            counterparty_index=1,
            interaction_content="매도 희망가 확인. 28억 8천에서 조정 여지 있음.",
            unit_id=units[0].id or 0,
            listing_id=listings[0].id or 0,
            party_id=landlord_first.id or 0,
            created_by=user_id,
        ),
        ClientInteraction(
            brokerage_id=brokerage_id,
            interaction_at=now,
            interaction_channel="CALL",
            communication_direction="INBOUND",
            interaction_result="CONNECTED",
            interaction_content="예산 상향 가능. 1월 이사 희망 유지.",
            requirement_id=requirement.id or 0,
            party_id=buyer_consented.id or 0,
            created_by=user_id,
        ),
    ]
    for log in logs:
        db.add(log)
    db.flush()
    counts["logs"] = len(logs)

    units[0].last_contact_at = now
    db.add(units[0])
    db.commit()
    return counts
