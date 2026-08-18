from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

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

MAX_PAGE_SIZE = 500


class PropertyComplexSummary(BaseModel):
    id: int
    name: str
    property_type: str
    road_address: str | None

    @classmethod
    def from_domain(cls, row: PropertyComplex) -> PropertyComplexSummary:
        return cls(
            id=row.id or 0,
            name=row.name,
            property_type=row.property_type,
            road_address=row.road_address,
        )


class PropertyListingResponse(BaseModel):
    id: int
    unit_id: int
    client_party_id: int | None
    received_at: date | None
    status: str
    is_sale_available: bool
    sale_price: int | None
    is_jeonse_available: bool
    jeonse_deposit_amount: int | None
    is_monthly_rent_available: bool
    monthly_rent_deposit_amount: int | None
    monthly_rent_amount: int | None
    price_raw_text: str | None
    handover_condition: str | None
    assigned_user_id: int | None
    memo: str | None
    custom_fields: dict[str, object]
    row_version: int

    @classmethod
    def from_domain(cls, row: PropertyListing) -> PropertyListingResponse:
        return cls(
            id=row.id or 0,
            unit_id=row.unit_id,
            client_party_id=row.client_party_id,
            received_at=row.received_at,
            status=row.status,
            is_sale_available=row.is_sale_available,
            sale_price=row.sale_price,
            is_jeonse_available=row.is_jeonse_available,
            jeonse_deposit_amount=row.jeonse_deposit_amount,
            is_monthly_rent_available=row.is_monthly_rent_available,
            monthly_rent_deposit_amount=row.monthly_rent_deposit_amount,
            monthly_rent_amount=row.monthly_rent_amount,
            price_raw_text=row.price_raw_text,
            handover_condition=row.handover_condition,
            assigned_user_id=row.assigned_user_id,
            memo=row.memo,
            custom_fields=row.custom_fields,
            row_version=row.row_version,
        )


class PropertyUnitRow(BaseModel):
    """매물장 그리드 한 행. 매물이 아닌 세대는 current_listing이 null이다."""

    id: int
    complex: PropertyComplexSummary
    building_number: str | None
    unit_number: str
    floor_number: str | None
    orientation: str | None
    unit_type: str | None
    pyeong: Decimal | None
    exclusive_area_sqm: Decimal | None
    supply_area_sqm: Decimal | None
    tenancy_status: str | None
    current_deposit_amount: int | None
    current_monthly_rent_amount: int | None
    loan_amount: int | None
    tenancy_expiry_date: date | None
    tenancy_raw_text: str | None
    is_expanded: bool | None
    built_in_features: str | None
    facility_condition: str | None
    lifecycle_status: str
    assigned_user_id: int | None
    memo: str | None
    custom_fields: dict[str, object]
    last_contact_at: datetime | None
    row_version: int
    current_listing: PropertyListingResponse | None

    @classmethod
    def from_domain(
        cls,
        unit: PropertyUnit,
        complex_row: PropertyComplex,
        listing: PropertyListing | None,
    ) -> PropertyUnitRow:
        return cls(
            id=unit.id or 0,
            complex=PropertyComplexSummary.from_domain(complex_row),
            building_number=unit.building_number,
            unit_number=unit.unit_number,
            floor_number=unit.floor_number,
            orientation=unit.orientation,
            unit_type=unit.unit_type,
            pyeong=unit.pyeong,
            exclusive_area_sqm=unit.exclusive_area_sqm,
            supply_area_sqm=unit.supply_area_sqm,
            tenancy_status=unit.tenancy_status,
            current_deposit_amount=unit.current_deposit_amount,
            current_monthly_rent_amount=unit.current_monthly_rent_amount,
            loan_amount=unit.loan_amount,
            tenancy_expiry_date=unit.tenancy_expiry_date,
            tenancy_raw_text=unit.tenancy_raw_text,
            is_expanded=unit.is_expanded,
            built_in_features=unit.built_in_features,
            facility_condition=unit.facility_condition,
            lifecycle_status=unit.lifecycle_status,
            assigned_user_id=unit.assigned_user_id,
            memo=unit.memo,
            custom_fields=unit.custom_fields,
            last_contact_at=unit.last_contact_at,
            row_version=unit.row_version,
            current_listing=(
                PropertyListingResponse.from_domain(listing) if listing is not None else None
            ),
        )


class PropertyUnitListResponse(BaseModel):
    items: list[PropertyUnitRow]
    total: int
    limit: int
    offset: int


class PartyContactResponse(BaseModel):
    id: int
    contact_method: str
    contact_value: str
    contact_label: str | None
    is_primary: bool
    contactability_status: str

    @classmethod
    def from_domain(cls, row: PartyContact) -> PartyContactResponse:
        return cls(
            id=row.id or 0,
            contact_method=row.contact_method,
            contact_value=row.contact_value,
            contact_label=row.contact_label,
            is_primary=row.is_primary,
            contactability_status=row.contactability_status,
        )


class PartySummary(BaseModel):
    id: int
    party_type: str
    name: str
    alternate_name: str | None
    privacy_consent_at: datetime | None
    contacts: list[PartyContactResponse]

    @classmethod
    def from_domain(cls, row: Party, contacts: list[PartyContact]) -> PartySummary:
        return cls(
            id=row.id or 0,
            party_type=row.party_type,
            name=row.name,
            alternate_name=row.alternate_name,
            privacy_consent_at=row.privacy_consent_at,
            contacts=[PartyContactResponse.from_domain(contact) for contact in contacts],
        )


class UnitPartyRelationResponse(BaseModel):
    role: str
    role_index: int
    is_primary: bool
    is_co_owner: bool
    valid_from: date | None
    party: PartySummary

    @classmethod
    def from_domain(
        cls,
        relation: PropertyUnitPartyRelation,
        party: Party,
        contacts: list[PartyContact],
    ) -> UnitPartyRelationResponse:
        return cls(
            role=relation.role,
            role_index=relation.role_index,
            is_primary=relation.is_primary,
            is_co_owner=relation.is_co_owner,
            valid_from=relation.valid_from,
            party=PartySummary.from_domain(party, contacts),
        )


class PropertyUnitDetailResponse(BaseModel):
    unit: PropertyUnitRow
    listings: list[PropertyListingResponse]
    parties: list[UnitPartyRelationResponse]


class PropertyUnitCreateRequest(BaseModel):
    complex_id: int
    unit_number: str = Field(min_length=1, max_length=50)
    building_number: str | None = Field(default=None, max_length=50)
    floor_number: str | None = Field(default=None, max_length=20)
    orientation: str | None = Field(default=None, max_length=30)
    unit_type: str | None = Field(default=None, max_length=30)
    pyeong: Decimal | None = None
    exclusive_area_sqm: Decimal | None = None
    supply_area_sqm: Decimal | None = None
    tenancy_status: str | None = Field(default=None, max_length=30)
    current_deposit_amount: int | None = None
    current_monthly_rent_amount: int | None = None
    loan_amount: int | None = None
    tenancy_expiry_date: date | None = None
    tenancy_raw_text: str | None = None
    is_expanded: bool | None = None
    built_in_features: str | None = None
    facility_condition: str | None = None
    assigned_user_id: int | None = None
    memo: str | None = None
    custom_fields: dict[str, object] = Field(default_factory=dict)


class PropertyUnitUpdateRequest(BaseModel):
    row_version: int
    building_number: str | None = Field(default=None, max_length=50)
    unit_number: str | None = Field(default=None, min_length=1, max_length=50)
    floor_number: str | None = Field(default=None, max_length=20)
    orientation: str | None = Field(default=None, max_length=30)
    unit_type: str | None = Field(default=None, max_length=30)
    pyeong: Decimal | None = None
    exclusive_area_sqm: Decimal | None = None
    supply_area_sqm: Decimal | None = None
    tenancy_status: str | None = Field(default=None, max_length=30)
    current_deposit_amount: int | None = None
    current_monthly_rent_amount: int | None = None
    loan_amount: int | None = None
    tenancy_expiry_date: date | None = None
    tenancy_raw_text: str | None = None
    is_expanded: bool | None = None
    built_in_features: str | None = None
    facility_condition: str | None = None
    lifecycle_status: str | None = Field(default=None, max_length=30)
    assigned_user_id: int | None = None
    memo: str | None = None
    custom_fields: dict[str, object] | None = None


class PropertyListingCreateRequest(BaseModel):
    client_party_id: int | None = None
    received_at: date | None = None
    status: str | None = Field(default=None, max_length=30)
    is_sale_available: bool = False
    sale_price: int | None = None
    is_jeonse_available: bool = False
    jeonse_deposit_amount: int | None = None
    is_monthly_rent_available: bool = False
    monthly_rent_deposit_amount: int | None = None
    monthly_rent_amount: int | None = None
    price_raw_text: str | None = None
    handover_condition: str | None = Field(default=None, max_length=100)
    assigned_user_id: int | None = None
    memo: str | None = None
    custom_fields: dict[str, object] = Field(default_factory=dict)


class PropertyListingUpdateRequest(BaseModel):
    row_version: int
    client_party_id: int | None = None
    received_at: date | None = None
    status: str | None = Field(default=None, max_length=30)
    is_sale_available: bool | None = None
    sale_price: int | None = None
    is_jeonse_available: bool | None = None
    jeonse_deposit_amount: int | None = None
    is_monthly_rent_available: bool | None = None
    monthly_rent_deposit_amount: int | None = None
    monthly_rent_amount: int | None = None
    price_raw_text: str | None = None
    handover_condition: str | None = Field(default=None, max_length=100)
    assigned_user_id: int | None = None
    memo: str | None = None
    custom_fields: dict[str, object] | None = None


class ColumnValueItem(BaseModel):
    value: str
    count: int


class ColumnValuesResponse(BaseModel):
    column: str
    items: list[ColumnValueItem]


class RequirementComplexResponse(BaseModel):
    complex: PropertyComplexSummary
    preference_order: int | None

    @classmethod
    def from_domain(
        cls, link: PropertyRequirementComplex, complex_row: PropertyComplex
    ) -> RequirementComplexResponse:
        return cls(
            complex=PropertyComplexSummary.from_domain(complex_row),
            preference_order=link.preference_order,
        )


class PropertyRequirementRow(BaseModel):
    """구입장 한 행. 원문 필드와 파싱값을 함께 싣는다."""

    id: int
    party: PartySummary
    received_at: date | None
    demand_type: str
    desired_pyeongs: list[Decimal] | None
    min_area_sqm: Decimal | None
    max_area_sqm: Decimal | None
    area_requirement_raw_text: str | None
    min_budget_amount: int | None
    max_budget_amount: int | None
    budget_raw_text: str | None
    desired_move_in_date: date | None
    move_in_date_raw_text: str | None
    request_expiry_date: date | None
    current_tenancy_expiry_date: date | None
    co_broker_party_id: int | None
    classification: str | None
    workflow_stage: str | None
    status: str
    assigned_user_id: int | None
    memo: str | None
    custom_fields: dict[str, object]
    last_contact_at: datetime | None
    row_version: int

    @classmethod
    def from_domain(
        cls,
        requirement: PropertyRequirement,
        party: Party,
        contacts: list[PartyContact],
    ) -> PropertyRequirementRow:
        return cls(
            id=requirement.id or 0,
            party=PartySummary.from_domain(party, contacts),
            received_at=requirement.received_at,
            demand_type=requirement.demand_type,
            desired_pyeongs=requirement.desired_pyeongs,
            min_area_sqm=requirement.min_area_sqm,
            max_area_sqm=requirement.max_area_sqm,
            area_requirement_raw_text=requirement.area_requirement_raw_text,
            min_budget_amount=requirement.min_budget_amount,
            max_budget_amount=requirement.max_budget_amount,
            budget_raw_text=requirement.budget_raw_text,
            desired_move_in_date=requirement.desired_move_in_date,
            move_in_date_raw_text=requirement.move_in_date_raw_text,
            request_expiry_date=requirement.request_expiry_date,
            current_tenancy_expiry_date=requirement.current_tenancy_expiry_date,
            co_broker_party_id=requirement.co_broker_party_id,
            classification=requirement.classification,
            workflow_stage=requirement.workflow_stage,
            status=requirement.status,
            assigned_user_id=requirement.assigned_user_id,
            memo=requirement.memo,
            custom_fields=requirement.custom_fields,
            last_contact_at=requirement.last_contact_at,
            row_version=requirement.row_version,
        )


class PropertyRequirementListResponse(BaseModel):
    items: list[PropertyRequirementRow]
    total: int
    limit: int
    offset: int


class PropertyRequirementDetailResponse(BaseModel):
    requirement: PropertyRequirementRow
    desired_complexes: list[RequirementComplexResponse]


class PropertyRequirementCreateRequest(BaseModel):
    party_id: int
    demand_type: str = Field(min_length=1, max_length=20)
    received_at: date | None = None
    desired_pyeongs: list[Decimal] | None = None
    desired_complex_ids: list[int] = Field(default_factory=list)
    min_area_sqm: Decimal | None = None
    max_area_sqm: Decimal | None = None
    area_requirement_raw_text: str | None = None
    min_budget_amount: int | None = None
    max_budget_amount: int | None = None
    budget_raw_text: str | None = None
    desired_move_in_date: date | None = None
    move_in_date_raw_text: str | None = None
    request_expiry_date: date | None = None
    current_tenancy_expiry_date: date | None = None
    co_broker_party_id: int | None = None
    classification: str | None = Field(default=None, max_length=100)
    workflow_stage: str | None = Field(default=None, max_length=100)
    status: str | None = Field(default=None, max_length=20)
    assigned_user_id: int | None = None
    memo: str | None = None
    custom_fields: dict[str, object] = Field(default_factory=dict)


class PropertyRequirementUpdateRequest(BaseModel):
    row_version: int
    demand_type: str | None = Field(default=None, min_length=1, max_length=20)
    received_at: date | None = None
    desired_pyeongs: list[Decimal] | None = None
    desired_complex_ids: list[int] | None = None
    min_area_sqm: Decimal | None = None
    max_area_sqm: Decimal | None = None
    area_requirement_raw_text: str | None = None
    min_budget_amount: int | None = None
    max_budget_amount: int | None = None
    budget_raw_text: str | None = None
    desired_move_in_date: date | None = None
    move_in_date_raw_text: str | None = None
    request_expiry_date: date | None = None
    current_tenancy_expiry_date: date | None = None
    co_broker_party_id: int | None = None
    classification: str | None = Field(default=None, max_length=100)
    workflow_stage: str | None = Field(default=None, max_length=100)
    status: str | None = Field(default=None, max_length=20)
    assigned_user_id: int | None = None
    memo: str | None = None
    custom_fields: dict[str, object] | None = None


class ClientInteractionResponse(BaseModel):
    id: int
    interaction_at: datetime | None
    interaction_channel: str
    communication_direction: str | None
    interaction_result: str | None
    counterparty_role: str | None
    counterparty_index: int | None
    interaction_content: str
    party_id: int | None
    unit_id: int | None
    listing_id: int | None
    requirement_id: int | None
    source_type: str
    approval_status: str
    created_by: int | None
    created_at: datetime | None

    @classmethod
    def from_domain(cls, row: ClientInteraction) -> ClientInteractionResponse:
        return cls(
            id=row.id or 0,
            interaction_at=row.interaction_at,
            interaction_channel=row.interaction_channel,
            communication_direction=row.communication_direction,
            interaction_result=row.interaction_result,
            counterparty_role=row.counterparty_role,
            counterparty_index=row.counterparty_index,
            interaction_content=row.interaction_content,
            party_id=row.party_id,
            unit_id=row.unit_id,
            listing_id=row.listing_id,
            requirement_id=row.requirement_id,
            source_type=row.source_type,
            approval_status=row.approval_status,
            created_by=row.created_by,
            created_at=row.created_at,
        )


class ClientInteractionListResponse(BaseModel):
    items: list[ClientInteractionResponse]
    total: int
    limit: int
    offset: int


class ClientInteractionCreateRequest(BaseModel):
    interaction_content: str = Field(min_length=1)
    interaction_at: datetime | None = None
    interaction_channel: str | None = Field(default=None, max_length=20)
    communication_direction: str | None = Field(default=None, max_length=20)
    interaction_result: str | None = Field(default=None, max_length=20)
    counterparty_role: str | None = Field(default=None, max_length=20)
    counterparty_index: int | None = None
    party_id: int | None = None
    unit_id: int | None = None
    listing_id: int | None = None
    requirement_id: int | None = None
    related_context: dict[str, object] = Field(default_factory=dict)
