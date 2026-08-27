import os
from pathlib import Path

import pytest

import brokerage_ai.core.config as config_module
from brokerage_ai.core.config import AiProfile, bind_ai_config, load_ai_config
from brokerage_ai.core.errors import ConfigurationError


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
    with pytest.raises(ConfigurationError, match="AI_VLLM_LLM_BASE_URL"):
        bind_ai_config({"AI_VLLM_LLM_API_KEY": "secret"}, AiProfile.LOCAL)


def test_f2_runpod_endpoints_and_models_are_bound() -> None:
    config = bind_ai_config(
        {
            "AI_VLLM_LLM_BASE_URL": "https://pod-8001.proxy.runpod.net/v1",
            "AI_VLLM_STT_BASE_URL": "https://pod-8002.proxy.runpod.net/v1",
            "AI_VLLM_STT_API_KEY": "stt-secret",
            "AI_F2_LLM_MODEL": "Qwen/Qwen3-4B",
            "AI_F2_STT_MODEL": "openai/whisper-large-v3-turbo",
        },
        AiProfile.LOCAL,
    )

    assert config.vllm.stt is not None
    assert config.vllm.stt.api_key is not None
    assert config.vllm.stt.api_key.get_secret_value() == "stt-secret"
    assert config.f2.llm_model == "Qwen/Qwen3-4B"
    assert config.f2.stt_model == "openai/whisper-large-v3-turbo"


def test_invalid_provider_url_is_sanitized() -> None:
    with pytest.raises(ConfigurationError) as caught:
        bind_ai_config(
            {
                "AI_VLLM_LLM_BASE_URL": "not-a-url",
                "AI_VLLM_LLM_API_KEY": "sensitive-value",
            },
            AiProfile.LOCAL,
        )

    assert "sensitive-value" not in str(caught.value)


def test_secret_string_is_masked() -> None:
    config = bind_ai_config({"AI_OPENAI_API_KEY": "sensitive-value"}, AiProfile.LOCAL)

    assert config.openai is not None
    assert str(config.openai.api_key) == "**********"
    assert "sensitive-value" not in repr(config)
