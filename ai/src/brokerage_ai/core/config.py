from __future__ import annotations

import os
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path

from dotenv import dotenv_values
from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    TypeAdapter,
    ValidationError,
)

from brokerage_ai.core.errors import ConfigurationError

AI_ROOT = Path(__file__).resolve().parents[3]


class AiProfile(StrEnum):
    LOCAL = "local"
    TEST = "test"
    PROD = "prod"


class ProviderEndpointConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    base_url: AnyHttpUrl
    api_key: SecretStr | None = None


class OpenAIConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    base_url: AnyHttpUrl
    api_key: SecretStr


class VllmConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    llm: ProviderEndpointConfig | None = None
    embedding: ProviderEndpointConfig | None = None


class AiConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    profile: AiProfile
    request_timeout_seconds: float = Field(default=60, gt=0)
    openai: OpenAIConfig | None = None
    vllm: VllmConfig = Field(default_factory=VllmConfig)


def _optional(source: Mapping[str, str], name: str) -> str | None:
    value = source.get(name, "").strip()
    return value or None


def _http_url(value: str) -> AnyHttpUrl:
    return TypeAdapter(AnyHttpUrl).validate_python(value)


def _positive_float(source: Mapping[str, str], name: str, default: float) -> float:
    raw = _optional(source, name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a positive number") from exc
    if value <= 0:
        raise ConfigurationError(f"{name} must be a positive number")
    return value


def _vllm_endpoint(
    source: Mapping[str, str],
    *,
    base_url_name: str,
    api_key_name: str,
) -> ProviderEndpointConfig | None:
    base_url = _optional(source, base_url_name)
    api_key = _optional(source, api_key_name)
    if base_url is None:
        if api_key is not None:
            raise ConfigurationError(f"{base_url_name} is required when {api_key_name} is set")
        return None
    return ProviderEndpointConfig(
        base_url=_http_url(base_url),
        api_key=SecretStr(api_key) if api_key is not None else None,
    )


def bind_ai_config(source: Mapping[str, str], profile: AiProfile | str) -> AiConfig:
    try:
        selected_profile = AiProfile(profile)
    except ValueError as exc:
        raise ConfigurationError("AI profile must be local, test, or prod") from exc

    openai_api_key = _optional(source, "AI_OPENAI_API_KEY")
    openai_config: OpenAIConfig | None = None
    try:
        if openai_api_key is not None:
            openai_config = OpenAIConfig(
                base_url=_http_url(
                    _optional(source, "AI_OPENAI_BASE_URL") or "https://api.openai.com/v1"
                ),
                api_key=SecretStr(openai_api_key),
            )
        return AiConfig(
            profile=selected_profile,
            request_timeout_seconds=_positive_float(source, "AI_REQUEST_TIMEOUT_SECONDS", 60),
            openai=openai_config,
            vllm=VllmConfig(
                llm=_vllm_endpoint(
                    source,
                    base_url_name="AI_VLLM_LLM_BASE_URL",
                    api_key_name="AI_VLLM_LLM_API_KEY",
                ),
                embedding=_vllm_endpoint(
                    source,
                    base_url_name="AI_VLLM_EMBEDDING_BASE_URL",
                    api_key_name="AI_VLLM_EMBEDDING_API_KEY",
                ),
            ),
        )
    except ValidationError:
        raise ConfigurationError("invalid AI provider configuration") from None


def _dotenv_mapping(path: Path) -> dict[str, str]:
    return {key: value for key, value in dotenv_values(path).items() if value is not None}


def load_ai_config(
    profile: AiProfile | str,
    environ: Mapping[str, str] | None = None,
) -> AiConfig:
    try:
        selected_profile = AiProfile(profile)
    except ValueError as exc:
        raise ConfigurationError("AI profile must be local, test, or prod") from exc

    values: dict[str, str] = {}
    if selected_profile is not AiProfile.TEST:
        values.update(_dotenv_mapping(AI_ROOT / f".env.{selected_profile.value}"))
        values.update(_dotenv_mapping(AI_ROOT / ".env"))
    values.update(dict(os.environ if environ is None else environ))
    return bind_ai_config(values, selected_profile)
