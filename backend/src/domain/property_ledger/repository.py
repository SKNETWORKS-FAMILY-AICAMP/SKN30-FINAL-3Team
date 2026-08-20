from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import ColumnElement, CursorResult, Select, func, or_, select, true, update
from sqlalchemy.orm import aliased
from sqlmodel import Session, col

from core.errors import ValidationError
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

EMPTY_VALUE = "__EMPTY__"


@dataclass(frozen=True)
class Page:
    limit: int
    offset: int


@dataclass(frozen=True)
class PropertyUnitFilters:
    complex_id: Sequence[str] = field(default_factory=tuple)
    building_number: Sequence[str] = field(default_factory=tuple)
    unit_number: Sequence[str] = field(default_factory=tuple)
    floor_number: Sequence[str] = field(default_factory=tuple)
    orientation: Sequence[str] = field(default_factory=tuple)
    tenancy_status: Sequence[str] = field(default_factory=tuple)
    lifecycle_status: Sequence[str] = field(default_factory=tuple)
    unit_type: Sequence[str] = field(default_factory=tuple)
    assigned_user_id: Sequence[str] = field(default_factory=tuple)
    listing_status: Sequence[str] = field(default_factory=tuple)
    handover_condition: Sequence[str] = field(default_factory=tuple)
    is_expanded: bool | None = None
    is_sale_available: bool | None = None
    is_jeonse_available: bool | None = None
    is_monthly_rent_available: bool | None = None


@dataclass(frozen=True)
class PropertyRequirementFilters:
    demand_type: Sequence[str] = field(default_factory=tuple)
    status: Sequence[str] = field(default_factory=tuple)
    classification: Sequence[str] = field(default_factory=tuple)
    workflow_stage: Sequence[str] = field(default_factory=tuple)
    assigned_user_id: Sequence[str] = field(default_factory=tuple)


def coerce_values(column: Any, values: Sequence[str]) -> list[Any]:
    """쿼리 문자열을 컬럼의 실제 타입으로 바꾼다. 정수 컬럼에 문자열을 넘기면 DB가 거절한다."""
    try:
        python_type = column.type.python_type
    except NotImplementedError:
        return list(values)
    if python_type is int:
        try:
            return [int(value) for value in values]
        except ValueError as error:
            raise ValidationError(f"{column.key} filter accepts integers only") from error
    if python_type is bool:
        return [value.lower() in {"true", "1"} for value in values]
    return list(values)


def value_condition(column: Any, values: Sequence[str]) -> ColumnElement[bool] | None:
    """선택된 값들을 OR로 묶는다. 예약값 __EMPTY__는 빈 칸을 뜻한다."""
    if not values:
        return None
    clauses: list[ColumnElement[bool]] = []
    literals = [value for value in values if value != EMPTY_VALUE]
    if literals:
        clauses.append(column.in_(coerce_values(column, literals)))
    if EMPTY_VALUE in values:
        clauses.append(column.is_(None))
    return or_(*clauses)


def latest_listing_alias() -> Any:
    """세대별 가장 최근 접수 매물 1건. 접수일이 같으면 나중에 등록된 건을 쓴다."""
    lateral = (
        select(PropertyListing)
        .where(
            col(PropertyListing.brokerage_id) == PropertyUnit.brokerage_id,
            col(PropertyListing.unit_id) == PropertyUnit.id,
            col(PropertyListing.is_deleted).is_(False),
        )
        .order_by(col(PropertyListing.received_at).desc(), col(PropertyListing.id).desc())
        .limit(1)
        .lateral("latest_listing")
    )
    return aliased(PropertyListing, lateral)


def latest_interaction_alias() -> Any:
    """세대별 가장 최근 상담 로그 1건.

    목록에서 로그 열이 늘 비어 보이지 않도록 lateral로 붙인다. 행마다 별도 질의를 보내면
    한 화면에 수백 건의 요청이 생기므로 join으로 해결한다.
    """
    lateral = (
        select(ClientInteraction)
        .where(
            col(ClientInteraction.brokerage_id) == PropertyUnit.brokerage_id,
            col(ClientInteraction.unit_id) == PropertyUnit.id,
        )
        .order_by(col(ClientInteraction.interaction_at).desc(), col(ClientInteraction.id).desc())
        .limit(1)
        .lateral("latest_interaction")
    )
    return aliased(ClientInteraction, lateral)


def property_unit_conditions(
    brokerage_id: int, filters: PropertyUnitFilters, listing: Any
) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = [
        col(PropertyUnit.brokerage_id) == brokerage_id,
        col(PropertyUnit.is_deleted).is_(False),
    ]
    column_filters: list[tuple[Any, Sequence[str]]] = [
        (col(PropertyUnit.complex_id), filters.complex_id),
        (col(PropertyUnit.building_number), filters.building_number),
        (col(PropertyUnit.unit_number), filters.unit_number),
        (col(PropertyUnit.floor_number), filters.floor_number),
        (col(PropertyUnit.orientation), filters.orientation),
        (col(PropertyUnit.tenancy_status), filters.tenancy_status),
        (col(PropertyUnit.lifecycle_status), filters.lifecycle_status),
        (col(PropertyUnit.unit_type), filters.unit_type),
        (col(PropertyUnit.assigned_user_id), filters.assigned_user_id),
        (listing.status, filters.listing_status),
        (listing.handover_condition, filters.handover_condition),
    ]
    for column, values in column_filters:
        condition = value_condition(column, values)
        if condition is not None:
            conditions.append(condition)

    boolean_filters: list[tuple[Any, bool | None]] = [
        (col(PropertyUnit.is_expanded), filters.is_expanded),
        (listing.is_sale_available, filters.is_sale_available),
        (listing.is_jeonse_available, filters.is_jeonse_available),
        (listing.is_monthly_rent_available, filters.is_monthly_rent_available),
    ]
    for column, expected in boolean_filters:
        if expected is not None:
            conditions.append(column.is_(expected))
    return conditions


def property_unit_query(brokerage_id: int, filters: PropertyUnitFilters) -> tuple[Select[Any], Any]:
    listing = latest_listing_alias()
    interaction = latest_interaction_alias()
    statement = (
        select(PropertyUnit, PropertyComplex, listing, interaction)
        .join(
            PropertyComplex,
            (col(PropertyComplex.brokerage_id) == PropertyUnit.brokerage_id)
            & (col(PropertyComplex.id) == PropertyUnit.complex_id),
        )
        .outerjoin(listing, true())
        .outerjoin(interaction, true())
        .where(*property_unit_conditions(brokerage_id, filters, listing))
    )
    return statement, listing


def count_property_units(session: Session, brokerage_id: int, filters: PropertyUnitFilters) -> int:
    statement, _ = property_unit_query(brokerage_id, filters)
    total = session.execute(select(func.count()).select_from(statement.subquery())).scalar_one()
    return int(total)


def list_property_units(
    session: Session, brokerage_id: int, filters: PropertyUnitFilters, page: Page
) -> list[Any]:
    statement, _ = property_unit_query(brokerage_id, filters)
    statement = (
        statement.order_by(
            col(PropertyUnit.building_number).asc().nullsfirst(),
            col(PropertyUnit.unit_number).asc(),
            col(PropertyUnit.id).asc(),
        )
        .limit(page.limit)
        .offset(page.offset)
    )
    return list(session.execute(statement).all())


def property_unit_column_values(
    session: Session, brokerage_id: int, filters: PropertyUnitFilters, column_name: str
) -> list[tuple[str, int]]:
    statement, listing = property_unit_query(brokerage_id, filters)
    columns: dict[str, Any] = {
        "building_number": col(PropertyUnit.building_number),
        "unit_number": col(PropertyUnit.unit_number),
        "floor_number": col(PropertyUnit.floor_number),
        "orientation": col(PropertyUnit.orientation),
        "tenancy_status": col(PropertyUnit.tenancy_status),
        "lifecycle_status": col(PropertyUnit.lifecycle_status),
        "unit_type": col(PropertyUnit.unit_type),
        "listing_status": listing.status,
        "handover_condition": listing.handover_condition,
    }
    target = columns[column_name]
    subquery = statement.with_only_columns(target.label("value")).subquery()
    grouped = (
        select(subquery.c.value, func.count().label("count"))
        .group_by(subquery.c.value)
        .order_by(subquery.c.value.asc().nullsfirst())
    )
    return [
        (EMPTY_VALUE if value is None else str(value), int(count))
        for value, count in session.execute(grouped).all()
    ]


def supported_unit_columns() -> list[str]:
    return [
        "building_number",
        "unit_number",
        "floor_number",
        "orientation",
        "tenancy_status",
        "lifecycle_status",
        "unit_type",
        "listing_status",
        "handover_condition",
    ]


def find_property_unit(
    session: Session, brokerage_id: int, unit_id: int
) -> tuple[PropertyUnit, PropertyComplex] | None:
    statement = (
        select(PropertyUnit, PropertyComplex)
        .join(
            PropertyComplex,
            (col(PropertyComplex.brokerage_id) == PropertyUnit.brokerage_id)
            & (col(PropertyComplex.id) == PropertyUnit.complex_id),
        )
        .where(
            col(PropertyUnit.brokerage_id) == brokerage_id,
            col(PropertyUnit.id) == unit_id,
            col(PropertyUnit.is_deleted).is_(False),
        )
    )
    row = session.execute(statement).first()
    return (row[0], row[1]) if row else None


def find_property_complex(
    session: Session, brokerage_id: int, complex_id: int
) -> PropertyComplex | None:
    statement = select(PropertyComplex).where(
        col(PropertyComplex.brokerage_id) == brokerage_id,
        col(PropertyComplex.id) == complex_id,
        col(PropertyComplex.is_deleted).is_(False),
    )
    return session.execute(statement).scalars().first()


def count_property_complexes(session: Session, brokerage_id: int) -> int:
    statement = select(func.count()).select_from(PropertyComplex).where(
        col(PropertyComplex.brokerage_id) == brokerage_id,
        col(PropertyComplex.is_deleted).is_(False),
    )
    return int(session.execute(statement).scalar_one())


def list_property_complexes(
    session: Session, brokerage_id: int, page: Page
) -> list[PropertyComplex]:
    statement = (
        select(PropertyComplex)
        .where(
            col(PropertyComplex.brokerage_id) == brokerage_id,
            col(PropertyComplex.is_deleted).is_(False),
        )
        .order_by(col(PropertyComplex.name))
        .limit(page.limit)
        .offset(page.offset)
    )
    return list(session.execute(statement).scalars().all())


def count_units_in_complex(session: Session, brokerage_id: int, complex_id: int) -> int:
    """단지에 남아 있는 세대 수. 삭제를 막을지 판단하는 데 쓴다."""
    statement = select(func.count()).select_from(PropertyUnit).where(
        col(PropertyUnit.brokerage_id) == brokerage_id,
        col(PropertyUnit.complex_id) == complex_id,
        col(PropertyUnit.is_deleted).is_(False),
    )
    return int(session.execute(statement).scalar_one())


def find_property_complex_by_name(
    session: Session, brokerage_id: int, name: str
) -> PropertyComplex | None:
    """같은 중개사무소 안에서 이름이 겹치는 단지. 중복 등록을 막기 위해 쓴다."""
    statement = select(PropertyComplex).where(
        col(PropertyComplex.brokerage_id) == brokerage_id,
        func.lower(col(PropertyComplex.name)) == name.strip().lower(),
        col(PropertyComplex.is_deleted).is_(False),
    )
    return session.execute(statement).scalars().first()


def list_listings_for_unit(
    session: Session, brokerage_id: int, unit_id: int
) -> list[PropertyListing]:
    statement = (
        select(PropertyListing)
        .where(
            col(PropertyListing.brokerage_id) == brokerage_id,
            col(PropertyListing.unit_id) == unit_id,
            col(PropertyListing.is_deleted).is_(False),
        )
        .order_by(col(PropertyListing.received_at).desc(), col(PropertyListing.id).desc())
    )
    return list(session.execute(statement).scalars().all())


def find_property_listing(
    session: Session, brokerage_id: int, listing_id: int
) -> PropertyListing | None:
    statement = select(PropertyListing).where(
        col(PropertyListing.brokerage_id) == brokerage_id,
        col(PropertyListing.id) == listing_id,
        col(PropertyListing.is_deleted).is_(False),
    )
    return session.execute(statement).scalars().first()


def list_unit_party_relations(
    session: Session, brokerage_id: int, unit_id: int
) -> list[tuple[PropertyUnitPartyRelation, Party]]:
    statement = (
        select(PropertyUnitPartyRelation, Party)
        .join(
            Party,
            (col(Party.brokerage_id) == PropertyUnitPartyRelation.brokerage_id)
            & (col(Party.id) == PropertyUnitPartyRelation.party_id),
        )
        .where(
            col(PropertyUnitPartyRelation.brokerage_id) == brokerage_id,
            col(PropertyUnitPartyRelation.unit_id) == unit_id,
            col(PropertyUnitPartyRelation.valid_to).is_(None),
        )
        .order_by(
            col(PropertyUnitPartyRelation.role).asc(),
            col(PropertyUnitPartyRelation.role_index).asc(),
        )
    )
    return [(row[0], row[1]) for row in session.execute(statement).all()]


def list_party_contacts(
    session: Session, brokerage_id: int, party_ids: Sequence[int]
) -> list[PartyContact]:
    if not party_ids:
        return []
    statement = (
        select(PartyContact)
        .where(
            col(PartyContact.brokerage_id) == brokerage_id,
            col(PartyContact.party_id).in_(list(party_ids)),
            col(PartyContact.is_deleted).is_(False),
        )
        .order_by(col(PartyContact.party_id).asc(), col(PartyContact.is_primary).desc())
    )
    return list(session.execute(statement).scalars().all())


def find_party(session: Session, brokerage_id: int, party_id: int) -> Party | None:
    statement = select(Party).where(
        col(Party.brokerage_id) == brokerage_id,
        col(Party.id) == party_id,
        col(Party.is_deleted).is_(False),
    )
    return session.execute(statement).scalars().first()


def property_requirement_conditions(
    brokerage_id: int, filters: PropertyRequirementFilters
) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = [
        col(PropertyRequirement.brokerage_id) == brokerage_id,
        col(PropertyRequirement.is_deleted).is_(False),
    ]
    column_filters: list[tuple[Any, Sequence[str]]] = [
        (col(PropertyRequirement.demand_type), filters.demand_type),
        (col(PropertyRequirement.status), filters.status),
        (col(PropertyRequirement.classification), filters.classification),
        (col(PropertyRequirement.workflow_stage), filters.workflow_stage),
        (col(PropertyRequirement.assigned_user_id), filters.assigned_user_id),
    ]
    for column, values in column_filters:
        condition = value_condition(column, values)
        if condition is not None:
            conditions.append(condition)
    return conditions


def property_requirement_query(
    brokerage_id: int, filters: PropertyRequirementFilters
) -> Select[Any]:
    return (
        select(PropertyRequirement, Party)
        .join(
            Party,
            (col(Party.brokerage_id) == PropertyRequirement.brokerage_id)
            & (col(Party.id) == PropertyRequirement.party_id),
        )
        .where(*property_requirement_conditions(brokerage_id, filters))
    )


def count_property_requirements(
    session: Session, brokerage_id: int, filters: PropertyRequirementFilters
) -> int:
    statement = property_requirement_query(brokerage_id, filters)
    total = session.execute(select(func.count()).select_from(statement.subquery())).scalar_one()
    return int(total)


def list_property_requirements(
    session: Session, brokerage_id: int, filters: PropertyRequirementFilters, page: Page
) -> list[Any]:
    statement = (
        property_requirement_query(brokerage_id, filters)
        .order_by(
            col(PropertyRequirement.last_contact_at).desc().nullslast(),
            col(PropertyRequirement.id).desc(),
        )
        .limit(page.limit)
        .offset(page.offset)
    )
    return list(session.execute(statement).all())


def property_requirement_column_values(
    session: Session, brokerage_id: int, filters: PropertyRequirementFilters, column_name: str
) -> list[tuple[str, int]]:
    statement = property_requirement_query(brokerage_id, filters)
    columns: dict[str, Any] = {
        "demand_type": col(PropertyRequirement.demand_type),
        "status": col(PropertyRequirement.status),
        "classification": col(PropertyRequirement.classification),
        "workflow_stage": col(PropertyRequirement.workflow_stage),
    }
    target = columns[column_name]
    subquery = statement.with_only_columns(target.label("value")).subquery()
    grouped = (
        select(subquery.c.value, func.count().label("count"))
        .group_by(subquery.c.value)
        .order_by(subquery.c.value.asc().nullsfirst())
    )
    return [
        (EMPTY_VALUE if value is None else str(value), int(count))
        for value, count in session.execute(grouped).all()
    ]


def supported_requirement_columns() -> list[str]:
    return ["demand_type", "status", "classification", "workflow_stage"]


def find_property_requirement(
    session: Session, brokerage_id: int, requirement_id: int
) -> tuple[PropertyRequirement, Party] | None:
    statement = (
        select(PropertyRequirement, Party)
        .join(
            Party,
            (col(Party.brokerage_id) == PropertyRequirement.brokerage_id)
            & (col(Party.id) == PropertyRequirement.party_id),
        )
        .where(
            col(PropertyRequirement.brokerage_id) == brokerage_id,
            col(PropertyRequirement.id) == requirement_id,
            col(PropertyRequirement.is_deleted).is_(False),
        )
    )
    row = session.execute(statement).first()
    return (row[0], row[1]) if row else None


def list_requirement_complexes(
    session: Session, brokerage_id: int, requirement_id: int
) -> list[tuple[PropertyRequirementComplex, PropertyComplex]]:
    statement = (
        select(PropertyRequirementComplex, PropertyComplex)
        .join(
            PropertyComplex,
            (col(PropertyComplex.brokerage_id) == PropertyRequirementComplex.brokerage_id)
            & (col(PropertyComplex.id) == PropertyRequirementComplex.complex_id),
        )
        .where(
            col(PropertyRequirementComplex.brokerage_id) == brokerage_id,
            col(PropertyRequirementComplex.requirement_id) == requirement_id,
        )
        .order_by(col(PropertyRequirementComplex.preference_order).asc().nullslast())
    )
    return [(row[0], row[1]) for row in session.execute(statement).all()]


def replace_requirement_complexes(
    session: Session, brokerage_id: int, requirement_id: int, complex_ids: Sequence[int]
) -> None:
    existing = list_requirement_complexes(session, brokerage_id, requirement_id)
    for link, _ in existing:
        session.delete(link)
    session.flush()
    for order, complex_id in enumerate(complex_ids, start=1):
        session.add(
            PropertyRequirementComplex(
                brokerage_id=brokerage_id,
                requirement_id=requirement_id,
                complex_id=complex_id,
                preference_order=order,
            )
        )
    session.flush()


def list_client_interactions(
    session: Session,
    brokerage_id: int,
    unit_id: int | None,
    requirement_id: int | None,
    party_id: int | None,
    page: Page,
) -> tuple[list[ClientInteraction], int]:
    conditions: list[ColumnElement[bool]] = [
        col(ClientInteraction.brokerage_id) == brokerage_id,
        col(ClientInteraction.is_voided).is_(False),
    ]
    if unit_id is not None:
        conditions.append(col(ClientInteraction.unit_id) == unit_id)
    if requirement_id is not None:
        conditions.append(col(ClientInteraction.requirement_id) == requirement_id)
    if party_id is not None:
        conditions.append(col(ClientInteraction.party_id) == party_id)

    total = session.execute(
        select(func.count()).select_from(select(ClientInteraction).where(*conditions).subquery())
    ).scalar_one()
    statement = (
        select(ClientInteraction)
        .where(*conditions)
        .order_by(col(ClientInteraction.interaction_at).desc(), col(ClientInteraction.id).desc())
        .limit(page.limit)
        .offset(page.offset)
    )
    return list(session.execute(statement).scalars().all()), int(total)


def touch_last_contact(
    session: Session,
    brokerage_id: int,
    unit_id: int | None,
    requirement_id: int | None,
    contacted_at: datetime,
) -> None:
    """상담 로그 추가 시 대상 원장의 최종접촉일을 갱신한다."""
    if unit_id is not None:
        session.execute(
            update(PropertyUnit)
            .where(
                col(PropertyUnit.brokerage_id) == brokerage_id,
                col(PropertyUnit.id) == unit_id,
            )
            .values(last_contact_at=contacted_at)
        )
    if requirement_id is not None:
        session.execute(
            update(PropertyRequirement)
            .where(
                col(PropertyRequirement.brokerage_id) == brokerage_id,
                col(PropertyRequirement.id) == requirement_id,
            )
            .values(last_contact_at=contacted_at)
        )


def bump_row_version(
    session: Session,
    model: Any,
    brokerage_id: int,
    record_id: int,
    expected_row_version: int,
    values: dict[str, Any],
) -> bool:
    """낙관적 잠금 갱신. 버전이 일치할 때만 1행을 수정하고 True를 돌려준다."""
    statement = (
        update(model)
        .where(
            model.brokerage_id == brokerage_id,
            model.id == record_id,
            model.row_version == expected_row_version,
            model.is_deleted.is_(False),
        )
        .values(
            **values,
            row_version=model.row_version + 1,
            updated_at=datetime.now(UTC),
        )
    )
    result = cast(CursorResult[Any], session.execute(statement))
    return result.rowcount == 1


def find_client_interaction(
    session: Session, brokerage_id: int, interaction_id: int
) -> ClientInteraction | None:
    statement = select(ClientInteraction).where(
        col(ClientInteraction.brokerage_id) == brokerage_id,
        col(ClientInteraction.id) == interaction_id,
    )
    return session.execute(statement).scalars().first()
