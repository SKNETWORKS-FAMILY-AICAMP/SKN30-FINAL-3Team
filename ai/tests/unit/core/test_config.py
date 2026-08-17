from pathlib import Path

import pytest

import brokerage_ai.core.config as config_module
from brokerage_ai.core.config import AiProfile, bind_ai_config, load_ai_config
from brokerage_ai.core.errors import ConfigurationError


def test_process_environment_overrides_secret_and_profile_files(
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


def test_test_profile_does_not_read_dotenv_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".env.test").write_text("AI_OPENAI_API_KEY=must-not-load\n")
    (tmp_path / ".env").write_text("AI_OPENAI_API_KEY=must-not-load\n")
    monkeypatch.setattr(config_module, "AI_ROOT", tmp_path)

    config = load_ai_config(AiProfile.TEST, environ={})

    assert config.openai is None


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
