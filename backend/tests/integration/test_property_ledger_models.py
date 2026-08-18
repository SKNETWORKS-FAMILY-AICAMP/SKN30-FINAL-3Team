import os
from decimal import Decimal

import pytest
from sqlalchemy import inspect
from sqlmodel import Session, SQLModel, create_engine, select

from domain.property_ledger import models
from domain.property_ledger.models import (
    Party,
    PropertyComplex,
    PropertyRequirement,
    PropertyUnit,
)

requires_database = pytest.mark.skipif(
    not os.getenv("TEST_DB_URL"),
    reason="TEST_DB_URL is required for PostgreSQL integration tests",
)


LEDGER_TABLES = [
    "property_complex",
    "property_unit",
    "party",
    "party_contact",
    "property_unit_party_relation",
    "property_listing",
    "property_requirement",
    "property_requirement_complex",
    "client_interaction",
]


def test_module_defines_every_ledger_table() -> None:
    declared = {
        value.__dict__["__tablename__"]
        for value in vars(models).values()
        if isinstance(value, type) and value is not SQLModel and issubclass(value, SQLModel)
        if "__tablename__" in value.__dict__
    }

    assert declared == set(LEDGER_TABLES)


@requires_database
@pytest.mark.parametrize("table_name", LEDGER_TABLES)
def test_model_columns_match_migrated_schema(table_name: str) -> None:
    engine = create_engine(os.environ["TEST_DB_URL"])
    inspector = inspect(engine)

    database_columns = {column["name"] for column in inspector.get_columns(table_name)}
    model_columns = {column.name for column in SQLModel.metadata.tables[table_name].columns}

    assert model_columns == database_columns


@requires_database
def test_numeric_array_json_and_bigint_values_survive_a_round_trip() -> None:
    engine = create_engine(os.environ["TEST_DB_URL"])

    with Session(engine) as session:
        brokerage_id = session.exec(select(PropertyComplex.brokerage_id).limit(1)).first()
        if brokerage_id is None:
            brokerage_id = 1

        complex_row = PropertyComplex(brokerage_id=brokerage_id, name="왕복 검증 단지")
        session.add(complex_row)
        session.flush()

        unit = PropertyUnit(
            brokerage_id=brokerage_id,
            complex_id=complex_row.id or 0,
            unit_number="1201",
            pyeong=Decimal("33.45"),
            current_deposit_amount=945_000_000,
            custom_fields={"사용자1": "메모"},
        )
        party = Party(brokerage_id=brokerage_id, party_type="PERSON", name="인천사모님")
        session.add(unit)
        session.add(party)
        session.flush()

        requirement = PropertyRequirement(
            brokerage_id=brokerage_id,
            party_id=party.id or 0,
            demand_type="매수",
            desired_pyeongs=[Decimal("25"), Decimal("33")],
            max_budget_amount=2_880_000_000,
            budget_raw_text="28억선",
        )
        session.add(requirement)
        session.flush()
        session.expire_all()

        stored_unit = session.exec(select(PropertyUnit).where(PropertyUnit.id == unit.id)).one()
        stored_requirement = session.exec(
            select(PropertyRequirement).where(PropertyRequirement.id == requirement.id)
        ).one()

        assert stored_unit.pyeong == Decimal("33.45")
        assert stored_unit.current_deposit_amount == 945_000_000
        assert stored_unit.custom_fields == {"사용자1": "메모"}
        assert stored_requirement.desired_pyeongs == [Decimal("25.00"), Decimal("33.00")]
        assert stored_requirement.max_budget_amount == 2_880_000_000
        assert stored_requirement.budget_raw_text == "28억선"

        session.rollback()


@requires_database
def test_server_defaults_fill_required_timestamps_and_received_date() -> None:
    engine = create_engine(os.environ["TEST_DB_URL"])

    with Session(engine) as session:
        complex_row = PropertyComplex(brokerage_id=1, name="기본값 검증 단지")
        session.add(complex_row)
        session.flush()
        session.refresh(complex_row)

        assert complex_row.created_at is not None
        assert complex_row.updated_at is not None

        party = Party(brokerage_id=1, party_type="PERSON", name="기본값 손님")
        session.add(party)
        session.flush()

        requirement = PropertyRequirement(
            brokerage_id=1, party_id=party.id or 0, demand_type="매수"
        )
        session.add(requirement)
        session.flush()
        session.refresh(requirement)

        assert requirement.received_at is not None

        session.rollback()
