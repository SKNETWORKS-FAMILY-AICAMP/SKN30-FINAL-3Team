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


@pytest.mark.parametrize("include_local_overrides", [False, True])
def test_copied_example_respects_explicit_local_overrides(
    tmp_path, monkeypatch, include_local_overrides
):
    root = Path(__file__).resolve().parents[2]
    local_values = (root / ".env.local").read_text().splitlines()
    if not include_local_overrides:
        local_values = [
            line
            for line in local_values
            if not line.startswith(("F3_ALLOW_SYNTHETIC_PROTOTYPE=", "CHATBOT_ENABLED="))
        ]
    (tmp_path / ".env.local").write_text("\n".join(local_values) + "\n")
    (tmp_path / ".env").write_text((root / ".env.example").read_text())
    monkeypatch.setattr(module, "BACKEND_ROOT", tmp_path)
    config = module.load_config(
        "local", {"DB_URL": "postgresql://synthetic:synthetic@localhost/db"}
    )
    assert config.f3.allow_synthetic_prototype is include_local_overrides
    assert config.chatbot.enabled is include_local_overrides
    assert module.load_ai_config("local", {}).f2.provider_status.value == "offline"
