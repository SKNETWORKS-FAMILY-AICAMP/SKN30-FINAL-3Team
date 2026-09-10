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


def test_dev_environment_requires_development_database_and_secure_cookies() -> None:
    config = bind_config(config_values(APP_ENV="dev", DB_TARGET="development"))

    assert config.app.environment is AppEnvironment.DEV
    assert config.db.target is DatabaseTarget.DEVELOPMENT
    assert config.secure_cookie is True


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


@pytest.mark.parametrize(
    "identity",
    (
        {"AUTH_DEVELOPMENT_BROKERAGE_ID": "1"},
        {"AUTH_DEVELOPMENT_LOGIN_ID": "developer"},
        {
            "AUTH_DEVELOPMENT_BROKERAGE_ID": "1",
            "AUTH_DEVELOPMENT_LOGIN_ID": "   ",
        },
    ),
)
def test_enabled_development_authentication_fails_closed_without_complete_identity(
    identity: dict[str, str],
) -> None:
    values = config_values(
        APP_ENV="dev",
        DB_TARGET="development",
        AUTH_DEVELOPMENT_ENABLED="true",
        **identity,
    )

    with pytest.raises(ValidationError, match="requires brokerage_id and login_id"):
        bind_config(values)


def test_session_and_csrf_cookie_names_must_differ() -> None:
    values = config_values(
        AUTH_SESSION_COOKIE_NAME="same-cookie",
        AUTH_CSRF_COOKIE_NAME="same-cookie",
    )

    with pytest.raises(ConfigurationError, match="Removed Backend"):
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
                "AUTH_DEVELOPMENT_LOGIN_ID=${CONFIG_DOTENV_SENTINEL}",
                "CONFIG_DOTENV_SENTINEL=must-not-leak",
                "",
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "BACKEND_ROOT", tmp_path)
    monkeypatch.delenv("CONFIG_DOTENV_SENTINEL", raising=False)

    config = load_config(AppEnvironment.LOCAL, environ={})

    assert config.auth.development.login_id == "${CONFIG_DOTENV_SENTINEL}"
    assert "CONFIG_DOTENV_SENTINEL" not in os.environ


@pytest.mark.parametrize(
    ("environment", "values"),
    (
        (AppEnvironment.TEST, config_values()),
        (
            AppEnvironment.DEV,
            config_values(APP_ENV="dev", DB_TARGET="development"),
        ),
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
    with pytest.raises(ConfigurationError, match="APP_ENV must be local, test, dev, or prod"):
        load_config(environ=config_values(APP_ENV="preview"))


@pytest.mark.parametrize("process_override", [None, "false", "true"])
def test_f3_opt_in_uses_worker_dotenv_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, process_override: str | None
) -> None:
    from worker import require_synthetic_prototype_opt_in

    defaults = config_values(APP_ENV="local", DB_TARGET="development")
    defaults.update(F3_ALLOW_SYNTHETIC_PROTOTYPE="false")
    (tmp_path / ".env.local").write_text("\n".join(f"{k}={v}" for k, v in defaults.items()))
    (tmp_path / ".env").write_text("F3_ALLOW_SYNTHETIC_PROTOTYPE=true\n")
    monkeypatch.setattr(config_module, "BACKEND_ROOT", tmp_path)
    process = {} if process_override is None else {"F3_ALLOW_SYNTHETIC_PROTOTYPE": process_override}
    config = load_config("local", process)
    if process_override == "false":
        with pytest.raises(ConfigurationError, match="F3_ALLOW_SYNTHETIC_PROTOTYPE"):
            require_synthetic_prototype_opt_in(config)
    else:
        require_synthetic_prototype_opt_in(config)


def test_invalid_privacy_opt_in_is_rejected_by_config() -> None:
    with pytest.raises(ConfigurationError, match="F3_ALLOW_SYNTHETIC_PROTOTYPE"):
        bind_config(config_values(F3_ALLOW_SYNTHETIC_PROTOTYPE="sometimes"))


def test_f2_has_no_feature_flag_and_keeps_request_limits() -> None:
    config = bind_config(
        config_values(
            F2_MAX_AUDIO_BYTES="1024",
        )
    )

    assert not hasattr(config.f2, "enabled")
    assert config.f2.max_audio_bytes == 1024


@pytest.mark.parametrize(
    "name", ["APP_OPENAPI_ENABLED", "WORKER_ENABLED", "WORKER_READY_FILE", "WORKER_ID"]
)
def test_removed_settings_fail_with_migration_hint(name: str) -> None:
    with pytest.raises(ConfigurationError, match="Removed Backend"):
        bind_config(config_values(**{name: "anything"}))


@pytest.mark.parametrize(
    "env,target,docs",
    [
        ("local", "development", True),
        ("test", "test", True),
        ("dev", "development", False),
        ("prod", "production", False),
    ],
)
def test_openapi_is_derived_from_environment(env, target, docs):
    assert bind_config(config_values(APP_ENV=env, DB_TARGET=target)).app.openapi_enabled is docs


@pytest.mark.parametrize("key,value", [("LOG_LEVEL", "trace"), ("LOG_FORMAT", "yaml")])
def test_log_choices_are_enums(key, value):
    with pytest.raises(ValueError):
        bind_config(config_values(**{key: value}))
