"""백필이 접수하는 앵커 범위 검증.

백필은 활성 장부마다 `LEDGER_SAVE` 실행을 접수한다. 그 범위가 F3 앵커 유효성과 어긋나면
Worker 가 다룰 수 없는 실행이 주차된 채 남는다.

특히 매물은 자기 `is_deleted` 만으로 판정할 수 없다. **부모 세대가 소프트 삭제되면 딸린 매물
건은 그대로 남지만** 화면과 F3 앵커에서는 사라진다(`find_property_listing`). 백필이 그 규칙을
따로 복사하면 F1 이 범위를 바꿀 때 조용히 어긋난다.
"""

import os
from typing import Any

import pytest
from sqlalchemy import delete, text
from sqlmodel import Session, col, create_engine, select

from domain.agent_execution.backfill import backfill_position_cards
from domain.property_ledger.models import (
    PropertyComplex,
    PropertyListing,
    PropertyUnit,
)

requires_database = pytest.mark.skipif(
    not os.getenv("TEST_DB_URL"),
    reason="TEST_DB_URL is required for PostgreSQL integration tests",
)

BROKERAGE_ID = 0
USER_ID = 0
SEED_COMPLEX_NAME = "백필 검증 단지"


@pytest.fixture(autouse=True)
def isolated_brokerage() -> Any:
    """빈 migration DB 에서도 돌도록 사무소와 장부를 테스트별로 격리한다."""
    if not os.getenv("TEST_DB_URL"):
        yield
        return

    global BROKERAGE_ID, USER_ID
    engine = create_engine(os.environ["TEST_DB_URL"])
    with Session(engine) as session:
        BROKERAGE_ID = session.execute(
            text("INSERT INTO brokerage (name) VALUES ('백필 통합 검증 사무소') RETURNING id")
        ).scalar_one()
        USER_ID = session.execute(
            text(
                "INSERT INTO app_user (brokerage_id, login_id, display_name, password_hash, role)"
                " VALUES (:b, 'backfill_probe', '백필 검증자',"
                " '!development-login-disabled!', 'OWNER') RETURNING id"
            ),
            {"b": BROKERAGE_ID},
        ).scalar_one()
        session.commit()

    yield

    with Session(engine) as session:
        # 참조하는 쪽부터 지운다. `agent_run` 이 매물을 외래키로 잡고 있다.
        session.execute(text("DELETE FROM agent_run WHERE brokerage_id = :b"), {"b": BROKERAGE_ID})
        complex_ids = session.exec(
            select(PropertyComplex.id).where(
                PropertyComplex.brokerage_id == BROKERAGE_ID,
                col(PropertyComplex.name) == SEED_COMPLEX_NAME,
            )
        ).all()
        if complex_ids:
            unit_ids = session.exec(
                select(PropertyUnit.id).where(col(PropertyUnit.complex_id).in_(complex_ids))
            ).all()
            if unit_ids:
                session.execute(
                    delete(PropertyListing).where(col(PropertyListing.unit_id).in_(unit_ids))
                )
                session.execute(delete(PropertyUnit).where(col(PropertyUnit.id).in_(unit_ids)))
            session.execute(delete(PropertyComplex).where(col(PropertyComplex.id).in_(complex_ids)))
        session.execute(text("DELETE FROM app_user WHERE brokerage_id = :b"), {"b": BROKERAGE_ID})
        session.execute(text("DELETE FROM brokerage WHERE id = :b"), {"b": BROKERAGE_ID})
        session.commit()


def _listing_under_new_unit(session: Session, unit_number: str) -> tuple[int, int]:
    """단지·세대·매물을 한 벌 만든다. 세대 ID 와 매물 ID 를 돌려준다."""
    complex_row = session.exec(
        select(PropertyComplex).where(
            PropertyComplex.brokerage_id == BROKERAGE_ID,
            col(PropertyComplex.name) == SEED_COMPLEX_NAME,
        )
    ).first()
    if complex_row is None:
        complex_row = PropertyComplex(brokerage_id=BROKERAGE_ID, name=SEED_COMPLEX_NAME)
        session.add(complex_row)
        session.flush()

    unit = PropertyUnit(
        brokerage_id=BROKERAGE_ID,
        complex_id=complex_row.id or 0,
        unit_number=unit_number,
    )
    session.add(unit)
    session.flush()
    listing = PropertyListing(brokerage_id=BROKERAGE_ID, unit_id=unit.id or 0)
    session.add(listing)
    session.flush()
    session.commit()
    return unit.id or 0, listing.id or 0


@requires_database
def test_backfill_skips_a_listing_whose_parent_unit_is_deleted() -> None:
    """부모 세대가 삭제된 매물은 접수하지 않는다.

    소프트 삭제는 딸린 매물 행을 건드리지 않으므로 매물의 `is_deleted` 만 보면 살아 있다.
    """
    engine = create_engine(os.environ["TEST_DB_URL"])
    with Session(engine) as session:
        kept_unit, kept_listing = _listing_under_new_unit(session, "1801")
        deleted_unit, deleted_listing = _listing_under_new_unit(session, "1802")

        session.execute(
            text("UPDATE property_unit SET is_deleted = true WHERE id = :i"), {"i": deleted_unit}
        )
        session.commit()

        # 매물 행 자체는 살아 있다. 그래서 매물만 봐서는 걸러지지 않는다.
        survivor = session.get(PropertyListing, deleted_listing)
        assert survivor is not None
        assert survivor.is_deleted is False

        result = backfill_position_cards(
            session, brokerage_id=BROKERAGE_ID, requested_by=USER_ID, dry_run=True
        )
        assert result.listings == 1, "삭제된 세대의 매물이 접수 대상에 남았다"

        targets = set(
            session.exec(
                select(col(PropertyListing.id)).where(
                    col(PropertyListing.id).in_([kept_listing, deleted_listing])
                )
            ).all()
        )
        assert targets == {kept_listing, deleted_listing}
        assert kept_unit != deleted_unit


@requires_database
def test_backfill_queues_a_run_for_a_live_listing_and_is_idempotent() -> None:
    """살아 있는 매물은 접수하고, 다시 돌리면 같은 실행을 재사용한다."""
    engine = create_engine(os.environ["TEST_DB_URL"])
    with Session(engine) as session:
        _listing_under_new_unit(session, "0101")

        first = backfill_position_cards(session, brokerage_id=BROKERAGE_ID, requested_by=USER_ID)
        assert first.queued == 1
        assert first.reused == 0
        assert first.failed == 0

        second = backfill_position_cards(session, brokerage_id=BROKERAGE_ID, requested_by=USER_ID)
        assert second.queued == 0, "같은 앵커를 두 번 접수했다"
        assert second.reused == 1
