import json
import sys
from pathlib import Path
from typing import Any

import pytest

import manage
from synthetic_seed import (
    EXPECTED_VERIFICATION_CHECKS,
    F3_MODEL_PROFILES,
    SyntheticSeedError,
    SyntheticSeedResult,
    model_profile_path,
    read_psql_script,
    require_local_seed_target,
    seed_f3_synthetic,
    validate_selected_profile,
    validate_verification_rows,
)


def local_config(make_config, url: str):
    return make_config(
        {
            "APP_ENV": "local",
            "DB_TARGET": "development",
            "DB_URL": url,
        }
    )


def passing_rows() -> list[tuple[str, int, int, str]]:
    return [(f"check-{index}", 0, 0, "PASS") for index in range(EXPECTED_VERIFICATION_CHECKS)]


def test_f3_synthetic_seed_remains_local_only(make_config) -> None:
    config = make_config({"APP_ENV": "dev", "DB_TARGET": "development"})

    with pytest.raises(SyntheticSeedError, match="APP_ENV=local"):
        require_local_seed_target(config)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://app:test@localhost:5432/brokerage",
        "postgresql+psycopg://app:test@127.0.0.1:5432/brokerage",
        "postgresql+psycopg://app:test@[::1]:5432/brokerage",
    ],
)
def test_f3_synthetic_seed_accepts_loopback_database(make_config, url: str) -> None:
    require_local_seed_target(local_config(make_config, url))


def test_f3_synthetic_seed_rejects_remote_database_even_in_local_profile(make_config) -> None:
    config = local_config(
        make_config,
        "postgresql+psycopg://app:test@dev-db.example.com:5432/brokerage",
    )

    with pytest.raises(SyntheticSeedError, match="loopback"):
        require_local_seed_target(config)


def test_psql_script_reader_removes_only_supported_meta_command(tmp_path: Path) -> None:
    path = tmp_path / "seed.sql"
    path.write_text("\\set ON_ERROR_STOP on\nBEGIN;\nSELECT 1;\nCOMMIT;\n", encoding="utf-8")

    assert read_psql_script(path) == "BEGIN;\nSELECT 1;\nCOMMIT;\n"


def test_psql_script_reader_rejects_unknown_meta_command(tmp_path: Path) -> None:
    path = tmp_path / "seed.sql"
    path.write_text("\\i arbitrary.sql\n", encoding="utf-8")

    with pytest.raises(SyntheticSeedError, match="unsupported psql command"):
        read_psql_script(path)


def test_verification_requires_exactly_30_passes() -> None:
    validate_verification_rows(passing_rows())

    with pytest.raises(SyntheticSeedError, match="expected 30 checks"):
        validate_verification_rows(passing_rows()[:-1])


def test_verification_reports_failed_check() -> None:
    rows = passing_rows()
    rows[3] = ("privacy-check", 0, 1, "FAIL")

    with pytest.raises(SyntheticSeedError, match="privacy-check"):
        validate_verification_rows(rows)


def test_verification_requires_the_selected_profile() -> None:
    validate_selected_profile([("local-openai",)], "local-openai")

    with pytest.raises(SyntheticSeedError, match="selected model profile"):
        validate_selected_profile(
            [("dev-bedrock-gpt56-luna",)],
            "local-openai",
        )


def test_model_profile_path_accepts_only_the_fixed_allowlist() -> None:
    assert tuple(F3_MODEL_PROFILES) == (
        "local-openai",
        "dev-bedrock-gpt56-luna",
        "dev-qwen38-vllm-bnb",
        "dev-qwen38-llamacpp-gguf",
    )
    assert model_profile_path("local-openai").name == "local-openai.sql"

    with pytest.raises(SyntheticSeedError, match="unsupported.*profile"):
        model_profile_path("../../../arbitrary")


class FakeCursor:
    def __init__(
        self, *, rows: list[tuple[Any, ...]] | None = None, row: tuple[Any, ...] | None = None
    ):
        self.rows = rows or []
        self.row = row

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.row


class FakeConnection:
    def __init__(self) -> None:
        self.scripts: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(
        self,
        query: str,
        params: tuple[object, ...] | None = None,
        *,
        prepare: bool | None = None,
    ) -> FakeCursor:
        assert prepare is False
        if params is not None:
            if "SELECT DISTINCT c.config_key" in query:
                return FakeCursor(rows=[("local-openai",)])
            return FakeCursor(row=(7, 11, "f3_synthetic_dev"))
        self.scripts.append(query)
        if query == "VERIFY\n":
            return FakeCursor(rows=passing_rows())
        return FakeCursor()


def test_seed_runs_fixed_scripts_in_order_and_returns_identity(make_config, tmp_path: Path) -> None:
    paths = []
    for name, content in (
        ("reset.sql", "RESET\n"),
        ("seed.sql", "SEED\n"),
        ("profile.sql", "PROFILE\n"),
        ("verify.sql", "VERIFY\n"),
    ):
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")
        paths.append(path)

    connection = FakeConnection()
    connect_calls: list[tuple[str, bool]] = []

    def connect(url: str, *, autocommit: bool):
        connect_calls.append((url, autocommit))
        return connection

    result = seed_f3_synthetic(
        local_config(
            make_config,
            "postgresql+psycopg://app:test@127.0.0.1:5432/brokerage",
        ),
        confirm_reset=True,
        model_profile="local-openai",
        connector=connect,
        script_paths=tuple(paths),
    )

    assert connect_calls == [("postgresql://app:test@127.0.0.1:5432/brokerage", True)]
    assert connection.scripts == ["RESET\n", "SEED\n", "PROFILE\n", "VERIFY\n"]
    assert result.brokerage_id == 7
    assert result.user_id == 11
    assert result.login_id == "f3_synthetic_dev"
    assert result.verification_checks == EXPECTED_VERIFICATION_CHECKS


def test_seed_requires_explicit_reset_confirmation(make_config) -> None:
    config = local_config(
        make_config,
        "postgresql+psycopg://app:test@127.0.0.1:5432/brokerage",
    )

    with pytest.raises(SyntheticSeedError, match="--confirm-reset"):
        seed_f3_synthetic(config, confirm_reset=False, model_profile="local-openai")


def test_manage_exposes_local_f3_synthetic_seed_command() -> None:
    arguments = manage.build_parser().parse_args(
        [
            "seed-f3-synthetic",
            "--confirm-reset",
            "--model-profile",
            "local-openai",
        ]
    )

    assert arguments.command == "seed-f3-synthetic"
    assert arguments.confirm_reset is True
    assert arguments.model_profile == "local-openai"


def test_manage_rejects_unknown_f3_model_profile() -> None:
    with pytest.raises(SystemExit):
        manage.build_parser().parse_args(
            [
                "seed-f3-synthetic",
                "--confirm-reset",
                "--model-profile",
                "arbitrary-provider",
            ]
        )

    with pytest.raises(SystemExit):
        manage.build_parser().parse_args(["seed-f3-synthetic", "--confirm-reset"])

    with pytest.raises(SystemExit):
        manage.build_parser().parse_args(
            [
                "seed-f3-synthetic",
                "--confirm-reset",
                "--model-profile",
                "local-openai",
                "--sql-path",
                "arbitrary.sql",
            ]
        )


def test_manage_prints_seed_identity_as_json(
    make_config, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = local_config(
        make_config,
        "postgresql+psycopg://app:test@127.0.0.1:5432/brokerage",
    )
    calls: list[tuple[object, bool, str]] = []

    def run_seed(resolved_config, *, confirm_reset: bool, model_profile: str):
        calls.append((resolved_config, confirm_reset, model_profile))
        return SyntheticSeedResult(
            brokerage_id=7,
            user_id=11,
            login_id="f3_synthetic_dev",
            verification_checks=EXPECTED_VERIFICATION_CHECKS,
        )

    monkeypatch.setattr(manage, "get_config", lambda: config)
    monkeypatch.setattr(manage, "seed_f3_synthetic", run_seed)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "manage.py",
            "seed-f3-synthetic",
            "--confirm-reset",
            "--model-profile",
            "local-openai",
        ],
    )

    manage.main()

    assert calls == [(config, True, "local-openai")]
    assert json.loads(capsys.readouterr().out) == {
        "brokerage_id": 7,
        "user_id": 11,
        "login_id": "f3_synthetic_dev",
        "verification_checks": EXPECTED_VERIFICATION_CHECKS,
    }
