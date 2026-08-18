from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from api.schemas.property_ledger import (
    MAX_PAGE_SIZE,
    ClientInteractionCreateRequest,
    ClientInteractionListResponse,
    ClientInteractionResponse,
    ColumnValueItem,
    ColumnValuesResponse,
    PropertyListingCreateRequest,
    PropertyListingResponse,
    PropertyListingUpdateRequest,
    PropertyRequirementCreateRequest,
    PropertyRequirementDetailResponse,
    PropertyRequirementListResponse,
    PropertyRequirementRow,
    PropertyRequirementUpdateRequest,
    PropertyUnitCreateRequest,
    PropertyUnitDetailResponse,
    PropertyUnitListResponse,
    PropertyUnitRow,
    PropertyUnitUpdateRequest,
    RequirementComplexResponse,
    UnitPartyRelationResponse,
)
from core.errors import ValidationError
from domain.authentication.dependencies import get_current_user, require_csrf
from domain.authentication.models import CurrentUser
from domain.property_ledger import repository, service
from domain.property_ledger.repository import (
    Page,
    PropertyRequirementFilters,
    PropertyUnitFilters,
)
from domain.session import get_db_session

router = APIRouter(tags=["property-ledger"])

StringFilter = Annotated[list[str] | None, Query()]


def build_page(limit: int, offset: int) -> Page:
    return Page(limit=min(limit, MAX_PAGE_SIZE), offset=offset)


def unit_filters(
    complex_id: StringFilter = None,
    building_number: StringFilter = None,
    unit_number: StringFilter = None,
    floor_number: StringFilter = None,
    orientation: StringFilter = None,
    tenancy_status: StringFilter = None,
    lifecycle_status: StringFilter = None,
    unit_type: StringFilter = None,
    assigned_user_id: StringFilter = None,
    listing_status: StringFilter = None,
    handover_condition: StringFilter = None,
    is_expanded: bool | None = None,
    is_sale_available: bool | None = None,
    is_jeonse_available: bool | None = None,
    is_monthly_rent_available: bool | None = None,
) -> PropertyUnitFilters:
    return PropertyUnitFilters(
        complex_id=keep_values(complex_id),
        building_number=keep_values(building_number),
        unit_number=keep_values(unit_number),
        floor_number=keep_values(floor_number),
        orientation=keep_values(orientation),
        tenancy_status=keep_values(tenancy_status),
        lifecycle_status=keep_values(lifecycle_status),
        unit_type=keep_values(unit_type),
        assigned_user_id=keep_values(assigned_user_id),
        listing_status=keep_values(listing_status),
        handover_condition=keep_values(handover_condition),
        is_expanded=is_expanded,
        is_sale_available=is_sale_available,
        is_jeonse_available=is_jeonse_available,
        is_monthly_rent_available=is_monthly_rent_available,
    )


def requirement_filters(
    demand_type: StringFilter = None,
    status: StringFilter = None,
    classification: StringFilter = None,
    workflow_stage: StringFilter = None,
    assigned_user_id: StringFilter = None,
) -> PropertyRequirementFilters:
    return PropertyRequirementFilters(
        demand_type=keep_values(demand_type),
        status=keep_values(status),
        classification=keep_values(classification),
        workflow_stage=keep_values(workflow_stage),
        assigned_user_id=keep_values(assigned_user_id),
    )


def keep_values(values: list[str] | None) -> tuple[str, ...]:
    """값이 비어 있는 파라미터는 필터로 취급하지 않는다."""
    if not values:
        return ()
    return tuple(value for value in values if value != "")


def changed_fields(payload: Any) -> dict[str, Any]:
    return payload.model_dump(exclude_unset=True)


@router.get("/property-units", response_model=PropertyUnitListResponse)
def list_property_units(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db_session),
    filters: PropertyUnitFilters = Depends(unit_filters),
    limit: int = Query(default=100, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
) -> PropertyUnitListResponse:
    page = build_page(limit, offset)
    total = repository.count_property_units(db, user.brokerage_id, filters)
    rows = repository.list_property_units(db, user.brokerage_id, filters, page)
    return PropertyUnitListResponse(
        items=[PropertyUnitRow.from_domain(row[0], row[1], row[2]) for row in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/property-units/column-values", response_model=ColumnValuesResponse)
def property_unit_column_values(
    column: str = Query(),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db_session),
    filters: PropertyUnitFilters = Depends(unit_filters),
) -> ColumnValuesResponse:
    if column not in repository.supported_unit_columns():
        raise ValidationError(f"column must be one of {repository.supported_unit_columns()}")
    values = repository.property_unit_column_values(db, user.brokerage_id, filters, column)
    return ColumnValuesResponse(
        column=column,
        items=[ColumnValueItem(value=value, count=count) for value, count in values],
    )


@router.get("/property-units/{unit_id}", response_model=PropertyUnitDetailResponse)
def get_property_unit(
    unit_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> PropertyUnitDetailResponse:
    unit, complex_row = service.require_property_unit(db, user.brokerage_id, unit_id)
    listings = repository.list_listings_for_unit(db, user.brokerage_id, unit_id)
    relations = repository.list_unit_party_relations(db, user.brokerage_id, unit_id)
    contacts = repository.list_party_contacts(
        db, user.brokerage_id, [party.id or 0 for _, party in relations]
    )
    return PropertyUnitDetailResponse(
        unit=PropertyUnitRow.from_domain(unit, complex_row, listings[0] if listings else None),
        listings=[PropertyListingResponse.from_domain(listing) for listing in listings],
        parties=[
            UnitPartyRelationResponse.from_domain(
                relation,
                party,
                [contact for contact in contacts if contact.party_id == party.id],
            )
            for relation, party in relations
        ],
    )


@router.post("/property-units", response_model=PropertyUnitDetailResponse, status_code=201)
def create_property_unit(
    payload: PropertyUnitCreateRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db_session),
    _: None = Depends(require_csrf),
) -> PropertyUnitDetailResponse:
    unit_id = service.create_property_unit(db, user.brokerage_id, payload.model_dump())
    return get_property_unit(unit_id, user, db)


@router.patch("/property-units/{unit_id}", response_model=PropertyUnitDetailResponse)
def update_property_unit(
    unit_id: int,
    payload: PropertyUnitUpdateRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db_session),
    _: None = Depends(require_csrf),
) -> PropertyUnitDetailResponse:
    service.update_property_unit(db, user.brokerage_id, unit_id, changed_fields(payload))
    return get_property_unit(unit_id, user, db)


@router.post(
    "/property-units/{unit_id}/listings",
    response_model=PropertyListingResponse,
    status_code=201,
)
def create_property_listing(
    unit_id: int,
    payload: PropertyListingCreateRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db_session),
    _: None = Depends(require_csrf),
) -> PropertyListingResponse:
    listing_id = service.create_property_listing(
        db, user.brokerage_id, unit_id, changed_fields(payload)
    )
    listing = repository.find_property_listing(db, user.brokerage_id, listing_id)
    assert listing is not None
    return PropertyListingResponse.from_domain(listing)


@router.patch("/property-listings/{listing_id}", response_model=PropertyListingResponse)
def update_property_listing(
    listing_id: int,
    payload: PropertyListingUpdateRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db_session),
    _: None = Depends(require_csrf),
) -> PropertyListingResponse:
    service.update_property_listing(db, user.brokerage_id, listing_id, changed_fields(payload))
    listing = repository.find_property_listing(db, user.brokerage_id, listing_id)
    assert listing is not None
    return PropertyListingResponse.from_domain(listing)


@router.get("/property-requirements", response_model=PropertyRequirementListResponse)
def list_property_requirements(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db_session),
    filters: PropertyRequirementFilters = Depends(requirement_filters),
    limit: int = Query(default=100, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
) -> PropertyRequirementListResponse:
    page = build_page(limit, offset)
    total = repository.count_property_requirements(db, user.brokerage_id, filters)
    rows = repository.list_property_requirements(db, user.brokerage_id, filters, page)
    contacts = repository.list_party_contacts(
        db, user.brokerage_id, [row[1].id or 0 for row in rows]
    )
    return PropertyRequirementListResponse(
        items=[
            PropertyRequirementRow.from_domain(
                row[0],
                row[1],
                [contact for contact in contacts if contact.party_id == row[1].id],
            )
            for row in rows
        ],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/property-requirements/column-values", response_model=ColumnValuesResponse)
def property_requirement_column_values(
    column: str = Query(),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db_session),
    filters: PropertyRequirementFilters = Depends(requirement_filters),
) -> ColumnValuesResponse:
    if column not in repository.supported_requirement_columns():
        raise ValidationError(f"column must be one of {repository.supported_requirement_columns()}")
    values = repository.property_requirement_column_values(db, user.brokerage_id, filters, column)
    return ColumnValuesResponse(
        column=column,
        items=[ColumnValueItem(value=value, count=count) for value, count in values],
    )


@router.get(
    "/property-requirements/{requirement_id}",
    response_model=PropertyRequirementDetailResponse,
)
def get_property_requirement(
    requirement_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> PropertyRequirementDetailResponse:
    requirement, party = service.require_property_requirement(db, user.brokerage_id, requirement_id)
    contacts = repository.list_party_contacts(db, user.brokerage_id, [party.id or 0])
    links = repository.list_requirement_complexes(db, user.brokerage_id, requirement_id)
    return PropertyRequirementDetailResponse(
        requirement=PropertyRequirementRow.from_domain(requirement, party, contacts),
        desired_complexes=[
            RequirementComplexResponse.from_domain(link, complex_row) for link, complex_row in links
        ],
    )


@router.post(
    "/property-requirements",
    response_model=PropertyRequirementDetailResponse,
    status_code=201,
)
def create_property_requirement(
    payload: PropertyRequirementCreateRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db_session),
    _: None = Depends(require_csrf),
) -> PropertyRequirementDetailResponse:
    requirement_id = service.create_property_requirement(
        db, user.brokerage_id, changed_fields(payload)
    )
    return get_property_requirement(requirement_id, user, db)


@router.patch(
    "/property-requirements/{requirement_id}",
    response_model=PropertyRequirementDetailResponse,
)
def update_property_requirement(
    requirement_id: int,
    payload: PropertyRequirementUpdateRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db_session),
    _: None = Depends(require_csrf),
) -> PropertyRequirementDetailResponse:
    service.update_property_requirement(
        db, user.brokerage_id, requirement_id, changed_fields(payload)
    )
    return get_property_requirement(requirement_id, user, db)


@router.get("/client-interactions", response_model=ClientInteractionListResponse)
def list_client_interactions(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db_session),
    unit_id: int | None = None,
    requirement_id: int | None = None,
    party_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
) -> ClientInteractionListResponse:
    if unit_id is None and requirement_id is None and party_id is None:
        raise ValidationError("one of unit_id, requirement_id or party_id is required")

    page = build_page(limit, offset)
    rows, total = repository.list_client_interactions(
        db, user.brokerage_id, unit_id, requirement_id, party_id, page
    )
    return ClientInteractionListResponse(
        items=[ClientInteractionResponse.from_domain(row) for row in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post("/client-interactions", response_model=ClientInteractionResponse, status_code=201)
def create_client_interaction(
    payload: ClientInteractionCreateRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db_session),
    _: None = Depends(require_csrf),
) -> ClientInteractionResponse:
    interaction_id = service.create_client_interaction(
        db, user.brokerage_id, user.id, changed_fields(payload)
    )
    created = repository.find_client_interaction(db, user.brokerage_id, interaction_id)
    assert created is not None
    return ClientInteractionResponse.from_domain(created)
