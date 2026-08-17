import pytest
from pydantic import ValidationError

from conftest import config_values
from core.config import (
    AppEnvironment,
    DatabaseTarget,
    bind_config,
)
from core.errors import ConfigurationError


def test_environment_values_are_bound_to_group_dtos() -> None:
    config = bind_config(config_values())

    assert config.app.environment is AppEnvironment.TEST
    assert config.db.target is DatabaseTarget.TEST
    assert config.db.pool.size == 5
    assert config.auth.development.enabled is False
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
