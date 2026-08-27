from collections.abc import Mapping

import pytest

from core.config import Config, bind_config


@pytest.fixture(autouse=True)
def configure_test_f2_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Backend lifespan이 외부 요청 없이 F2 provider client를 생성할 수 있게 한다."""
    monkeypatch.setenv("AI_VLLM_LLM_BASE_URL", "http://127.0.0.1:18001/v1")
    monkeypatch.setenv("AI_VLLM_STT_BASE_URL", "http://127.0.0.1:18002/v1")


def config_values(**overrides: str) -> dict[str, str]:
    values = {
        "APP_ENV": "test",
        "APP_HOST": "127.0.0.1",
        "APP_PORT": "8000",
        "APP_OPENAPI_ENABLED": "true",
        "DB_TARGET": "test",
        "DB_URL": "postgresql+psycopg://app:test@localhost:5432/brokerage_test",
        "DB_MIGRATION_URL": ("postgresql+psycopg://migration:test@localhost:5432/brokerage_test"),
        "AUTH_DEVELOPMENT_ENABLED": "false",
        "HTTP_CORS_ALLOWED_ORIGINS": '["http://localhost:5173"]',
        "HTTP_ALLOWED_HOSTS": '["testserver","localhost"]',
        "LOG_LEVEL": "INFO",
        "LOG_FORMAT": "console",
    }
    values.update(overrides)
    return values


@pytest.fixture
def config() -> Config:
    return bind_config(config_values())


@pytest.fixture
def make_config():
    def factory(overrides: Mapping[str, str] | None = None) -> Config:
        return bind_config(config_values(**dict(overrides or {})))

    return factory
