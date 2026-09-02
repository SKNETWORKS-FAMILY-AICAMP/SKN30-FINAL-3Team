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
    DEV = "dev"
    PROD = "prod"


class F2ProviderStatus(StrEnum):
    ACTIVE = "active"
    OFFLINE = "offline"


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

    sllm: ProviderEndpointConfig | None = None
    embedding: ProviderEndpointConfig | None = None
    stt: ProviderEndpointConfig | None = None


class F2Config(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider_status: F2ProviderStatus = F2ProviderStatus.OFFLINE
    sllm_model: str = Field(default="sllm", min_length=1)
    stt_model: str = Field(default="stt", min_length=1)
    stt_language: str = Field(default="ko", min_length=1)


class AiConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    profile: AiProfile
    request_timeout_seconds: float = Field(default=60, gt=0)
    openai: OpenAIConfig | None = None
    vllm: VllmConfig = Field(default_factory=VllmConfig)
    f2: F2Config = Field(default_factory=F2Config)


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
        raise ConfigurationError("AI profile must be local, test, dev, or prod") from exc

    openai_api_key = _optional(source, "AI_OPENAI_API_KEY")
    openai_config: OpenAIConfig | None = None
    try:
        raw_f2_status = _optional(source, "AI_F2_PROVIDER_STATUS")
        if raw_f2_status is None:
            f2_status = (
                F2ProviderStatus.ACTIVE
                if _optional(source, "AI_VLLM_SLLM_BASE_URL")
                and _optional(source, "AI_VLLM_STT_BASE_URL")
                else F2ProviderStatus.OFFLINE
            )
        else:
            try:
                f2_status = F2ProviderStatus(raw_f2_status)
            except ValueError as exc:
                raise ConfigurationError("AI_F2_PROVIDER_STATUS must be active or offline") from exc
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
                sllm=(
                    _vllm_endpoint(
                        source,
                        base_url_name="AI_VLLM_SLLM_BASE_URL",
                        api_key_name="AI_VLLM_SLLM_API_KEY",
                    )
                    if f2_status is F2ProviderStatus.ACTIVE
                    else None
                ),
                embedding=_vllm_endpoint(
                    source,
                    base_url_name="AI_VLLM_EMBEDDING_BASE_URL",
                    api_key_name="AI_VLLM_EMBEDDING_API_KEY",
                ),
                stt=(
                    _vllm_endpoint(
                        source,
                        base_url_name="AI_VLLM_STT_BASE_URL",
                        api_key_name="AI_VLLM_STT_API_KEY",
                    )
                    if f2_status is F2ProviderStatus.ACTIVE
                    else None
                ),
            ),
            f2=F2Config(
                provider_status=f2_status,
                sllm_model=_optional(source, "AI_F2_SLLM_MODEL") or "sllm",
                stt_model=_optional(source, "AI_F2_STT_MODEL") or "stt",
                stt_language=_optional(source, "AI_F2_STT_LANGUAGE") or "ko",
            ),
        )
    except ValidationError:
        raise ConfigurationError("invalid AI provider configuration") from None


def _dotenv_mapping(path: Path) -> dict[str, str]:
    return {
        key: value
        for key, value in dotenv_values(path, interpolate=False).items()
        if value is not None
    }


def load_ai_config(
    profile: AiProfile | str,
    environ: Mapping[str, str] | None = None,
) -> AiConfig:
    try:
        selected_profile = AiProfile(profile)
    except ValueError as exc:
        raise ConfigurationError("AI profile must be local, test, dev, or prod") from exc

    values: dict[str, str] = {}
    if selected_profile is AiProfile.LOCAL:
        values.update(_dotenv_mapping(AI_ROOT / ".env.local"))
        values.update(_dotenv_mapping(AI_ROOT / ".env"))
    values.update(dict(os.environ if environ is None else environ))
    return bind_ai_config(values, selected_profile)
