import json
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

import brokerage_ai.core.config as config_module
from brokerage_ai.core.config import (
    AiProfile,
    BedrockLlmEndpointConfig,
    F2ProviderStatus,
    SelfHostedLlmEndpointConfig,
    bind_ai_config,
    load_ai_config,
)
from brokerage_ai.core.errors import ConfigurationError
from brokerage_ai.core.types import ProviderKind


def test_local_environment_merges_team_personal_and_process_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".env.local").write_text(
        "AI_REQUEST_TIMEOUT_SECONDS=10\nAI_OPENAI_API_KEY=profile-secret\n"
    )
    (tmp_path / ".env").write_text(
        "AI_REQUEST_TIMEOUT_SECONDS=20\nAI_OPENAI_API_KEY=local-secret\n"
    )
    monkeypatch.setattr(config_module, "AI_ROOT", tmp_path)

    config = load_ai_config(
        AiProfile.LOCAL,
        environ={
            "AI_REQUEST_TIMEOUT_SECONDS": "30",
            "AI_OPENAI_API_KEY": "process-secret",
        },
    )

    assert config.request_timeout_seconds == 30
    assert config.openai is not None
    assert config.openai.api_key.get_secret_value() == "process-secret"


def test_local_dotenv_loading_is_literal_and_does_not_mutate_process_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".env.local").write_text(
        "AI_OPENAI_BASE_URL=https://api.openai.com/v1\nAI_REQUEST_TIMEOUT_SECONDS=10\n",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "AI_OPENAI_API_KEY=${AI_CONFIG_SENTINEL}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "AI_ROOT", tmp_path)
    monkeypatch.delenv("AI_CONFIG_SENTINEL", raising=False)

    config = load_ai_config(AiProfile.LOCAL, environ={})

    assert config.openai is not None
    assert config.openai.api_key.get_secret_value() == "${AI_CONFIG_SENTINEL}"
    assert "AI_CONFIG_SENTINEL" not in os.environ


@pytest.mark.parametrize("profile", [AiProfile.TEST, AiProfile.DEV, AiProfile.PROD])
def test_non_local_profiles_do_not_read_dotenv_files(
    profile: AiProfile,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".env.local").write_text(
        "AI_OPENAI_API_KEY=must-not-load\n",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "AI_OPENAI_API_KEY=must-not-load\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "AI_ROOT", tmp_path)

    config = load_ai_config(profile, environ={})

    assert config.profile is profile
    assert config.openai is None


def test_invalid_ai_profile_error_lists_dev() -> None:
    with pytest.raises(ConfigurationError, match="local, test, dev, or prod"):
        load_ai_config("preview", environ={})


def test_openai_is_disabled_without_api_key() -> None:
    config = bind_ai_config(
        {"AI_OPENAI_BASE_URL": "https://proxy.example/v1"},
        AiProfile.LOCAL,
    )

    assert config.openai is None


@pytest.mark.parametrize("value", ["0", "-1", "not-a-number"])
def test_timeout_must_be_positive(value: str) -> None:
    with pytest.raises(ConfigurationError, match="positive number"):
        bind_ai_config({"AI_REQUEST_TIMEOUT_SECONDS": value}, AiProfile.LOCAL)


def test_vllm_key_requires_matching_base_url() -> None:
    with pytest.raises(ConfigurationError, match="AI_VLLM_SLLM_BASE_URL"):
        bind_ai_config(
            {
                "AI_F2_PROVIDER_STATUS": "active",
                "AI_VLLM_SLLM_API_KEY": "secret",
                "AI_VLLM_STT_BASE_URL": "https://pod-8002.proxy.runpod.net/v1",
            },
            AiProfile.LOCAL,
        )


def test_f2_runpod_endpoints_and_models_are_bound() -> None:
    config = bind_ai_config(
        {
            "AI_F2_PROVIDER_STATUS": "active",
            "AI_VLLM_SLLM_BASE_URL": "https://pod-8001.proxy.runpod.net/v1",
            "AI_VLLM_STT_BASE_URL": "https://pod-8002.proxy.runpod.net/v1",
            "AI_VLLM_STT_API_KEY": "stt-secret",
            "AI_F2_SLLM_MODEL": "sllm",
            "AI_F2_STT_MODEL": "stt",
        },
        AiProfile.LOCAL,
    )

    assert config.vllm.stt is not None
    assert config.vllm.stt.api_key is not None
    assert config.vllm.stt.api_key.get_secret_value() == "stt-secret"
    assert config.f2.provider_status is F2ProviderStatus.ACTIVE
    assert config.f2.sllm_model == "sllm"
    assert config.f2.stt_model == "stt"


def test_f2_endpoints_do_not_activate_provider_without_explicit_status() -> None:
    config = bind_ai_config(
        {
            "AI_VLLM_SLLM_BASE_URL": "https://pod-8001.proxy.runpod.net/v1",
            "AI_VLLM_SLLM_API_KEY": "retained-secret",
            "AI_VLLM_STT_BASE_URL": "https://pod-8002.proxy.runpod.net/v1",
            "AI_VLLM_STT_API_KEY": "retained-secret-2",
        },
        AiProfile.DEV,
    )

    assert config.f2.provider_status is F2ProviderStatus.OFFLINE
    assert config.vllm.sllm is None
    assert config.vllm.stt is None


@pytest.mark.parametrize(
    ("source", "missing_url"),
    [
        (
            {"AI_VLLM_STT_BASE_URL": "https://pod-8002.proxy.runpod.net/v1"},
            "AI_VLLM_SLLM_BASE_URL",
        ),
        (
            {"AI_VLLM_SLLM_BASE_URL": "https://pod-8001.proxy.runpod.net/v1"},
            "AI_VLLM_STT_BASE_URL",
        ),
    ],
)
def test_active_f2_requires_both_provider_endpoints(
    source: dict[str, str], missing_url: str
) -> None:
    with pytest.raises(ConfigurationError, match=missing_url):
        bind_ai_config(
            {"AI_F2_PROVIDER_STATUS": "active", **source},
            AiProfile.DEV,
        )


def test_invalid_provider_url_is_sanitized() -> None:
    with pytest.raises(ConfigurationError) as caught:
        bind_ai_config(
            {
                "AI_F2_PROVIDER_STATUS": "active",
                "AI_VLLM_SLLM_BASE_URL": "not-a-url",
                "AI_VLLM_SLLM_API_KEY": "sensitive-value",
                "AI_VLLM_STT_BASE_URL": "https://pod-8002.proxy.runpod.net/v1",
            },
            AiProfile.LOCAL,
        )

    assert "sensitive-value" not in str(caught.value)


def test_offline_f2_does_not_bind_vllm_secrets_without_urls() -> None:
    config = bind_ai_config(
        {
            "AI_F2_PROVIDER_STATUS": "offline",
            "AI_VLLM_SLLM_API_KEY": "retained-secret",
            "AI_VLLM_STT_API_KEY": "retained-secret-2",
        },
        AiProfile.DEV,
    )

    assert config.vllm.sllm is None
    assert config.vllm.stt is None


def test_secret_string_is_masked() -> None:
    config = bind_ai_config({"AI_OPENAI_API_KEY": "sensitive-value"}, AiProfile.LOCAL)

    assert config.openai is not None
    assert str(config.openai.api_key) == "**********"
    assert "sensitive-value" not in repr(config)


def test_self_hosted_llm_endpoint_resolves_secret_reference() -> None:
    address_book = [
        {
            "alias": " general-dev-gpu ",
            "provider": "llama_cpp",
            "base_url": "https://gpu.example/v1",
            "api_key_env": "AI_GENERAL_DEV_GPU_API_KEY",
        }
    ]

    config = bind_ai_config(
        {
            "AI_LLM_ENDPOINTS": json.dumps(address_book),
            "AI_GENERAL_DEV_GPU_API_KEY": "sensitive-value",
        },
        AiProfile.DEV,
    )

    endpoint = config.llm_endpoints[0]
    assert isinstance(endpoint, SelfHostedLlmEndpointConfig)
    assert endpoint.alias == "general-dev-gpu"
    assert endpoint.provider is ProviderKind.LLAMA_CPP
    assert endpoint.api_key.get_secret_value() == "sensitive-value"
    assert "sensitive-value" not in repr(config)


def test_bedrock_llm_endpoint_derives_official_runtime_url_without_secret() -> None:
    config = bind_ai_config(
        {
            "AI_LLM_ENDPOINTS": json.dumps(
                [
                    {
                        "alias": " general-dev-bedrock ",
                        "provider": "bedrock",
                        "aws_region": " ap-northeast-2 ",
                    }
                ]
            )
        },
        AiProfile.DEV,
    )

    endpoint = config.llm_endpoints[0]
    assert isinstance(endpoint, BedrockLlmEndpointConfig)
    assert endpoint.alias == "general-dev-bedrock"
    assert endpoint.provider is ProviderKind.BEDROCK
    assert endpoint.aws_region == "ap-northeast-2"
    assert endpoint.base_url == ("https://bedrock-runtime.ap-northeast-2.amazonaws.com/openai/v1")


def test_direct_bedrock_endpoint_config_applies_the_same_normalization() -> None:
    endpoint = BedrockLlmEndpointConfig(
        alias=" general-dev-bedrock ",
        provider=ProviderKind.BEDROCK,
        aws_region=" ap-northeast-2 ",
    )

    assert endpoint.alias == "general-dev-bedrock"
    assert endpoint.aws_region == "ap-northeast-2"
    with pytest.raises(ValidationError, match="valid AWS region"):
        BedrockLlmEndpointConfig(
            alias="general-dev-bedrock",
            provider=ProviderKind.BEDROCK,
            aws_region="not a region",
        )


@pytest.mark.parametrize("extra_field", ["base_url", "api_key_env", "api_key"])
def test_bedrock_llm_endpoint_rejects_key_and_url_fields(extra_field: str) -> None:
    definition = {
        "alias": "general-dev-bedrock",
        "provider": "bedrock",
        "aws_region": "ap-northeast-2",
        extra_field: "sensitive-value",
    }

    with pytest.raises(ConfigurationError) as caught:
        bind_ai_config(
            {"AI_LLM_ENDPOINTS": json.dumps([definition])},
            AiProfile.DEV,
        )

    assert "sensitive-value" not in str(caught.value)


@pytest.mark.parametrize(
    "definition",
    [
        {
            "alias": " ",
            "provider": "bedrock",
            "aws_region": "ap-northeast-2",
        },
        {
            "alias": "general-dev-bedrock",
            "provider": "bedrock",
            "aws_region": "not a region",
        },
        {
            "alias": "general-dev-bedrock",
            "provider": "unsupported",
            "aws_region": "ap-northeast-2",
        },
        {
            "alias": "general-dev-gpu",
            "provider": "vllm",
            "base_url": "not-a-url",
            "api_key_env": "AI_GENERAL_DEV_GPU_API_KEY",
        },
        {
            "alias": "general-dev-gpu",
            "provider": "vllm",
            "base_url": "https://gpu.example/v1",
            "api_key_env": "UNSAFE_KEY",
        },
    ],
)
def test_invalid_llm_endpoint_definition_is_rejected(definition: dict[str, str]) -> None:
    with pytest.raises(ConfigurationError, match="invalid AI_LLM_ENDPOINTS"):
        bind_ai_config(
            {
                "AI_LLM_ENDPOINTS": json.dumps([definition]),
                "AI_GENERAL_DEV_GPU_API_KEY": "sensitive-value",
            },
            AiProfile.DEV,
        )


def test_self_hosted_llm_endpoint_requires_referenced_secret() -> None:
    definition = {
        "alias": "general-dev-gpu",
        "provider": "vllm",
        "base_url": "https://gpu.example/v1",
        "api_key_env": "AI_GENERAL_DEV_GPU_API_KEY",
    }

    with pytest.raises(ConfigurationError, match="AI_GENERAL_DEV_GPU_API_KEY"):
        bind_ai_config(
            {"AI_LLM_ENDPOINTS": json.dumps([definition])},
            AiProfile.DEV,
        )


@pytest.mark.parametrize(
    "base_url",
    [
        "https://user:sensitive-value@gpu.example/v1",
        "https://gpu.example/v1?token=sensitive-value",
        "https://gpu.example/v1#sensitive-value",
    ],
)
def test_self_hosted_llm_endpoint_rejects_sensitive_url_components(
    base_url: str,
) -> None:
    definition = {
        "alias": "general-dev-gpu",
        "provider": "vllm",
        "base_url": base_url,
        "api_key_env": "AI_GENERAL_DEV_GPU_API_KEY",
    }

    with pytest.raises(ConfigurationError) as caught:
        bind_ai_config(
            {
                "AI_LLM_ENDPOINTS": json.dumps([definition]),
                "AI_GENERAL_DEV_GPU_API_KEY": "another-sensitive-value",
            },
            AiProfile.DEV,
        )

    assert "sensitive-value" not in str(caught.value)
    assert "another-sensitive-value" not in str(caught.value)


def test_llm_endpoint_alias_is_unique_across_providers() -> None:
    address_book = [
        {
            "alias": "general-dev",
            "provider": "bedrock",
            "aws_region": "ap-northeast-2",
        },
        {
            "alias": " general-dev ",
            "provider": "vllm",
            "base_url": "https://gpu.example/v1",
            "api_key_env": "AI_GENERAL_DEV_GPU_API_KEY",
        },
    ]

    with pytest.raises(ConfigurationError, match="duplicate alias: general-dev"):
        bind_ai_config(
            {
                "AI_LLM_ENDPOINTS": json.dumps(address_book),
                "AI_GENERAL_DEV_GPU_API_KEY": "sensitive-value",
            },
            AiProfile.DEV,
        )
