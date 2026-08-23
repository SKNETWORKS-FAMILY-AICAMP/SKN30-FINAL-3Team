"""소프트 삭제 동작 검증.

삭제는 행을 지우지 않는다. 상담 로그와 매물 이력이 세대를 참조하므로 물리 삭제는 이력을 잃는다.
그래서 확인할 것은 네 가지다. 목록에서 빠지는가, 딸린 매물 건은 그대로 남는가,
낡은 row_version으로는 삭제되지 않는가, 그리고 단지 삭제와 세대 등록이 동시에 들어와도
감춰진 단지에 살아 있는 세대가 남지 않는가.
"""

import os
import threading
import time
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import delete, text
from sqlalchemy.pool import NullPool
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
    engine = create_engine(os.environ["TEST_DB_URL"], poolclass=NullPool)
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

        party_ids = session.exec(select(Party.id).where(col(Party.name) == SEED_PARTY_NAME)).all()
        if party_ids:
            session.execute(
                delete(PropertyRequirement).where(col(PropertyRequirement.party_id).in_(party_ids))
            )
            session.execute(delete(Party).where(col(Party.id).in_(party_ids)))
        session.commit()


def seeded_complex(session: Session) -> int:
    complex_row = PropertyComplex(brokerage_id=BROKERAGE_ID, name=SEED_COMPLEX_NAME)
    session.add(complex_row)
    session.flush()
    session.commit()
    return complex_row.id or 0


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
def test_deleted_unit_disappears_from_the_listing_but_leaves_its_listings_untouched() -> None:
    """세대 삭제는 딸린 매물 건을 수정하지 않는다.

    매물 건은 자신의 row_version을 갖고 있어, 한 요청에서 함께 고치면 그 낙관적 잠금을
    우회한다. 매물이 화면에서 사라지는 것은 조회가 세대를 join하기 때문이지
    매물 행을 건드려서가 아니다.
    """
    engine = create_engine(os.environ["TEST_DB_URL"], poolclass=NullPool)

    with Session(engine) as session:
        unit_id, listing_id = seeded_unit(session)
        filters = PropertyUnitFilters()
        before = repository.count_property_units(session, BROKERAGE_ID, filters)
        listing_before = session.exec(
            select(PropertyListing).where(PropertyListing.id == listing_id)
        ).one()
        listing_version_before = listing_before.row_version

        service.delete_property_unit(session, BROKERAGE_ID, unit_id, expected_row_version=1)

        assert repository.count_property_units(session, BROKERAGE_ID, filters) == before - 1
        assert repository.find_property_unit(session, BROKERAGE_ID, unit_id) is None

        session.expire_all()
        stored_unit = session.exec(select(PropertyUnit).where(PropertyUnit.id == unit_id)).one()
        stored_listing = session.exec(
            select(PropertyListing).where(PropertyListing.id == listing_id)
        ).one()
        # 세대 행 자체는 남아 있어야 이력을 잃지 않는다.
        assert stored_unit.is_deleted is True
        assert stored_unit.deleted_at is not None
        # 매물 건은 손대지 않는다. 버전이 오르면 다른 사람의 동시 수정을 덮은 것이다.
        assert stored_listing.is_deleted is False
        assert stored_listing.row_version == listing_version_before


@requires_database
def test_delete_rejects_a_stale_row_version() -> None:
    engine = create_engine(os.environ["TEST_DB_URL"], poolclass=NullPool)

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
    engine = create_engine(os.environ["TEST_DB_URL"], poolclass=NullPool)

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
    engine = create_engine(os.environ["TEST_DB_URL"], poolclass=NullPool)

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
    engine = create_engine(os.environ["TEST_DB_URL"], poolclass=NullPool)

    with Session(engine) as session:
        unit_id, _ = seeded_unit(session)
        unit = session.exec(select(PropertyUnit).where(PropertyUnit.id == unit_id)).one()

        with pytest.raises(ValidationError):
            service.delete_property_complex(
                session, BROKERAGE_ID, unit.complex_id, expected_row_version=1
            )

        assert repository.find_property_complex(session, BROKERAGE_ID, unit.complex_id) is not None


def run_in_another_session(
    engine: Any, work: Any
) -> tuple[threading.Thread, list[Any], threading.Event]:
    """다른 커넥션에서 `work(session)`을 돌리고 결과나 예외를 목록에 담는다.

    경합을 재현하려면 커넥션이 둘이어야 한다. 같은 세션으로는 자기 잠금을 기다리지 않는다.
    """
    outcome: list[Any] = []
    started = threading.Event()

    def run() -> None:
        with Session(engine) as session:
            started.set()
            try:
                outcome.append(work(session))
            except Exception as error:  # noqa: BLE001 - 스레드 밖으로 결과를 옮기기 위해서다
                outcome.append(error)

    return threading.Thread(target=run), outcome, started


def wait_until_another_transaction_is_blocked(session: Session, timeout: float = 10.0) -> None:
    """다른 커넥션이 잠금 대기에 들어갈 때까지 기다린다.

    고정 시간 sleep으로 대신하지 않는다. sleep은 상대가 아직 질의를 보내지 않았을 뿐인
    경우에도 통과해, 잠금을 제거해도 초록으로 남는 테스트가 된다. 여기서는 대기 중인 잠금이
    실제로 생겼는지를 `pg_locks`에서 확인한다.

    이 세션은 잠금을 쥔 채 idle in transaction 상태이므로 질의를 보내도 자기 잠금을 놓지 않는다.

    묻는 것은 "내가 쥔 트랜잭션을 기다리는 다른 세션이 있는가"다. 행 잠금 대기는
    `locktype = 'transactionid'`인 미승인 잠금으로 나타나므로, 그 잠금을 이미 승인받아
    쥐고 있는 쪽이 나인지 확인하면 무관한 커넥션의 대기와 섞이지 않는다.

    `pg_stat_activity`와 `pg_blocking_pids` 조합은 쓰지 않는다. PostgreSQL 15는
    `stats_fetch_consistency = cache`가 기본이라 통계 뷰가 트랜잭션 종료까지 캐시된다.
    한 트랜잭션 안에서 반복 조회하면 처음 읽은 값이 그대로 되돌아와 영원히 0이 된다.
    `pg_locks`는 통계 뷰가 아니라 잠금 관리자를 직접 읽으므로 매번 최신이다.
    """
    deadline = time.monotonic() + timeout
    statement = text(
        "SELECT count(*) FROM pg_locks blocked"
        " JOIN pg_locks holder"
        "   ON holder.locktype = 'transactionid'"
        "  AND holder.transactionid = blocked.transactionid"
        "  AND holder.granted"
        " WHERE NOT blocked.granted"
        "   AND blocked.locktype = 'transactionid'"
        "   AND holder.pid = pg_backend_pid()"
    )
    while time.monotonic() < deadline:
        if session.execute(statement).scalar_one() > 0:
            return
        time.sleep(0.02)
    raise AssertionError(
        "다른 트랜잭션이 잠금을 기다리지 않는다. 두 경로가 직렬화되지 않는다는 뜻이다."
    )


@requires_database
def test_complex_delete_waits_for_a_concurrent_unit_insert_and_is_then_refused() -> None:
    """세대 등록이 단지 잠금을 먼저 쥐면 단지 삭제는 그 세대를 보고 거절된다.

    잠그지 않으면 삭제가 남은 세대를 0으로 세고 그대로 커밋한다. 그러면 감춰진 단지에
    살아 있는 세대가 남고, 세대 조회는 단지를 inner join하므로 그 세대는 지운 단지 이름을
    달고 목록에 계속 나타난다.
    """
    engine = create_engine(os.environ["TEST_DB_URL"], poolclass=NullPool)
    with Session(engine) as setup:
        complex_id = seeded_complex(setup)

    thread, outcome, started = run_in_another_session(
        engine,
        lambda session: service.delete_property_complex(
            session, BROKERAGE_ID, complex_id, expected_row_version=1
        ),
    )

    with Session(engine) as creator:
        # 세대 등록 경로가 하는 일과 같다. 단지를 공유 잠금으로 쥐고 커밋 전까지 놓지 않는다.
        assert (
            repository.lock_property_complex(creator, BROKERAGE_ID, complex_id, exclusive=False)
            is not None
        )
        creator.add(
            PropertyUnit(brokerage_id=BROKERAGE_ID, complex_id=complex_id, unit_number="1801")
        )
        creator.flush()

        thread.start()
        assert started.wait(timeout=5)
        # 삭제는 배타 잠금을 원하므로 여기서 막힌다. 막혔다는 사실 자체를 확인한다.
        wait_until_another_transaction_is_blocked(creator)
        assert outcome == []

        creator.commit()

    thread.join(timeout=10)
    assert not thread.is_alive()
    assert len(outcome) == 1
    assert isinstance(outcome[0], ValidationError)
    assert outcome[0].code == "COMPLEX_HAS_UNITS"

    with Session(engine) as check:
        assert repository.find_property_complex(check, BROKERAGE_ID, complex_id) is not None


@requires_database
def test_unit_creation_is_refused_once_the_complex_delete_commits() -> None:
    """단지 삭제가 잠금을 먼저 쥐면 뒤따르는 세대 등록이 거절된다."""
    engine = create_engine(os.environ["TEST_DB_URL"], poolclass=NullPool)
    with Session(engine) as setup:
        complex_id = seeded_complex(setup)

    thread, outcome, started = run_in_another_session(
        engine,
        lambda session: service.create_property_unit(
            session, BROKERAGE_ID, {"complex_id": complex_id, "unit_number": "1801"}
        ),
    )

    with Session(engine) as deleter:
        # 단지 삭제 경로가 하는 일과 같다. 배타로 잠그고, 남은 세대를 세고, 커밋 전까지 쥔다.
        assert (
            repository.lock_property_complex(deleter, BROKERAGE_ID, complex_id, exclusive=True)
            is not None
        )
        assert repository.count_units_in_complex(deleter, BROKERAGE_ID, complex_id) == 0

        thread.start()
        assert started.wait(timeout=5)
        # 세대 등록이 여기서 막힌다. 막히지 않으면 세대가 먼저 들어가고 아래 삭제가 그 사실을
        # 못 본 채 커밋된다.
        wait_until_another_transaction_is_blocked(deleter)
        assert outcome == []

        assert repository.bump_row_version(
            deleter,
            PropertyComplex,
            BROKERAGE_ID,
            complex_id,
            1,
            {"is_deleted": True, "deleted_at": datetime.now(UTC)},
        )
        deleter.commit()

    thread.join(timeout=10)
    assert not thread.is_alive()
    assert len(outcome) == 1
    assert isinstance(outcome[0], ValidationError)

    with Session(engine) as check:
        assert repository.count_units_in_complex(check, BROKERAGE_ID, complex_id) == 0


@requires_database
def test_concurrent_unit_creations_in_one_complex_do_not_block_each_other() -> None:
    """같은 단지에 세대를 동시에 넣는 정상 작업은 서로 기다리지 않는다.

    등록 쪽이 배타 잠금을 쓰면 이 흔한 작업이 한 줄로 직렬화된다. 등록이 보장해야 하는 것은
    "단지가 사라지지 않는다"뿐이므로 공유 잠금이면 충분하고, 공유 잠금끼리는 충돌하지 않는다.
    """
    engine = create_engine(os.environ["TEST_DB_URL"], poolclass=NullPool)
    with Session(engine) as setup:
        complex_id = seeded_complex(setup)

    thread, outcome, started = run_in_another_session(
        engine,
        lambda session: service.create_property_unit(
            session, BROKERAGE_ID, {"complex_id": complex_id, "unit_number": "1802"}
        ),
    )

    with Session(engine) as first_creator:
        assert (
            repository.lock_property_complex(
                first_creator, BROKERAGE_ID, complex_id, exclusive=False
            )
            is not None
        )
        first_creator.add(
            PropertyUnit(brokerage_id=BROKERAGE_ID, complex_id=complex_id, unit_number="1801")
        )
        first_creator.flush()

        thread.start()
        assert started.wait(timeout=5)
        # 첫 등록이 아직 커밋하지 않았는데도 두 번째 등록이 끝나야 한다.
        thread.join(timeout=10)
        assert not thread.is_alive()
        assert len(outcome) == 1
        assert isinstance(outcome[0], int)

        first_creator.commit()

    with Session(engine) as check:
        assert repository.count_units_in_complex(check, BROKERAGE_ID, complex_id) == 2


@requires_database
def test_empty_complex_is_deleted_and_leaves_the_option_list() -> None:
    engine = create_engine(os.environ["TEST_DB_URL"], poolclass=NullPool)

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
