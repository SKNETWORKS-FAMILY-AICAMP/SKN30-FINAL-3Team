"""F3 실행 접수 재사용의 PostgreSQL 동시성 검증."""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import text
from sqlmodel import Session, create_engine

from domain.agent_execution import service
from domain.agent_execution.models import AnchorType

requires_database = pytest.mark.skipif(
    not os.getenv("TEST_DB_URL"),
    reason="TEST_DB_URL is required for PostgreSQL integration tests",
)


@contextmanager
def committed_listing() -> Iterator[tuple[int, int, int]]:
    """서로 다른 접수 연결이 볼 수 있는 커밋된 사무소·사용자·매물을 만든다."""
    engine = create_engine(os.environ["TEST_DB_URL"])
    brokerage_id: int | None = None
    unit_id: int | None = None
    complex_id: int | None = None
    try:
        with Session(engine) as setup:
            created_brokerage_id = setup.execute(
                text("INSERT INTO brokerage (name) VALUES ('동시접수 사무소') RETURNING id")
            ).scalar_one()
            brokerage_id = created_brokerage_id
            user_id = setup.execute(
                text(
                    "INSERT INTO app_user (brokerage_id, login_id, password_hash,"
                    " display_name, role) VALUES (:b, :login, 'unused', '접수검증', 'OWNER')"
                    " RETURNING id"
                ),
                {"b": created_brokerage_id, "login": f"intake-{created_brokerage_id}"},
            ).scalar_one()
            created_complex_id = setup.execute(
                text(
                    "INSERT INTO property_complex (brokerage_id, name)"
                    " VALUES (:b, '동시접수단지') RETURNING id"
                ),
                {"b": created_brokerage_id},
            ).scalar_one()
            complex_id = created_complex_id
            created_unit_id = setup.execute(
                text(
                    "INSERT INTO property_unit (brokerage_id, complex_id, unit_number)"
                    " VALUES (:b, :c, '101') RETURNING id"
                ),
                {"b": created_brokerage_id, "c": created_complex_id},
            ).scalar_one()
            unit_id = created_unit_id
            listing_id = setup.execute(
                text(
                    "INSERT INTO property_listing (brokerage_id, unit_id, is_sale_available,"
                    " sale_price) VALUES (:b, :u, true, 2880000000) RETURNING id"
                ),
                {"b": created_brokerage_id, "u": created_unit_id},
            ).scalar_one()
            setup.commit()

        yield created_brokerage_id, user_id, listing_id
    finally:
        if brokerage_id is not None:
            with Session(engine) as cleanup:
                cleanup.execute(
                    text("DELETE FROM agent_run WHERE brokerage_id = :b"),
                    {"b": brokerage_id},
                )
                cleanup.execute(
                    text("DELETE FROM property_listing WHERE brokerage_id = :b"),
                    {"b": brokerage_id},
                )
                if unit_id is not None:
                    cleanup.execute(
                        text("DELETE FROM property_unit WHERE id = :id"), {"id": unit_id}
                    )
                if complex_id is not None:
                    cleanup.execute(
                        text("DELETE FROM property_complex WHERE id = :id"),
                        {"id": complex_id},
                    )
                cleanup.execute(
                    text("DELETE FROM app_user WHERE brokerage_id = :b"), {"b": brokerage_id}
                )
                cleanup.execute(text("DELETE FROM brokerage WHERE id = :b"), {"b": brokerage_id})
                cleanup.commit()
        engine.dispose()


@requires_database
def test_parallel_intakes_return_one_active_run() -> None:
    """API 인스턴스에 해당하는 독립 연결 네 개가 동시에 접수해도 실행은 하나다."""
    worker_count = 4
    with committed_listing() as (brokerage_id, user_id, listing_id):
        barrier = threading.Barrier(worker_count)
        run_ids: list[int] = []
        failures: list[BaseException] = []
        result_lock = threading.Lock()

        def intake() -> None:
            engine = create_engine(os.environ["TEST_DB_URL"])
            try:
                with Session(engine) as session:
                    barrier.wait(timeout=10)
                    run = service.queue_cross_judgment_run(
                        session,
                        brokerage_id,
                        user_id,
                        AnchorType.LISTING,
                        listing_id,
                    )
                    assert run.id is not None
                    with result_lock:
                        run_ids.append(run.id)
            except BaseException as error:  # noqa: BLE001 - 스레드 실패를 본 스레드로 전달
                with result_lock:
                    failures.append(error)
            finally:
                engine.dispose()

        threads = [threading.Thread(target=intake) for _ in range(worker_count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert all(not thread.is_alive() for thread in threads)
        assert failures == []
        assert len(run_ids) == worker_count
        assert len(set(run_ids)) == 1

        engine = create_engine(os.environ["TEST_DB_URL"])
        try:
            with Session(engine) as verify:
                count = verify.execute(
                    text(
                        "SELECT count(*) FROM agent_run WHERE brokerage_id = :b"
                        " AND target_listing_id = :listing"
                    ),
                    {"b": brokerage_id, "listing": listing_id},
                ).scalar_one()
                assert count == 1
        finally:
            engine.dispose()
