"""소프트 삭제 동작 검증.

삭제는 행을 지우지 않는다. 상담 로그와 매물 이력이 세대를 참조하므로 물리 삭제는 이력을 잃는다.
그래서 확인할 것은 세 가지다. 목록에서 빠지는가, 딸린 매물 건도 함께 감춰지는가,
그리고 낡은 row_version으로는 삭제되지 않는가.
"""

import os
from typing import Any

import pytest
from sqlalchemy import delete
from sqlmodel import Session, col, create_engine, select

from core.errors import RowVersionConflictError, ValidationError
from domain.property_ledger import repository, service
from domain.property_ledger.models import (
    ClientInteraction,
    Party,
    PropertyComplex,
    PropertyListing,
    PropertyRequirement,
    PropertyUnit,
)
from domain.property_ledger.repository import Page, PropertyUnitFilters

requires_database = pytest.mark.skipif(
    not os.getenv("TEST_DB_URL"),
    reason="TEST_DB_URL is required for PostgreSQL integration tests",
)

BROKERAGE_ID = 1
SEED_COMPLEX_NAME = "삭제 검증 단지"
SEED_PARTY_NAME = "삭제 검증 손님"


@pytest.fixture(autouse=True)
def clean_up_seeded_complexes() -> Any:
    """테스트가 만든 단지를 남기지 않는다.

    남기면 화면의 단지 선택지에 검증용 이름이 계속 쌓인다. 실제로 그렇게 쌓인 적이 있다.
    """
    yield
    if not os.getenv("TEST_DB_URL"):
        return
    engine = create_engine(os.environ["TEST_DB_URL"])
    with Session(engine) as session:
        # 참조하는 쪽부터 지운다. 소프트 삭제된 행도 외래키는 그대로 걸려 있다.
        complex_ids = session.exec(
            select(PropertyComplex.id).where(col(PropertyComplex.name) == SEED_COMPLEX_NAME)
        ).all()
        if complex_ids:
            unit_ids = session.exec(
                select(PropertyUnit.id).where(col(PropertyUnit.complex_id).in_(complex_ids))
            ).all()
            if unit_ids:
                session.execute(
                    delete(ClientInteraction).where(col(ClientInteraction.unit_id).in_(unit_ids))
                )
                session.execute(
                    delete(PropertyListing).where(col(PropertyListing.unit_id).in_(unit_ids))
                )
                session.execute(delete(PropertyUnit).where(col(PropertyUnit.id).in_(unit_ids)))
            session.execute(delete(PropertyComplex).where(col(PropertyComplex.id).in_(complex_ids)))

        party_ids = session.exec(
            select(Party.id).where(col(Party.name) == SEED_PARTY_NAME)
        ).all()
        if party_ids:
            session.execute(
                delete(PropertyRequirement).where(col(PropertyRequirement.party_id).in_(party_ids))
            )
            session.execute(delete(Party).where(col(Party.id).in_(party_ids)))
        session.commit()


def seeded_unit(session: Session) -> tuple[int, int]:
    complex_row = PropertyComplex(brokerage_id=BROKERAGE_ID, name=SEED_COMPLEX_NAME)
    session.add(complex_row)
    session.flush()

    unit = PropertyUnit(
        brokerage_id=BROKERAGE_ID,
        complex_id=complex_row.id or 0,
        unit_number="1801",
        building_number="101",
    )
    session.add(unit)
    session.flush()

    listing = PropertyListing(brokerage_id=BROKERAGE_ID, unit_id=unit.id or 0)
    session.add(listing)
    session.flush()
    session.commit()
    return unit.id or 0, listing.id or 0


@requires_database
def test_deleted_unit_disappears_from_the_listing_and_hides_its_listings() -> None:
    engine = create_engine(os.environ["TEST_DB_URL"])

    with Session(engine) as session:
        unit_id, listing_id = seeded_unit(session)
        filters = PropertyUnitFilters()
        before = repository.count_property_units(session, BROKERAGE_ID, filters)

        service.delete_property_unit(session, BROKERAGE_ID, unit_id, expected_row_version=1)

        assert repository.count_property_units(session, BROKERAGE_ID, filters) == before - 1
        assert repository.find_property_unit(session, BROKERAGE_ID, unit_id) is None

        stored_unit = session.exec(select(PropertyUnit).where(PropertyUnit.id == unit_id)).one()
        stored_listing = session.exec(
            select(PropertyListing).where(PropertyListing.id == listing_id)
        ).one()
        # 행 자체는 남아 있어야 이력을 잃지 않는다.
        assert stored_unit.is_deleted is True
        assert stored_unit.deleted_at is not None
        assert stored_listing.is_deleted is True


@requires_database
def test_delete_rejects_a_stale_row_version() -> None:
    engine = create_engine(os.environ["TEST_DB_URL"])

    with Session(engine) as session:
        unit_id, _ = seeded_unit(session)
        service.update_property_unit(
            session, BROKERAGE_ID, unit_id, {"row_version": 1, "memo": "다른 사람이 먼저 고침"}
        )

        with pytest.raises(RowVersionConflictError):
            service.delete_property_unit(session, BROKERAGE_ID, unit_id, expected_row_version=1)

        assert repository.find_property_unit(session, BROKERAGE_ID, unit_id) is not None


@requires_database
def test_deleted_requirement_disappears_from_the_listing() -> None:
    engine = create_engine(os.environ["TEST_DB_URL"])

    with Session(engine) as session:
        party = Party(brokerage_id=BROKERAGE_ID, party_type="PERSON", name="삭제 검증 손님")
        session.add(party)
        session.flush()
        requirement = PropertyRequirement(
            brokerage_id=BROKERAGE_ID, party_id=party.id or 0, demand_type="매수"
        )
        session.add(requirement)
        session.flush()
        session.commit()
        requirement_id = requirement.id or 0

        service.delete_property_requirement(
            session, BROKERAGE_ID, requirement_id, expected_row_version=1
        )

        assert repository.find_property_requirement(session, BROKERAGE_ID, requirement_id) is None
        stored = session.exec(
            select(PropertyRequirement).where(PropertyRequirement.id == requirement_id)
        ).one()
        assert stored.is_deleted is True


@requires_database
def test_listing_page_excludes_deleted_units() -> None:
    engine = create_engine(os.environ["TEST_DB_URL"])

    with Session(engine) as session:
        unit_id, _ = seeded_unit(session)
        service.delete_property_unit(session, BROKERAGE_ID, unit_id, expected_row_version=1)

        rows = repository.list_property_units(
            session, BROKERAGE_ID, PropertyUnitFilters(), Page(limit=500, offset=0)
        )
        assert all(row[0].id != unit_id for row in rows)


@requires_database
def test_complex_delete_is_refused_while_units_remain() -> None:
    """세대가 남은 단지는 지울 수 없다. 지우면 그 세대들이 이름 없는 상태가 된다."""
    engine = create_engine(os.environ["TEST_DB_URL"])

    with Session(engine) as session:
        unit_id, _ = seeded_unit(session)
        unit = session.exec(select(PropertyUnit).where(PropertyUnit.id == unit_id)).one()

        with pytest.raises(ValidationError):
            service.delete_property_complex(
                session, BROKERAGE_ID, unit.complex_id, expected_row_version=1
            )

        assert repository.find_property_complex(session, BROKERAGE_ID, unit.complex_id) is not None


@requires_database
def test_empty_complex_is_deleted_and_leaves_the_option_list() -> None:
    engine = create_engine(os.environ["TEST_DB_URL"])

    with Session(engine) as session:
        unit_id, _ = seeded_unit(session)
        unit = session.exec(select(PropertyUnit).where(PropertyUnit.id == unit_id)).one()
        complex_id = unit.complex_id
        service.delete_property_unit(session, BROKERAGE_ID, unit_id, expected_row_version=1)

        service.delete_property_complex(session, BROKERAGE_ID, complex_id, expected_row_version=1)

        assert repository.find_property_complex(session, BROKERAGE_ID, complex_id) is None
        page = Page(limit=500, offset=0)
        listed = repository.list_property_complexes(session, BROKERAGE_ID, page)
        assert all(row.id != complex_id for row in listed)
