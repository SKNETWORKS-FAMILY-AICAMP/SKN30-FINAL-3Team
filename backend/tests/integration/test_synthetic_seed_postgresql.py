"""F3 합성 seed 관리 명령의 실제 PostgreSQL 실행 경계를 검증한다.

공유 DB는 건드리지 않는다. ``TEST_DB_URL``과 같은 서버에 임시 DB를 만들고 migration을
적용한 뒤, 각 모델 프로필 seed를 두 번 실행해 반복 가능성과 30개 검증을 확인하고 임시 DB를 제거한다.
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

MODEL_PROFILES = {
    "local-openai": (
        "openai",
        "gpt-5.6-luna",
        None,
        None,
    ),
    "dev-bedrock-gpt56-luna": (
        "bedrock",
        "global.openai.gpt-5.6-luna",
        None,
        "general-dev-bedrock",
    ),
    "dev-qwen38-vllm-bnb": (
        "vllm",
        "unsloth/Qwen3.8-27B-unsloth-bnb-4bit",
        "8aa5f05d26b7205477066e1449e0af13f762a299",
        "general-dev-gpu",
    ),
    "dev-qwen38-llamacpp-gguf": (
        "llama_cpp",
        "unsloth/Qwen3.8-27B-GGUF:UD-Q4_K_M",
        "4ca720788d1e01f1bff70c033e0d0028fd02e502@sha256:322e194ff79741c7baa497c240f677f54b201b0efab44ca8e50f122b39123482",
        "general-dev-gpu",
    ),
}


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
@pytest.mark.parametrize(("model_profile", "expected"), MODEL_PROFILES.items())
def test_f3_synthetic_seed_is_repeatable_on_postgresql(
    make_config, model_profile: str, expected: tuple[str, str, str | None, str | None]
) -> None:
    with _isolated_database(os.environ["TEST_DB_URL"]) as database_url:
        config = make_config(
            {
                "APP_ENV": "local",
                "DB_TARGET": "development",
                "DB_URL": database_url,
                "DB_MIGRATION_URL": database_url,
            }
        )

        first = seed_f3_synthetic(config, confirm_reset=True, model_profile=model_profile)
        second = seed_f3_synthetic(config, confirm_reset=True, model_profile=model_profile)

        assert first.verification_checks == EXPECTED_VERIFICATION_CHECKS
        assert second.verification_checks == EXPECTED_VERIFICATION_CHECKS
        assert second.brokerage_id == first.brokerage_id
        assert second.user_id == first.user_id
        assert second.login_id == "f3_synthetic_dev"

        engine = create_engine(database_url)
        try:
            with engine.connect() as connection:
                rows = (
                    connection.execute(
                        text(
                            "SELECT capability, config_key, provider, model_name, model_version,"
                            " endpoint_alias, config_version, parameters, is_active"
                            " FROM ai_model_config WHERE brokerage_id = :brokerage_id"
                            " ORDER BY capability"
                        ),
                        {"brokerage_id": second.brokerage_id},
                    )
                    .mappings()
                    .all()
                )
        finally:
            engine.dispose()

        assert [row["capability"] for row in rows] == [
            "BROKERAGE_JUDGMENT",
            "POSITION_CARD",
        ]
        assert all(row["config_key"] == model_profile for row in rows)
        assert all(
            (
                row["provider"],
                row["model_name"],
                row["model_version"],
                row["endpoint_alias"],
            )
            == expected
            for row in rows
        )
        assert all(row["config_version"] == 1 for row in rows)
        assert all(row["parameters"] == {} for row in rows)
        assert all(row["is_active"] is True for row in rows)
