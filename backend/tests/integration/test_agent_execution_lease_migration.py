"""migration 011을 기존 데이터가 있는 DB에 전진 적용하는 검증.

빈 DB에 001~011을 한 번에 거는 것으로는 부족하다. 011은 이미 `agent_run` 행이 쌓인 환경에
적용되며, `status` 컬럼 타입을 바꾸고 `NOT NULL DEFAULT 0` 컬럼과 CHECK 제약을 함께 넣는다.
기존 행이 그 제약을 만족하지 못하면 적용 시점에 실패한다.

그래서 여기서는 001~010만 적용한 격리된 DB를 만들어 행을 넣고, 011만 따로 적용한다.
공유 개발 DB는 건드리지 않는다. `TEST_DB_URL`이 가리키는 서버에 임시 DB를 만들고 결과와
무관하게 지운다.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from yoyo import get_backend, read_migrations

MIGRATION_DIRECTORY = Path(__file__).resolve().parents[3] / "docs" / "db" / "migrate"

requires_database = pytest.mark.skipif(
    not os.getenv("TEST_DB_URL"),
    reason="TEST_DB_URL is required for PostgreSQL integration tests",
)


def url_with_database(url: str, database: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{database}", parts.query, parts.fragment))


@contextmanager
def isolated_migration_database() -> Iterator[str]:
    """001~010만 적용한 임시 DB. 이름은 매번 새로 만들고 끝나면 반드시 지운다."""
    base_url = os.environ["TEST_DB_URL"]
    name = f"brokerage_lease_migration_{uuid4().hex[:12]}"
    admin_url = url_with_database(base_url, "postgres")
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            try:
                connection.execute(text(f'CREATE DATABASE "{name}"'))
            except ProgrammingError as error:  # 권한이 없으면 우회하지 않고 건너뛴다.
                pytest.skip(f"cannot create a temporary database for migration testing: {error}")
        try:
            yield url_with_database(base_url, name)
        finally:
            with admin.connect() as connection:
                connection.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
                        " WHERE datname = :name AND pid <> pg_backend_pid()"
                    ),
                    {"name": name},
                )
                connection.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
    finally:
        admin.dispose()


def apply_through(url: str, last_id_prefix: str) -> None:
    """번호 접두사가 `last_id_prefix` 이하인 migration까지만 순서대로 적용한다.

    이미 적용된 파일은 `to_apply`가 걸러내므로 010까지 올린 DB에 다시 부르면 011만 실행된다.
    """
    migrations = read_migrations(str(MIGRATION_DIRECTORY))
    selected = migrations[: [m.id[:3] for m in migrations].index(last_id_prefix) + 1]
    backend = get_backend(url)
    with backend.lock():
        backend.apply_migrations(backend.to_apply(selected))


def seed_existing_run(connection: Connection) -> int:
    """011 이전 스키마의 실행 1건. 011이 보존해야 할 기존 데이터다."""
    brokerage_id = connection.execute(
        text("INSERT INTO brokerage (name) VALUES ('이관 검증 사무소') RETURNING id")
    ).scalar_one()
    user_id = connection.execute(
        text(
            "INSERT INTO app_user (brokerage_id, login_id, password_hash, display_name, role)"
            " VALUES (:b, 'migration', 'unused', '검증', 'OWNER') RETURNING id"
        ),
        {"b": brokerage_id},
    ).scalar_one()
    return connection.execute(
        text(
            "INSERT INTO agent_run (brokerage_id, run_group_id, run_type, agent_type, status,"
            " trigger_type, requested_by)"
            " VALUES (:b, :g, 'CROSS_JUDGMENT', 'BROKERAGE_WORKFLOW', 'RUNNING', 'USER_REQUEST',"
            " :u) RETURNING id"
        ),
        {"b": brokerage_id, "g": str(uuid4()), "u": user_id},
    ).scalar_one()


@requires_database
def test_migration_011_upgrades_a_database_that_already_holds_agent_runs() -> None:
    with isolated_migration_database() as url:
        apply_through(url, "010")
        engine = create_engine(url)
        try:
            with engine.begin() as connection:
                run_id = seed_existing_run(connection)
                assert (
                    connection.execute(
                        text(
                            "SELECT character_maximum_length FROM information_schema.columns"
                            " WHERE table_name = 'agent_run' AND column_name = 'status'"
                        )
                    ).scalar_one()
                    == 20
                )

            apply_through(url, "011")

            with engine.connect() as connection:
                stored = (
                    connection.execute(
                        text(
                            "SELECT status, attempt_count, lease_owner, lease_expires_at"
                            " FROM agent_run WHERE id = :i"
                        ),
                        {"i": run_id},
                    )
                    .mappings()
                    .one()
                )
                # 기존 행과 상태값이 살아남아야 한다.
                assert stored["status"] == "RUNNING"
                # 새 컬럼은 안전한 기본값으로 채워진다.
                assert stored["attempt_count"] == 0
                assert stored["lease_owner"] is None
                assert stored["lease_expires_at"] is None

                assert (
                    connection.execute(
                        text(
                            "SELECT character_maximum_length FROM information_schema.columns"
                            " WHERE table_name = 'agent_run' AND column_name = 'status'"
                        )
                    ).scalar_one()
                    == 30
                )
                claim_index = (
                    connection.execute(
                        text(
                            "SELECT pg_get_indexdef(i.indexrelid) AS definition,"
                            " pg_get_expr(i.indpred, i.indrelid) AS predicate"
                            " FROM pg_index i"
                            " JOIN pg_class index_class ON index_class.oid = i.indexrelid"
                            " JOIN pg_class table_class ON table_class.oid = i.indrelid"
                            " WHERE table_class.relname = 'agent_run'"
                            " AND index_class.relname = 'idx_agent_run_claim_queue'"
                        )
                    )
                    .mappings()
                    .one()
                )
                assert "(created_at, id)" in claim_index["definition"]
                predicate = claim_index["predicate"]
                assert predicate is not None
                for expected in (
                    "parent_run_id IS NULL",
                    "run_type",
                    "CROSS_JUDGMENT",
                    "status",
                    "QUEUED",
                    "RUNNING",
                ):
                    assert expected in predicate

            with engine.begin() as connection:
                # 21자 상태값이 잘리지 않고 왕복해야 lease 이후 단계를 저장할 수 있다.
                connection.execute(
                    text("UPDATE agent_run SET status = 'CANDIDATE_CARDS_READY' WHERE id = :i"),
                    {"i": run_id},
                )
                assert (
                    connection.execute(
                        text("SELECT status FROM agent_run WHERE id = :i"), {"i": run_id}
                    ).scalar_one()
                    == "CANDIDATE_CARDS_READY"
                )

            with engine.begin() as connection:
                with pytest.raises(IntegrityError) as negative:
                    connection.execute(
                        text("UPDATE agent_run SET attempt_count = -1 WHERE id = :i"),
                        {"i": run_id},
                    )
                assert "ck_agent_run_attempt_count_not_negative" in str(negative.value)
        finally:
            engine.dispose()


@requires_database
def test_migration_012_adds_the_price_table_to_a_database_that_already_holds_cards() -> None:
    """011 까지 올라간 DB 에 카드가 이미 있어도 012 가 전진 적용되고 데이터가 보존된다."""
    with isolated_migration_database() as url:
        apply_through(url, "011")
        engine = create_engine(url)
        try:
            with engine.begin() as connection:
                run_id = seed_existing_run(connection)
                brokerage_id = connection.execute(
                    text("SELECT brokerage_id FROM agent_run WHERE id = :i"), {"i": run_id}
                ).scalar_one()
                complex_id = connection.execute(
                    text(
                        "INSERT INTO property_complex (brokerage_id, name)"
                        " VALUES (:b, '이관 검증 단지') RETURNING id"
                    ),
                    {"b": brokerage_id},
                ).scalar_one()
                unit_id = connection.execute(
                    text(
                        "INSERT INTO property_unit (brokerage_id, complex_id, unit_number)"
                        " VALUES (:b, :c, '101') RETURNING id"
                    ),
                    {"b": brokerage_id, "c": complex_id},
                ).scalar_one()
                listing_id = connection.execute(
                    text(
                        "INSERT INTO property_listing (brokerage_id, unit_id)"
                        " VALUES (:b, :u) RETURNING id"
                    ),
                    {"b": brokerage_id, "u": unit_id},
                ).scalar_one()
                analysis_id = connection.execute(
                    text(
                        "INSERT INTO negotiation_position_analysis (brokerage_id, agent_run_id,"
                        " negotiation_side, cache_key, data_version, unit_id, listing_id)"
                        " VALUES (:b, :r, 'LISTING', 'position-card:v2:existing', 1, :u, :l)"
                        " RETURNING id"
                    ),
                    {"b": brokerage_id, "r": run_id, "u": unit_id, "l": listing_id},
                ).scalar_one()
                assert (
                    connection.execute(
                        text(
                            "SELECT count(*) FROM information_schema.tables"
                            " WHERE table_name = 'negotiation_position_price'"
                        )
                    ).scalar_one()
                    == 0
                )

            apply_through(url, "012")

            with engine.connect() as connection:
                # 기존 카드가 살아남아야 한다.
                assert (
                    connection.execute(
                        text("SELECT cache_key FROM negotiation_position_analysis WHERE id = :i"),
                        {"i": analysis_id},
                    ).scalar_one()
                    == "position-card:v2:existing"
                )
                comments = connection.execute(
                    text(
                        "SELECT count(*) FROM pg_description d"
                        " JOIN pg_class c ON c.oid = d.objoid"
                        " WHERE c.relname = 'negotiation_position_price'"
                    )
                ).scalar_one()
                # 테이블 1개 + 컬럼 10개.
                assert comments == 11
                constraints = set(
                    connection.execute(
                        text(
                            "SELECT conname FROM pg_constraint"
                            " WHERE conrelid = 'negotiation_position_price'::regclass"
                        )
                    ).scalars()
                )
                assert {
                    "fk_position_price_analysis",
                    "uq_position_price_kind",
                    "ck_position_price_amounts_not_negative",
                    "ck_position_price_monthly_requires_monthly_rent",
                } <= constraints
                assert (
                    connection.execute(
                        text(
                            "SELECT count(*) FROM pg_indexes"
                            " WHERE indexname = 'idx_position_price_analysis'"
                        )
                    ).scalar_one()
                    == 1
                )

            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO negotiation_position_price (brokerage_id,"
                        " position_analysis_id, price_kind, stated_amount)"
                        " SELECT brokerage_id, id, 'SALE', 2880000000"
                        " FROM negotiation_position_analysis WHERE id = :i"
                    ),
                    {"i": analysis_id},
                )

            for sql, violated in (
                (
                    "INSERT INTO negotiation_position_price (brokerage_id, position_analysis_id,"
                    " price_kind, stated_amount) SELECT brokerage_id, id, 'SALE', 1"
                    " FROM negotiation_position_analysis WHERE id = :i",
                    "uq_position_price_kind",
                ),
                (
                    "INSERT INTO negotiation_position_price (brokerage_id, position_analysis_id,"
                    " price_kind, stated_amount) SELECT brokerage_id, id, 'JEONSE', -1"
                    " FROM negotiation_position_analysis WHERE id = :i",
                    "ck_position_price_amounts_not_negative",
                ),
                (
                    "INSERT INTO negotiation_position_price (brokerage_id, position_analysis_id,"
                    " price_kind, stated_monthly_amount) SELECT brokerage_id, id, 'JEONSE', 1"
                    " FROM negotiation_position_analysis WHERE id = :i",
                    "ck_position_price_monthly_requires_monthly_rent",
                ),
            ):
                with engine.begin() as connection:  # noqa: SIM117 - 제약마다 새 transaction 이 필요하다
                    with pytest.raises(IntegrityError) as rejected:
                        connection.execute(text(sql), {"i": analysis_id})
                    assert violated in str(rejected.value)
        finally:
            engine.dispose()


@requires_database
def test_migration_013_extends_the_claim_index_for_anchor_ready_recovery() -> None:
    with isolated_migration_database() as url:
        apply_through(url, "012")
        engine = create_engine(url)
        try:
            with engine.connect() as connection:
                before = connection.execute(
                    text(
                        "SELECT indexdef FROM pg_indexes"
                        " WHERE indexname = 'idx_agent_run_claim_queue'"
                    )
                ).scalar_one()
                assert "ANCHOR_READY" not in before

            apply_through(url, "013")

            with engine.connect() as connection:
                after = connection.execute(
                    text(
                        "SELECT indexdef FROM pg_indexes"
                        " WHERE indexname = 'idx_agent_run_claim_queue'"
                    )
                ).scalar_one()
                assert "ANCHOR_READY" in after
                assert "QUEUED" in after
                assert "RUNNING" in after
        finally:
            engine.dispose()


@requires_database
def test_migration_014_extends_the_claim_index_for_candidates_ready_recovery() -> None:
    with isolated_migration_database() as url:
        apply_through(url, "013")
        engine = create_engine(url)
        try:
            with engine.connect() as connection:
                before = connection.execute(
                    text(
                        "SELECT indexdef FROM pg_indexes"
                        " WHERE indexname = 'idx_agent_run_claim_queue'"
                    )
                ).scalar_one()
                assert "ANCHOR_READY" in before
                assert "CANDIDATES_READY" not in before

            apply_through(url, "014")

            with engine.connect() as connection:
                after = connection.execute(
                    text(
                        "SELECT indexdef FROM pg_indexes"
                        " WHERE indexname = 'idx_agent_run_claim_queue'"
                    )
                ).scalar_one()
                for expected in ("QUEUED", "RUNNING", "ANCHOR_READY", "CANDIDATES_READY"):
                    assert expected in after
        finally:
            engine.dispose()


@requires_database
def test_migration_015_extends_the_claim_index_for_candidate_cards_ready_recovery() -> None:
    with isolated_migration_database() as url:
        apply_through(url, "014")
        engine = create_engine(url)
        try:
            with engine.connect() as connection:
                before = connection.execute(
                    text(
                        "SELECT indexdef FROM pg_indexes"
                        " WHERE indexname = 'idx_agent_run_claim_queue'"
                    )
                ).scalar_one()
                assert "CANDIDATES_READY" in before
                assert "CANDIDATE_CARDS_READY" not in before

            apply_through(url, "015")

            with engine.connect() as connection:
                after = connection.execute(
                    text(
                        "SELECT indexdef FROM pg_indexes"
                        " WHERE indexname = 'idx_agent_run_claim_queue'"
                    )
                ).scalar_one()
                for expected in (
                    "QUEUED",
                    "RUNNING",
                    "ANCHOR_READY",
                    "CANDIDATES_READY",
                    "CANDIDATE_CARDS_READY",
                ):
                    assert expected in after
        finally:
            engine.dispose()
