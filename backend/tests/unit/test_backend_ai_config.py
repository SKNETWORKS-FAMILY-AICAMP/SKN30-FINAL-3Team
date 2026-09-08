from pathlib import Path

import pytest

import core.config as module


def test_backend_loads_only_its_own_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".env.local").write_text(
        "AI_OPENAI_API_KEY=public-default\nAI_F2_PROVIDER_STATUS=offline\n"
    )
    (tmp_path / ".env").write_text("AI_OPENAI_API_KEY=private-backend\n")
    monkeypatch.setattr(module, "BACKEND_ROOT", tmp_path)
    config = module.load_ai_config("local", {"AI_OPENAI_API_KEY": "explicit-process"})
    assert config.openai is not None
    assert config.openai.api_key.get_secret_value() == "explicit-process"
    config = module.load_ai_config("local", {})
    assert config.openai is not None
    assert config.openai.api_key.get_secret_value() == "private-backend"


def test_dev_never_reads_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".env").write_text("AI_OPENAI_API_KEY=must-not-be-read\n")
    monkeypatch.setattr(module, "BACKEND_ROOT", tmp_path)
    config = module.load_ai_config("dev", {"AI_F2_PROVIDER_STATUS": "offline"})
    assert config.openai is None


@pytest.mark.parametrize("profile", ["test", "dev", "prod"])
def test_deployed_ai_config_never_opens_dotenv(
    profile: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def reject_file_read(_path: Path) -> dict[str, str]:
        pytest.fail("non-local settings must not read dotenv files")

    monkeypatch.setattr(module, "_dotenv_mapping", reject_file_read)
    config = module.load_ai_config(profile, {"AI_REQUEST_TIMEOUT_SECONDS": "25"})
    assert config.request_timeout_seconds == 25
    assert config.openai is None


def test_backend_and_ai_standalone_keep_separate_personal_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import brokerage_ai.core.config as ai_module

    backend_root = tmp_path / "backend"
    ai_root = tmp_path / "ai"
    backend_root.mkdir()
    ai_root.mkdir()
    (backend_root / ".env").write_text("AI_OPENAI_API_KEY=synthetic-backend\n")
    (ai_root / ".env").write_text("AI_OPENAI_API_KEY=synthetic-ai\n")
    monkeypatch.setattr(module, "BACKEND_ROOT", backend_root)
    monkeypatch.setattr(ai_module, "AI_ROOT", ai_root)
    backend = module.load_ai_config("local", {})
    standalone = ai_module.load_ai_config("local", {})
    assert backend.openai is not None and standalone.openai is not None
    assert backend.openai.api_key.get_secret_value() == "synthetic-backend"
    assert standalone.openai.api_key.get_secret_value() == "synthetic-ai"
    (backend_root / ".env").unlink()
    assert module.load_ai_config("local", {}).openai is None


@pytest.mark.parametrize("layer", ["default", "personal", "process"])
def test_backend_and_ai_settings_share_precedence_without_mutating_inputs(
    layer: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from conftest import config_values

    defaults = config_values(APP_ENV="local", DB_TARGET="development", APP_PORT="8001")
    defaults["AI_REQUEST_TIMEOUT_SECONDS"] = "11"
    (tmp_path / ".env.local").write_text(
        "\n".join(f"{key}={value}" for key, value in defaults.items()) + "\n"
    )
    monkeypatch.setattr(module, "BACKEND_ROOT", tmp_path)
    source: dict[str, str] = {}
    expected = (8001, 11)
    if layer in {"personal", "process"}:
        (tmp_path / ".env").write_text("APP_PORT=8002\nAI_REQUEST_TIMEOUT_SECONDS=22\n")
        expected = (8002, 22)
    if layer == "process":
        source = {"APP_PORT": "8003", "AI_REQUEST_TIMEOUT_SECONDS": "33"}
        expected = (8003, 33)
    original = source.copy()
    backend = module.load_config("local", source)
    ai = module.load_ai_config("local", source)
    assert (backend.app.port, ai.request_timeout_seconds) == expected
    assert source == original
