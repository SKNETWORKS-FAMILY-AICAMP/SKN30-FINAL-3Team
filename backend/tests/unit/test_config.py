import os
from pathlib import Path

import pytest
from pydantic import ValidationError

import core.config as config_module
from conftest import config_values
from core.config import (
    AppEnvironment,
    DatabaseTarget,
    bind_config,
    load_config,
)
from core.errors import ConfigurationError


def test_environment_values_are_bound_to_group_dtos() -> None:
    config = bind_config(config_values())

    assert config.app.environment is AppEnvironment.TEST
    assert config.db.target is DatabaseTarget.TEST
    assert config.db.pool.size == 5
    assert config.auth.development.enabled is False
    assert config.auth.session.cookie_name == "brokerage_session"
    assert config.auth.session.csrf_cookie_name == "brokerage_csrf"
    assert config.http.cors_allowed_origins == ["http://localhost:5173"]
    assert config.log.level == "INFO"


def test_database_secret_is_masked_in_representation() -> None:
    config = bind_config(config_values())

    assert "postgresql" not in repr(config.db.url)
    assert config.db.url.get_secret_value().startswith("postgresql+psycopg://")


def test_required_value_is_rejected() -> None:
    values = config_values()
    values["DB_URL"] = ""

    with pytest.raises(ConfigurationError, match="DB_URL"):
        bind_config(values)


def test_application_runtime_does_not_require_migration_url() -> None:
    values = config_values()
    values.pop("DB_MIGRATION_URL")

    config = bind_config(values)

    assert config.db.migration_url is None


def test_environment_and_database_target_must_match() -> None:
    values = config_values(APP_ENV="prod", DB_TARGET="development")

    with pytest.raises(ValidationError, match="DB_TARGET=production"):
        bind_config(values)


def test_production_rejects_development_authentication() -> None:
    values = config_values(
        APP_ENV="prod",
        DB_TARGET="production",
        AUTH_DEVELOPMENT_ENABLED="true",
        AUTH_DEVELOPMENT_BROKERAGE_ID="1",
        AUTH_DEVELOPMENT_LOGIN_ID="developer",
    )

    with pytest.raises(ValidationError, match="forbidden in production"):
        bind_config(values)


def test_session_and_csrf_cookie_names_must_differ() -> None:
    values = config_values(
        AUTH_SESSION_COOKIE_NAME="same-cookie",
        AUTH_CSRF_COOKIE_NAME="same-cookie",
    )

    with pytest.raises(ValidationError, match="must use different names"):
        bind_config(values)


def test_local_environment_merges_team_personal_and_process_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".env.local").write_text(
        "\n".join(
            (
                "APP_ENV=local",
                "DB_TARGET=development",
                "DB_URL=postgresql+psycopg://app:team@localhost:5432/brokerage",
                "DB_POOL_SIZE=3",
                "WORKER_ENABLED=false",
                "WORKER_READY_FILE=/tmp/team-worker-ready",
                "",
            )
        ),
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "\n".join(
            (
                "DB_URL=postgresql+psycopg://app:personal@localhost:5432/brokerage",
                "DB_POOL_SIZE=7",
                "WORKER_ENABLED=true",
                "",
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "BACKEND_ROOT", tmp_path)

    config = load_config(
        AppEnvironment.LOCAL,
        environ={
            "DB_URL": "postgresql+psycopg://app:process@localhost:5432/brokerage",
            "DB_POOL_SIZE": "11",
        },
    )

    assert config.app.environment is AppEnvironment.LOCAL
    assert (
        config.db.url.get_secret_value()
        == "postgresql+psycopg://app:process@localhost:5432/brokerage"
    )
    assert config.db.pool.size == 11
    assert config.worker.enabled is True
    assert config.worker.ready_file == Path("/tmp/team-worker-ready")


def test_local_dotenv_loading_is_literal_and_does_not_mutate_process_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".env.local").write_text(
        "\n".join(
            (
                "APP_ENV=local",
                "DB_TARGET=development",
                "DB_URL=postgresql+psycopg://app:team@localhost:5432/brokerage",
                "WORKER_ID=${CONFIG_DOTENV_SENTINEL}",
                "CONFIG_DOTENV_SENTINEL=must-not-leak",
                "",
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "BACKEND_ROOT", tmp_path)
    monkeypatch.delenv("CONFIG_DOTENV_SENTINEL", raising=False)

    config = load_config(AppEnvironment.LOCAL, environ={})

    assert config.worker.worker_id == "${CONFIG_DOTENV_SENTINEL}"
    assert "CONFIG_DOTENV_SENTINEL" not in os.environ


@pytest.mark.parametrize(
    ("environment", "values"),
    (
        (AppEnvironment.TEST, config_values()),
        (
            AppEnvironment.PROD,
            config_values(APP_ENV="prod", DB_TARGET="production"),
        ),
    ),
)
def test_non_local_environments_do_not_read_dotenv(
    environment: AppEnvironment,
    values: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".env.local").write_text(
        "DB_URL=postgresql+psycopg://app:team@localhost:5432/brokerage\n",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "DB_URL=postgresql+psycopg://app:personal@localhost:5432/brokerage\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "BACKEND_ROOT", tmp_path)
    values.pop("DB_URL")

    with pytest.raises(ConfigurationError, match="DB_URL"):
        load_config(environment, environ=values)


def test_app_env_selects_environment() -> None:
    config = load_config(environ=config_values())

    assert config.app.environment is AppEnvironment.TEST


def test_explicit_environment_must_match_app_env() -> None:
    with pytest.raises(ConfigurationError, match="selected environment and APP_ENV must match"):
        load_config(AppEnvironment.LOCAL, environ=config_values())


def test_invalid_app_env_is_rejected_before_binding() -> None:
    with pytest.raises(ConfigurationError, match="APP_ENV must be local, test, or prod"):
        load_config(environ=config_values(APP_ENV="preview"))


def test_worker_settings_use_the_same_validated_mapping() -> None:
    config = bind_config(
        config_values(
            WORKER_ENABLED="true",
            WORKER_READY_FILE="/tmp/nondefault-worker-ready",
            WORKER_ID="configured-worker",
        )
    )

    assert config.worker.enabled is True
    assert config.worker.ready_file == Path("/tmp/nondefault-worker-ready")
    assert config.worker.worker_id == "configured-worker"


def test_f2_has_no_feature_flag_and_keeps_request_limits() -> None:
    config = bind_config(
        config_values(
            F2_MAX_AUDIO_BYTES="1024",
        )
    )

    assert not hasattr(config.f2, "enabled")
    assert config.f2.max_audio_bytes == 1024


@pytest.mark.parametrize(
    ("name", "value", "message"),
    (
        ("WORKER_ENABLED", "sometimes", "WORKER_ENABLED"),
        ("WORKER_READY_FILE", "relative/worker-ready", "absolute path"),
    ),
)
def test_invalid_worker_settings_fail_fast(name: str, value: str, message: str) -> None:
    with pytest.raises((ConfigurationError, ValidationError), match=message):
        bind_config(config_values(**{name: value}))
