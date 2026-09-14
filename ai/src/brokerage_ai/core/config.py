from __future__ import annotations

import math
import os
import re
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import Literal

from dotenv import dotenv_values
from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    TypeAdapter,
    ValidationError,
    field_validator,
)

from brokerage_ai.core.errors import ConfigurationError
from brokerage_ai.core.model_catalog import (
    F2SllmModel,
    F2SttModel,
    GeneralModel,
    GeneralSelection,
    SttLanguage,
)
from brokerage_ai.core.types import ProviderKind

AI_ROOT = Path(__file__).resolve().parents[3]


def _normalized_alias(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("alias must not be blank")
    return normalized


def _normalized_aws_region(value: str) -> str:
    normalized = value.strip()
    if re.fullmatch(r"[a-z]{2}(?:-[a-z0-9]+)+-[0-9]+", normalized) is None:
        raise ValueError("aws_region must be a valid AWS region name")
    return normalized


def _safe_self_hosted_base_url(value: AnyHttpUrl) -> AnyHttpUrl:
    if any(
        component is not None
        for component in (value.username, value.password, value.query, value.fragment)
    ):
        raise ValueError("base_url must not contain userinfo, query, or fragment")
    return value


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


class SelfHostedLlmEndpointConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    alias: str = Field(min_length=1, max_length=160)
    provider: Literal[ProviderKind.VLLM, ProviderKind.LLAMA_CPP]
    base_url: AnyHttpUrl
    api_key: SecretStr

    @field_validator("alias")
    @classmethod
    def alias_must_not_be_blank(cls, value: str) -> str:
        return _normalized_alias(value)

    @field_validator("base_url")
    @classmethod
    def base_url_must_not_contain_secrets(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        return _safe_self_hosted_base_url(value)


class BedrockLlmEndpointConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    alias: str = Field(min_length=1, max_length=160)
    provider: Literal[ProviderKind.BEDROCK]
    aws_region: str = Field(min_length=1)

    @field_validator("alias")
    @classmethod
    def alias_must_not_be_blank(cls, value: str) -> str:
        return _normalized_alias(value)

    @field_validator("aws_region")
    @classmethod
    def aws_region_must_be_valid(cls, value: str) -> str:
        return _normalized_aws_region(value)

    @property
    def base_url(self) -> str:
        return f"https://bedrock-runtime.{self.aws_region}.amazonaws.com/openai/v1"


LlmEndpointConfig = SelfHostedLlmEndpointConfig | BedrockLlmEndpointConfig


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
    sllm_model: F2SllmModel = F2SllmModel.SLLM
    stt_model: F2SttModel = F2SttModel.STT
    stt_language: SttLanguage = SttLanguage.KOREAN


class AiConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    profile: AiProfile
    general: GeneralSelection = Field(default_factory=GeneralSelection)
    request_timeout_seconds: float = Field(default=60, gt=0)
    general_request_timeout_seconds: float | None = Field(default=None, gt=0)
    general_vllm_max_in_flight: int = Field(default=1, ge=1)
    openai: OpenAIConfig | None = None
    vllm: VllmConfig = Field(default_factory=VllmConfig)
    llm_endpoints: tuple[LlmEndpointConfig, ...] = ()
    f2: F2Config = Field(default_factory=F2Config)

    @property
    def general_timeout_seconds(self) -> float:
        """범용 생성만 별도 제한을 쓰며, 미설정 환경은 기존 공통 제한을 유지한다."""
        return self.general_request_timeout_seconds or self.request_timeout_seconds


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
    if not math.isfinite(value) or value <= 0:
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

    removed = {
        "AI_LLM_ENDPOINTS",
        "AI_F2_PROVIDER_STATUS",
        "AI_OPENAI_API_KEY",
        "AI_OPENAI_BASE_URL",
    } & source.keys()
    if removed:
        raise ConfigurationError(
            "Removed AI inputs: "
            + ", ".join(sorted(removed))
            + "; migrate using docs/development/environment-variables.md"
        )
    try:
        general = GeneralSelection(
            provider=ProviderKind(
                _optional(source, "AI_GENERAL_PROVIDER") or ProviderKind.OPENAI.value
            ),
            model=GeneralModel(
                _optional(source, "AI_GENERAL_MODEL") or GeneralModel.OPENAI_LUNA.value
            ),
        )
        key = _optional(source, "AI_GENERAL_API_KEY")
        base_url = _optional(source, "AI_GENERAL_BASE_URL")
        region = _optional(source, "AI_GENERAL_AWS_REGION")
        openai_config = None
        endpoints: tuple[LlmEndpointConfig, ...] = ()
        if general.provider is ProviderKind.OPENAI:
            if region:
                raise ConfigurationError("AI_GENERAL_AWS_REGION is only valid for bedrock")
            if key:
                openai_config = OpenAIConfig(
                    base_url=_safe_self_hosted_base_url(
                        _http_url(base_url or "https://api.openai.com/v1")
                    ),
                    api_key=SecretStr(key),
                )
        elif general.provider is ProviderKind.BEDROCK:
            if key or base_url:
                raise ConfigurationError(
                    "bedrock uses an AWS role and region, not API key/base URL"
                )
            if not region:
                raise ConfigurationError("AI_GENERAL_AWS_REGION is required for bedrock")
            endpoints = (
                BedrockLlmEndpointConfig(
                    alias="general-dev-bedrock", provider=ProviderKind.BEDROCK, aws_region=region
                ),
            )
        else:
            if region:
                raise ConfigurationError("AI_GENERAL_AWS_REGION is only valid for bedrock")
            if bool(base_url) != bool(key):
                raise ConfigurationError(
                    "AI_GENERAL_BASE_URL and AI_GENERAL_API_KEY "
                    "are required together for self-hosted providers"
                )
            endpoints = (
                (
                    SelfHostedLlmEndpointConfig(
                        alias="general-dev-gpu",
                        provider=general.provider,
                        base_url=_http_url(base_url),
                        api_key=SecretStr(key or ""),
                    ),
                )
                if base_url
                else ()
            )
        sllm = _vllm_endpoint(
            source, base_url_name="AI_VLLM_SLLM_BASE_URL", api_key_name="AI_VLLM_SLLM_API_KEY"
        )
        stt = _vllm_endpoint(
            source, base_url_name="AI_VLLM_STT_BASE_URL", api_key_name="AI_VLLM_STT_API_KEY"
        )
        if (sllm is None) != (stt is None):
            raise ConfigurationError("F2 requires both SLLM and STT URLs, or neither")
        return AiConfig(
            profile=selected_profile,
            general=general,
            request_timeout_seconds=_positive_float(source, "AI_REQUEST_TIMEOUT_SECONDS", 60),
            general_request_timeout_seconds=(
                _positive_float(source, "AI_GENERAL_REQUEST_TIMEOUT_SECONDS", 60)
                if _optional(source, "AI_GENERAL_REQUEST_TIMEOUT_SECONDS") is not None
                else None
            ),
            general_vllm_max_in_flight=TypeAdapter(int).validate_python(
                _optional(source, "AI_GENERAL_VLLM_MAX_IN_FLIGHT") or "1"
            ),
            openai=openai_config,
            vllm=VllmConfig(
                sllm=sllm,
                stt=stt,
                embedding=_vllm_endpoint(
                    source,
                    base_url_name="AI_VLLM_EMBEDDING_BASE_URL",
                    api_key_name="AI_VLLM_EMBEDDING_API_KEY",
                ),
            ),
            llm_endpoints=endpoints,
            f2=F2Config(
                provider_status=F2ProviderStatus.ACTIVE
                if sllm is not None
                else F2ProviderStatus.OFFLINE,
                sllm_model=F2SllmModel(
                    _optional(source, "AI_F2_SLLM_MODEL") or F2SllmModel.SLLM.value
                ),
                stt_model=F2SttModel(_optional(source, "AI_F2_STT_MODEL") or F2SttModel.STT.value),
                stt_language=SttLanguage(
                    _optional(source, "AI_F2_STT_LANGUAGE") or SttLanguage.KOREAN.value
                ),
            ),
        )
    except (ValidationError, ValueError):
        raise ConfigurationError(
            "invalid AI selection or provider configuration; see model_catalog.py allowed values"
        ) from None


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
