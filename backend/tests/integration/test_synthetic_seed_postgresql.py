"""F3 합성 seed 관리 명령의 실제 PostgreSQL 실행 경계를 검증한다.

공유 DB는 건드리지 않는다. ``TEST_DB_URL``과 같은 서버에 임시 DB를 만들고 migration을
적용한 뒤, seed를 두 번 실행해 반복 가능성과 29개 검증을 확인하고 임시 DB를 제거한다.
"""

from __future__ import annotations

import ipaddress
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError
from yoyo import get_backend, read_migrations

from synthetic_seed import EXPECTED_VERIFICATION_CHECKS, seed_f3_synthetic

MIGRATION_DIRECTORY = Path(__file__).resolve().parents[3] / "docs" / "db" / "migrate"


def _url_with_database(url: str, database: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{database}", parts.query, parts.fragment))


def _has_loopback_host(url: str) -> bool:
    host = urlsplit(url).hostname
    if host is None:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@contextmanager
def _isolated_database(base_url: str) -> Iterator[str]:
    if not _has_loopback_host(base_url):
        pytest.skip("F3 synthetic seed only accepts a loopback TEST_DB_URL")

    database_name = f"brokerage_f3_seed_{uuid4().hex[:12]}"
    admin = create_engine(
        _url_with_database(base_url, "postgres"),
        isolation_level="AUTOCOMMIT",
    )
    database_created = False
    try:
        with admin.connect() as connection:
            try:
                connection.execute(text(f'CREATE DATABASE "{database_name}"'))
            except ProgrammingError as error:
                pytest.skip(f"cannot create a temporary database for seed testing: {error}")
        database_created = True

        database_url = _url_with_database(base_url, database_name)
        migrations = read_migrations(str(MIGRATION_DIRECTORY))
        migration_backend = get_backend(database_url)
        with migration_backend.lock():
            migration_backend.apply_migrations(migration_backend.to_apply(migrations))

        yield database_url
    finally:
        try:
            if database_created:
                with admin.connect() as connection:
                    connection.execute(
                        text(
                            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
                            " WHERE datname = :name AND pid <> pg_backend_pid()"
                        ),
                        {"name": database_name},
                    )
                    connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
        finally:
            admin.dispose()


@pytest.mark.skipif(
    not os.getenv("TEST_DB_URL"),
    reason="TEST_DB_URL is required for PostgreSQL integration tests",
)
def test_f3_synthetic_seed_is_repeatable_on_postgresql(make_config) -> None:
    with _isolated_database(os.environ["TEST_DB_URL"]) as database_url:
        config = make_config(
            {
                "APP_ENV": "local",
                "DB_TARGET": "development",
                "DB_URL": database_url,
                "DB_MIGRATION_URL": database_url,
            }
        )

        first = seed_f3_synthetic(config, confirm_reset=True)
        second = seed_f3_synthetic(config, confirm_reset=True)

        assert first.verification_checks == EXPECTED_VERIFICATION_CHECKS
        assert second.verification_checks == EXPECTED_VERIFICATION_CHECKS
        assert second.brokerage_id == first.brokerage_id
        assert second.user_id == first.user_id
        assert second.login_id == "f3_synthetic_dev"
