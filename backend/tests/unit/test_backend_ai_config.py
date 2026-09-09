from pathlib import Path

import pytest

import core.config as module


@pytest.mark.parametrize("profile", ["local", "test", "dev", "prod"])
def test_backend_ai_binding_never_reads_private_files(profile, tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("AI_GENERAL_API_KEY=must-not-be-read\n")
    monkeypatch.setattr(module, "BACKEND_ROOT", tmp_path)
    assert module.load_ai_config(profile, {}).openai is None
    configured = module.load_ai_config(profile, {"AI_GENERAL_API_KEY": "injected"})
    assert configured.openai is not None
    assert configured.openai.api_key.get_secret_value() == "injected"


def test_copied_example_keeps_safe_public_defaults(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[2]
    (tmp_path / ".env.local").write_text((root / ".env.local").read_text())
    (tmp_path / ".env").write_text((root / ".env.example").read_text())
    monkeypatch.setattr(module, "BACKEND_ROOT", tmp_path)
    config = module.load_config(
        "local", {"DB_URL": "postgresql://synthetic:synthetic@localhost/db"}
    )
    assert not config.f3.allow_synthetic_prototype
    assert not config.chatbot.enabled
    assert module.load_ai_config("local", {}).f2.provider_status.value == "offline"
