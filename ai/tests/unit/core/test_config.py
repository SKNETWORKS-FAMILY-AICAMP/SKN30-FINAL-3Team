from pathlib import Path

import pytest
from pydantic import ValidationError

import brokerage_ai.core.config as module
from brokerage_ai.core.config import AiProfile, F2ProviderStatus, bind_ai_config, load_ai_config
from brokerage_ai.core.errors import ConfigurationError
from brokerage_ai.core.model_catalog import GeneralModel, GeneralSelection
from brokerage_ai.core.types import ProviderKind


@pytest.mark.parametrize("profile", ["test", "dev", "prod"])
def test_nonlocal_ignores_dotenv(profile, tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("AI_GENERAL_API_KEY=private\n")
    monkeypatch.setattr(module, "AI_ROOT", tmp_path)
    assert load_ai_config(profile, {}).openai is None


def test_local_precedence_literal_and_secret_redaction(tmp_path, monkeypatch):
    (tmp_path / ".env.local").write_text("AI_REQUEST_TIMEOUT_SECONDS=10\n")
    (tmp_path / ".env").write_text(
        "AI_REQUEST_TIMEOUT_SECONDS=20\nAI_GENERAL_API_KEY=${SENTINEL}\n"
    )
    monkeypatch.setattr(module, "AI_ROOT", tmp_path)
    source = {"AI_REQUEST_TIMEOUT_SECONDS": "30"}
    config = load_ai_config("local", source)
    assert config.request_timeout_seconds == 30
    assert config.openai is not None
    assert config.openai.api_key.get_secret_value() == "${SENTINEL}"
    assert "${SENTINEL}" not in repr(config)
    assert source == {"AI_REQUEST_TIMEOUT_SECONDS": "30"}


def test_general_timeout_override_preserves_common_timeout():
    config = bind_ai_config(
        {"AI_REQUEST_TIMEOUT_SECONDS": "60", "AI_GENERAL_REQUEST_TIMEOUT_SECONDS": "300"}, "test"
    )
    assert config.general_timeout_seconds == 300
    assert config.request_timeout_seconds == 60
    assert (
        bind_ai_config({"AI_REQUEST_TIMEOUT_SECONDS": "12.5"}, "test").general_timeout_seconds
        == 12.5
    )


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "invalid"])
def test_general_timeout_requires_finite_positive_number(value):
    with pytest.raises(ConfigurationError):
        bind_ai_config({"AI_GENERAL_REQUEST_TIMEOUT_SECONDS": value}, "test")


@pytest.mark.parametrize("provider", list(ProviderKind))
@pytest.mark.parametrize("model", list(GeneralModel))
def test_provider_model_matrix(provider, model):
    allowed = (
        provider is ProviderKind.OPENAI
        and model is GeneralModel.OPENAI_LUNA
        or provider is ProviderKind.BEDROCK
        and model is GeneralModel.BEDROCK_LUNA
        or provider is ProviderKind.LLAMA_CPP
        and model is GeneralModel.QWEN_GGUF
        or provider is ProviderKind.VLLM
        and model
        in {
            GeneralModel.QWEN_FP8,
            GeneralModel.QWEN_14B,
            GeneralModel.QWEN_32B,
            GeneralModel.QWEN_BNB,
        }
    )
    if not allowed:
        with pytest.raises(ValidationError):
            GeneralSelection(provider=provider, model=model)
    else:
        assert GeneralSelection(provider=provider, model=model).route.model == model.value


@pytest.mark.parametrize(
    "key",
    [
        "AI_GENERAL_PROVIDER",
        "AI_GENERAL_MODEL",
        "AI_F2_SLLM_MODEL",
        "AI_F2_STT_MODEL",
        "AI_F2_STT_LANGUAGE",
    ],
)
def test_unknown_choice_is_rejected_without_echoing_value(key):
    with pytest.raises(ConfigurationError) as exc:
        bind_ai_config({key: "private-invalid-value"}, "local")
    assert "private-invalid-value" not in str(exc.value)


@pytest.mark.parametrize(
    "key", ["AI_OPENAI_API_KEY", "AI_OPENAI_BASE_URL", "AI_F2_PROVIDER_STATUS", "AI_LLM_ENDPOINTS"]
)
def test_removed_inputs_require_explicit_migration(key):
    with pytest.raises(ConfigurationError, match="Removed AI inputs"):
        bind_ai_config({key: "secret"}, "test")


def test_f2_is_derived_from_endpoint_pair():
    assert bind_ai_config({}, "local").f2.provider_status is F2ProviderStatus.OFFLINE
    values = {"AI_VLLM_SLLM_BASE_URL": "http://localhost:8001/v1"}
    with pytest.raises(ConfigurationError, match="both"):
        bind_ai_config(values, "local")
    values["AI_VLLM_STT_BASE_URL"] = "http://localhost:8002/v1"
    assert bind_ai_config(values, "local").f2.provider_status is F2ProviderStatus.ACTIVE


@pytest.mark.parametrize(
    "provider,model",
    [("vllm", "Qwen/Qwen3.8-27B-FP8"), ("llama_cpp", "unsloth/Qwen3.8-27B-GGUF:UD-Q4_K_M")],
)
def test_self_hosted_requires_url_key_pair_and_builds_registry(provider, model):
    values = {"AI_GENERAL_PROVIDER": provider, "AI_GENERAL_MODEL": model}
    assert bind_ai_config(values, "test").llm_endpoints == ()  # offline, no fallback
    values["AI_GENERAL_BASE_URL"] = "http://localhost:8000/v1"
    with pytest.raises(ConfigurationError, match="required"):
        bind_ai_config(values, "test")
    values["AI_GENERAL_API_KEY"] = "secret"
    config = bind_ai_config(values, "test")
    assert config.openai is None
    assert config.llm_endpoints[0].alias == config.general.route.endpoint_alias


@pytest.mark.parametrize(
    "provider,model",
    [
        ("openai", "gpt-5.6-luna"),
        ("vllm", "Qwen/Qwen3.8-27B-FP8"),
        ("llama_cpp", "unsloth/Qwen3.8-27B-GGUF:UD-Q4_K_M"),
    ],
)
@pytest.mark.parametrize(
    "url",
    [
        "ftp://localhost",
        "https://user:secret@localhost/v1",
        "https://localhost/v1?key=secret",
        "https://localhost/v1#secret",
    ],
)
def test_general_url_rejects_unsafe_components(provider, model, url):
    with pytest.raises(ConfigurationError) as error:
        bind_ai_config(
            {
                "AI_GENERAL_PROVIDER": provider,
                "AI_GENERAL_MODEL": model,
                "AI_GENERAL_BASE_URL": url,
                "AI_GENERAL_API_KEY": "private-key-sentinel",
            },
            "test",
        )
    assert url not in str(error.value)
    assert "private-key-sentinel" not in str(error.value)


def test_bedrock_role_region_contract():
    values = {
        "AI_GENERAL_PROVIDER": "bedrock",
        "AI_GENERAL_MODEL": "global.openai.gpt-5.6-luna",
        "AI_GENERAL_AWS_REGION": "ap-northeast-2",
    }
    assert bind_ai_config(values, "dev").llm_endpoints[0].provider is ProviderKind.BEDROCK
    for bad in (
        {"AI_GENERAL_API_KEY": "secret"},
        {"AI_GENERAL_BASE_URL": "http://localhost"},
        {"AI_GENERAL_AWS_REGION": "invalid"},
    ):
        with pytest.raises(ConfigurationError):
            bind_ai_config({**values, **bad}, "dev")


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "invalid"])
def test_timeout_requires_finite_positive_number(value):
    with pytest.raises(ConfigurationError):
        bind_ai_config({"AI_REQUEST_TIMEOUT_SECONDS": value}, "test")


def test_real_templates_are_valid_and_all_enum_values_are_documented(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[3]
    public = (root / ".env.local").read_text()
    (tmp_path / ".env.local").write_text(public)
    (tmp_path / ".env").write_text((root / ".env.example").read_text())
    monkeypatch.setattr(module, "AI_ROOT", tmp_path)
    config = load_ai_config(AiProfile.LOCAL, {})
    assert config.openai is None and config.vllm.sllm is None and config.vllm.embedding is None
    assert all(choice.value in public for choice in GeneralModel)
    assert all(choice.value in public for choice in ProviderKind)


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "nan", "invalid"])
def test_general_vllm_in_flight_requires_positive_integer(value):
    with pytest.raises(ConfigurationError):
        bind_ai_config({"AI_GENERAL_VLLM_MAX_IN_FLIGHT": value}, "test")


def test_general_vllm_in_flight_default_and_override():
    assert bind_ai_config({}, "test").general_vllm_max_in_flight == 1
    assert (
        bind_ai_config({"AI_GENERAL_VLLM_MAX_IN_FLIGHT": "4"}, "test").general_vllm_max_in_flight
        == 4
    )
