from __future__ import annotations

import json
import os
from collections.abc import Mapping
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from pydantic import BaseModel, Field, SecretStr, model_validator

from core.errors import ConfigurationError

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class AppEnvironment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    DEV = "dev"
    PROD = "prod"


class DatabaseTarget(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class AppConfig(BaseModel):
    environment: AppEnvironment
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    openapi_enabled: bool = True


class DbPoolConfig(BaseModel):
    size: int = Field(default=5, ge=1)
    max_overflow: int = Field(default=5, ge=0)
    timeout_seconds: int = Field(default=30, ge=1)


class DbConfig(BaseModel):
    target: DatabaseTarget
    url: SecretStr
    migration_url: SecretStr | None = None
    pool: DbPoolConfig


class DevelopmentAuthConfig(BaseModel):
    enabled: bool = False
    brokerage_id: int | None = Field(default=None, ge=1)
    login_id: str | None = None

    @model_validator(mode="after")
    def validate_identity(self) -> DevelopmentAuthConfig:
        if self.enabled and (self.brokerage_id is None or not self.login_id):
            raise ValueError("development authentication requires brokerage_id and login_id")
        return self


class SessionConfig(BaseModel):
    cookie_name: str = Field(default="brokerage_session", min_length=1)
    csrf_cookie_name: str = Field(default="brokerage_csrf", min_length=1)
    idle_timeout_minutes: int = Field(default=1440, ge=1)
    absolute_timeout_minutes: int = Field(default=10080, ge=1)
    last_seen_update_seconds: int = Field(default=300, ge=1)
    cookie_domain: str | None = None

    @model_validator(mode="after")
    def validate_cookie_names(self) -> SessionConfig:
        if self.cookie_name == self.csrf_cookie_name:
            raise ValueError("session and CSRF cookies must use different names")
        return self


class AuthConfig(BaseModel):
    development: DevelopmentAuthConfig
    session: SessionConfig


class HttpConfig(BaseModel):
    cors_allowed_origins: list[str]
    allowed_hosts: list[str]


class LogConfig(BaseModel):
    level: str = "INFO"
    format: str = "console"


class WorkerConfig(BaseModel):
    enabled: bool = False
    ready_file: Path = Path("/tmp/brokerage-worker-ready")
    worker_id: str | None = None

    @model_validator(mode="after")
    def validate_ready_file(self) -> WorkerConfig:
        if not self.ready_file.is_absolute():
            raise ValueError("WORKER_READY_FILE must be an absolute path")
        return self


class F2Config(BaseModel):
    max_audio_bytes: int = Field(default=25 * 1024 * 1024, ge=1)


class Config(BaseModel):
    app: AppConfig
    db: DbConfig
    auth: AuthConfig
    http: HttpConfig
    log: LogConfig
    worker: WorkerConfig
    f2: F2Config

    @model_validator(mode="after")
    def validate_environment_boundaries(self) -> Config:
        expected_target = {
            AppEnvironment.LOCAL: DatabaseTarget.DEVELOPMENT,
            AppEnvironment.TEST: DatabaseTarget.TEST,
            AppEnvironment.DEV: DatabaseTarget.DEVELOPMENT,
            AppEnvironment.PROD: DatabaseTarget.PRODUCTION,
        }[self.app.environment]
        if self.db.target is not expected_target:
            raise ValueError(
                f"{self.app.environment.value} requires DB_TARGET={expected_target.value}"
            )
        if self.app.environment is AppEnvironment.PROD and self.auth.development.enabled:
            raise ValueError("development authentication is forbidden in production")
        if "*" in self.http.cors_allowed_origins:
            raise ValueError("credentialed CORS cannot use a wildcard origin")
        if self.log.format not in {"console", "json"}:
            raise ValueError("LOG_FORMAT must be console or json")
        return self

    @property
    def secure_cookie(self) -> bool:
        return self.app.environment in {AppEnvironment.DEV, AppEnvironment.PROD}


def _required(source: Mapping[str, str], name: str) -> str:
    value = source.get(name, "").strip()
    if not value:
        raise ConfigurationError(f"missing required environment variable: {name}")
    return value


def _optional(source: Mapping[str, str], name: str) -> str | None:
    value = source.get(name, "").strip()
    return value or None


def _boolean(source: Mapping[str, str], name: str, default: bool) -> bool:
    raw = source.get(name)
    if raw is None or not raw.strip():
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} must be a boolean")


def _integer(source: Mapping[str, str], name: str, default: int) -> int:
    raw = source.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc


def _string_list(source: Mapping[str, str], name: str, default: list[str]) -> list[str]:
    raw = source.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"{name} must be a JSON string array") from exc
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigurationError(f"{name} must be a JSON string array")
    return value


def bind_config(source: Mapping[str, str]) -> Config:
    development_enabled = _boolean(source, "AUTH_DEVELOPMENT_ENABLED", False)
    return Config(
        app=AppConfig(
            environment=AppEnvironment(_required(source, "APP_ENV")),
            host=source.get("APP_HOST", "127.0.0.1"),
            port=_integer(source, "APP_PORT", 8000),
            openapi_enabled=_boolean(source, "APP_OPENAPI_ENABLED", True),
        ),
        db=DbConfig(
            target=DatabaseTarget(_required(source, "DB_TARGET")),
            url=SecretStr(_required(source, "DB_URL")),
            migration_url=(
                SecretStr(migration_url)
                if (migration_url := _optional(source, "DB_MIGRATION_URL"))
                else None
            ),
            pool=DbPoolConfig(
                size=_integer(source, "DB_POOL_SIZE", 5),
                max_overflow=_integer(source, "DB_POOL_MAX_OVERFLOW", 5),
                timeout_seconds=_integer(source, "DB_POOL_TIMEOUT_SECONDS", 30),
            ),
        ),
        auth=AuthConfig(
            development=DevelopmentAuthConfig(
                enabled=development_enabled,
                brokerage_id=(_integer(source, "AUTH_DEVELOPMENT_BROKERAGE_ID", 0) or None),
                login_id=_optional(source, "AUTH_DEVELOPMENT_LOGIN_ID"),
            ),
            session=SessionConfig(
                cookie_name=source.get("AUTH_SESSION_COOKIE_NAME", "brokerage_session"),
                csrf_cookie_name=source.get("AUTH_CSRF_COOKIE_NAME", "brokerage_csrf"),
                idle_timeout_minutes=_integer(source, "AUTH_SESSION_IDLE_TIMEOUT_MINUTES", 1440),
                absolute_timeout_minutes=_integer(
                    source, "AUTH_SESSION_ABSOLUTE_TIMEOUT_MINUTES", 10080
                ),
                last_seen_update_seconds=_integer(
                    source, "AUTH_SESSION_LAST_SEEN_UPDATE_SECONDS", 300
                ),
                cookie_domain=_optional(source, "AUTH_SESSION_COOKIE_DOMAIN"),
            ),
        ),
        http=HttpConfig(
            cors_allowed_origins=_string_list(
                source, "HTTP_CORS_ALLOWED_ORIGINS", ["http://localhost:5173"]
            ),
            allowed_hosts=_string_list(source, "HTTP_ALLOWED_HOSTS", ["localhost", "127.0.0.1"]),
        ),
        log=LogConfig(
            level=source.get("LOG_LEVEL", "INFO").upper(),
            format=source.get("LOG_FORMAT", "console").lower(),
        ),
        worker=WorkerConfig(
            enabled=_boolean(source, "WORKER_ENABLED", False),
            ready_file=Path(source.get("WORKER_READY_FILE", "/tmp/brokerage-worker-ready")),
            worker_id=_optional(source, "WORKER_ID"),
        ),
        f2=F2Config(
            max_audio_bytes=_integer(source, "F2_MAX_AUDIO_BYTES", 25 * 1024 * 1024),
        ),
    )


def _dotenv_mapping(path: Path) -> dict[str, str]:
    return {
        key: value
        for key, value in dotenv_values(path, interpolate=False).items()
        if value is not None
    }


def load_config(
    environment: AppEnvironment | str | None = None,
    environ: Mapping[str, str] | None = None,
) -> Config:
    process_values = dict(os.environ if environ is None else environ)
    selected_value = (
        environment if environment is not None else process_values.get("APP_ENV", "local")
    )
    try:
        selected_environment = AppEnvironment(selected_value)
    except ValueError as exc:
        raise ConfigurationError("APP_ENV must be local, test, dev, or prod") from exc

    values: dict[str, str] = {}
    if selected_environment is AppEnvironment.LOCAL:
        values.update(_dotenv_mapping(BACKEND_ROOT / ".env.local"))
        values.update(_dotenv_mapping(BACKEND_ROOT / ".env"))
    values.update(process_values)

    config = bind_config(values)
    if config.app.environment is not selected_environment:
        raise ConfigurationError("selected environment and APP_ENV must match")
    return config


@lru_cache(maxsize=1)
def get_config() -> Config:
    return load_config()
