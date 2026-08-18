from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar

from sqlalchemy import (
    ARRAY,
    JSON,
    BigInteger,
    Column,
    Date,
    DateTime,
    Numeric,
    SmallInteger,
    Text,
    func,
)
from sqlmodel import Field, SQLModel


def identity_column() -> Column[int]:
    return Column(BigInteger, primary_key=True, autoincrement=True)


def timestamp_column() -> Column[datetime]:
    return Column(DateTime(timezone=True))


def created_timestamp_column() -> Column[datetime]:
    """서버가 채우는 NOT NULL 시각. DB의 DEFAULT now()가 적용되도록 server_default를 붙인다."""
    return Column(DateTime(timezone=True), nullable=False, server_default=func.now())


def received_date_column() -> Column[date]:
    """서버가 채우는 NOT NULL 접수일. DB의 DEFAULT CURRENT_DATE가 적용되도록 한다."""
    return Column(Date, nullable=False, server_default=func.current_date())


class PropertyComplex(SQLModel, table=True):
    __tablename__: ClassVar[str] = "property_complex"  # pyright: ignore[reportIncompatibleVariableOverride]

    id: int | None = Field(default=None, sa_column=identity_column())
    brokerage_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    property_type: str = Field(default="APARTMENT", max_length=30)
    name: str = Field(max_length=150)
    road_address: str | None = Field(default=None, sa_column=Column(Text))
    memo: str | None = Field(default=None, sa_column=Column(Text))
    extra_info: dict[str, object] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    row_version: int = Field(default=1, sa_column=Column(BigInteger, nullable=False))
    is_deleted: bool = False
    deleted_at: datetime | None = Field(default=None, sa_column=timestamp_column())
    created_at: datetime | None = Field(default=None, sa_column=created_timestamp_column())
    updated_at: datetime | None = Field(default=None, sa_column=created_timestamp_column())


class PropertyUnit(SQLModel, table=True):
    __tablename__: ClassVar[str] = "property_unit"  # pyright: ignore[reportIncompatibleVariableOverride]

    id: int | None = Field(default=None, sa_column=identity_column())
    brokerage_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    complex_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    building_number: str | None = Field(default=None, max_length=50)
    unit_number: str = Field(max_length=50)
    floor_number: str | None = Field(default=None, max_length=20)
    orientation: str | None = Field(default=None, max_length=30)
    pyeong: Decimal | None = Field(default=None, sa_column=Column(Numeric(6, 2)))
    exclusive_area_sqm: Decimal | None = Field(default=None, sa_column=Column(Numeric(10, 2)))
    supply_area_sqm: Decimal | None = Field(default=None, sa_column=Column(Numeric(10, 2)))
    tenancy_status: str | None = Field(default=None, max_length=30)
    current_deposit_amount: int | None = Field(default=None, sa_column=Column(BigInteger))
    current_monthly_rent_amount: int | None = Field(default=None, sa_column=Column(BigInteger))
    loan_amount: int | None = Field(default=None, sa_column=Column(BigInteger))
    tenancy_expiry_date: date | None = Field(default=None, sa_column=Column(Date))
    tenancy_raw_text: str | None = Field(default=None, sa_column=Column(Text))
    assigned_user_id: int | None = Field(default=None, sa_column=Column(BigInteger))
    memo: str | None = Field(default=None, sa_column=Column(Text))
    custom_fields: dict[str, object] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    last_contact_at: datetime | None = Field(default=None, sa_column=timestamp_column())
    lifecycle_status: str = Field(default="NORMAL", max_length=30)
    unit_type: str | None = Field(default=None, max_length=30)
    is_expanded: bool | None = None
    built_in_features: str | None = Field(default=None, sa_column=Column(Text))
    facility_condition: str | None = Field(default=None, sa_column=Column(Text))
    row_version: int = Field(default=1, sa_column=Column(BigInteger, nullable=False))
    is_deleted: bool = False
    deleted_at: datetime | None = Field(default=None, sa_column=timestamp_column())
    created_at: datetime | None = Field(default=None, sa_column=created_timestamp_column())
    updated_at: datetime | None = Field(default=None, sa_column=created_timestamp_column())


class Party(SQLModel, table=True):
    __tablename__: ClassVar[str] = "party"  # pyright: ignore[reportIncompatibleVariableOverride]

    id: int | None = Field(default=None, sa_column=identity_column())
    brokerage_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    party_type: str = Field(max_length=20)
    name: str = Field(max_length=150)
    alternate_name: str | None = Field(default=None, max_length=150)
    memo: str | None = Field(default=None, sa_column=Column(Text))
    privacy_consent_at: datetime | None = Field(default=None, sa_column=timestamp_column())
    privacy_consent_by: int | None = Field(default=None, sa_column=Column(BigInteger))
    row_version: int = Field(default=1, sa_column=Column(BigInteger, nullable=False))
    is_deleted: bool = False
    deleted_at: datetime | None = Field(default=None, sa_column=timestamp_column())
    created_at: datetime | None = Field(default=None, sa_column=created_timestamp_column())
    updated_at: datetime | None = Field(default=None, sa_column=created_timestamp_column())


class PartyContact(SQLModel, table=True):
    __tablename__: ClassVar[str] = "party_contact"  # pyright: ignore[reportIncompatibleVariableOverride]

    id: int | None = Field(default=None, sa_column=identity_column())
    brokerage_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    party_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    contact_method: str = Field(default="PHONE", max_length=20)
    contact_value: str = Field(max_length=320)
    normalized_contact_value: str = Field(max_length=320)
    contact_label: str | None = Field(default=None, max_length=50)
    is_primary: bool = False
    contactability_status: str = Field(default="UNKNOWN", max_length=20)
    restriction_reason: str | None = Field(default=None, sa_column=Column(Text))
    row_version: int = Field(default=1, sa_column=Column(BigInteger, nullable=False))
    is_deleted: bool = False
    deleted_at: datetime | None = Field(default=None, sa_column=timestamp_column())
    created_at: datetime | None = Field(default=None, sa_column=created_timestamp_column())
    updated_at: datetime | None = Field(default=None, sa_column=created_timestamp_column())


class PropertyUnitPartyRelation(SQLModel, table=True):
    __tablename__: ClassVar[str] = "property_unit_party_relation"  # pyright: ignore[reportIncompatibleVariableOverride]

    id: int | None = Field(default=None, sa_column=identity_column())
    brokerage_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    unit_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    party_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    role: str = Field(max_length=20)
    role_index: int = Field(default=1, sa_column=Column(SmallInteger, nullable=False))
    is_primary: bool = False
    is_co_owner: bool = False
    valid_from: date | None = Field(default=None, sa_column=Column(Date))
    valid_to: date | None = Field(default=None, sa_column=Column(Date))
    memo: str | None = Field(default=None, sa_column=Column(Text))
    created_at: datetime | None = Field(default=None, sa_column=created_timestamp_column())


class PropertyListing(SQLModel, table=True):
    __tablename__: ClassVar[str] = "property_listing"  # pyright: ignore[reportIncompatibleVariableOverride]

    id: int | None = Field(default=None, sa_column=identity_column())
    brokerage_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    unit_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    client_party_id: int | None = Field(default=None, sa_column=Column(BigInteger))
    received_at: date | None = Field(default=None, sa_column=received_date_column())
    status: str = Field(default="RECEIVED", max_length=30)
    is_sale_available: bool = False
    sale_price: int | None = Field(default=None, sa_column=Column(BigInteger))
    is_jeonse_available: bool = False
    jeonse_deposit_amount: int | None = Field(default=None, sa_column=Column(BigInteger))
    is_monthly_rent_available: bool = False
    monthly_rent_deposit_amount: int | None = Field(default=None, sa_column=Column(BigInteger))
    monthly_rent_amount: int | None = Field(default=None, sa_column=Column(BigInteger))
    price_raw_text: str | None = Field(default=None, sa_column=Column(Text))
    handover_condition: str | None = Field(default=None, max_length=100)
    assigned_user_id: int | None = Field(default=None, sa_column=Column(BigInteger))
    memo: str | None = Field(default=None, sa_column=Column(Text))
    custom_fields: dict[str, object] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    row_version: int = Field(default=1, sa_column=Column(BigInteger, nullable=False))
    is_deleted: bool = False
    deleted_at: datetime | None = Field(default=None, sa_column=timestamp_column())
    created_at: datetime | None = Field(default=None, sa_column=created_timestamp_column())
    updated_at: datetime | None = Field(default=None, sa_column=created_timestamp_column())


class PropertyRequirement(SQLModel, table=True):
    __tablename__: ClassVar[str] = "property_requirement"  # pyright: ignore[reportIncompatibleVariableOverride]

    id: int | None = Field(default=None, sa_column=identity_column())
    brokerage_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    party_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    received_at: date | None = Field(default=None, sa_column=received_date_column())
    demand_type: str = Field(max_length=20)
    desired_pyeongs: list[Decimal] | None = Field(
        default=None, sa_column=Column(ARRAY(Numeric(6, 2)))
    )
    min_area_sqm: Decimal | None = Field(default=None, sa_column=Column(Numeric(10, 2)))
    max_area_sqm: Decimal | None = Field(default=None, sa_column=Column(Numeric(10, 2)))
    area_requirement_raw_text: str | None = Field(default=None, sa_column=Column(Text))
    min_budget_amount: int | None = Field(default=None, sa_column=Column(BigInteger))
    max_budget_amount: int | None = Field(default=None, sa_column=Column(BigInteger))
    budget_raw_text: str | None = Field(default=None, sa_column=Column(Text))
    desired_move_in_date: date | None = Field(default=None, sa_column=Column(Date))
    move_in_date_raw_text: str | None = Field(default=None, sa_column=Column(Text))
    request_expiry_date: date | None = Field(default=None, sa_column=Column(Date))
    status: str = Field(default="ACTIVE", max_length=20)
    assigned_user_id: int | None = Field(default=None, sa_column=Column(BigInteger))
    memo: str | None = Field(default=None, sa_column=Column(Text))
    custom_fields: dict[str, object] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    last_contact_at: datetime | None = Field(default=None, sa_column=timestamp_column())
    co_broker_party_id: int | None = Field(default=None, sa_column=Column(BigInteger))
    current_tenancy_expiry_date: date | None = Field(default=None, sa_column=Column(Date))
    classification: str | None = Field(default=None, max_length=100)
    workflow_stage: str | None = Field(default=None, max_length=100)
    row_version: int = Field(default=1, sa_column=Column(BigInteger, nullable=False))
    is_deleted: bool = False
    deleted_at: datetime | None = Field(default=None, sa_column=timestamp_column())
    created_at: datetime | None = Field(default=None, sa_column=created_timestamp_column())
    updated_at: datetime | None = Field(default=None, sa_column=created_timestamp_column())


class PropertyRequirementComplex(SQLModel, table=True):
    __tablename__: ClassVar[str] = "property_requirement_complex"  # pyright: ignore[reportIncompatibleVariableOverride]

    brokerage_id: int = Field(sa_column=Column(BigInteger, primary_key=True))
    requirement_id: int = Field(sa_column=Column(BigInteger, primary_key=True))
    complex_id: int = Field(sa_column=Column(BigInteger, primary_key=True))
    preference_order: int | None = Field(default=None, sa_column=Column(SmallInteger))
    created_at: datetime | None = Field(default=None, sa_column=created_timestamp_column())


class ClientInteraction(SQLModel, table=True):
    __tablename__: ClassVar[str] = "client_interaction"  # pyright: ignore[reportIncompatibleVariableOverride]

    id: int | None = Field(default=None, sa_column=identity_column())
    brokerage_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    interaction_at: datetime | None = Field(default=None, sa_column=created_timestamp_column())
    interaction_channel: str = Field(default="CALL", max_length=20)
    communication_direction: str | None = Field(default=None, max_length=20)
    interaction_result: str | None = Field(default=None, max_length=20)
    counterparty_role: str | None = Field(default=None, max_length=20)
    counterparty_index: int | None = Field(default=None, sa_column=Column(SmallInteger))
    interaction_content: str = Field(sa_column=Column(Text, nullable=False))
    party_id: int | None = Field(default=None, sa_column=Column(BigInteger))
    unit_id: int | None = Field(default=None, sa_column=Column(BigInteger))
    listing_id: int | None = Field(default=None, sa_column=Column(BigInteger))
    requirement_id: int | None = Field(default=None, sa_column=Column(BigInteger))
    related_context: dict[str, object] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    source_type: str = Field(default="HUMAN", max_length=20)
    approval_status: str = Field(default="NOT_REQUIRED", max_length=20)
    approved_by: int | None = Field(default=None, sa_column=Column(BigInteger))
    approved_at: datetime | None = Field(default=None, sa_column=timestamp_column())
    source_metadata: dict[str, object] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    created_by: int | None = Field(default=None, sa_column=Column(BigInteger))
    is_voided: bool = False
    void_reason: str | None = Field(default=None, sa_column=Column(Text))
    voided_by: int | None = Field(default=None, sa_column=Column(BigInteger))
    voided_at: datetime | None = Field(default=None, sa_column=timestamp_column())
    created_at: datetime | None = Field(default=None, sa_column=created_timestamp_column())
