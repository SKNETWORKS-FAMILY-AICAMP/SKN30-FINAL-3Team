"""Exercise the Infra launcher with isolated, synthetic files; never start services."""

import importlib.util
import sys
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "local_launcher", Path(__file__).resolve().parents[3] / "infra/local/run.py"
)
assert spec and spec.loader
launcher = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = launcher
spec.loader.exec_module(launcher)


def make_files(root):
    for module in ("ai", "backend"):
        (root / module).mkdir()
    (root / "backend/.env.local").write_text("APP_ENV=local\nAPP_PORT=8000\nCHATBOT_ENABLED=true\n")
    (root / "backend/.env").write_text("APP_PORT=8001\nDB_URL=synthetic-db\n")
    (root / "ai/.env.local").write_text("AI_GENERAL_PROVIDER=openai\n")
    (root / "ai/.env").write_text(
        "AI_GENERAL_API_KEY=${PRIVATE}\nAI_VLLM_SLLM_API_KEY=f2-private\n"
    )


def test_injection_ownership_precedence_and_worker_secret_scope(tmp_path):
    make_files(tmp_path)
    source = {"APP_PORT": "8002"}
    api = launcher.environment(tmp_path, launcher.Role.API, source)
    worker = launcher.environment(tmp_path, launcher.Role.WORKER, source)
    assert api["APP_PORT"] == "8002"
    assert api["AI_GENERAL_API_KEY"] == "${PRIVATE}"
    assert worker["AI_GENERAL_API_KEY"] == "${PRIVATE}"
    assert "AI_VLLM_SLLM_API_KEY" not in worker
    assert source == {"APP_PORT": "8002"}


def test_wrong_owner_is_rejected_before_process_override(tmp_path):
    make_files(tmp_path)
    (tmp_path / "backend/.env").write_text("AI_GENERAL_API_KEY=do-not-print\n")
    with pytest.raises(ValueError, match="wrong owner") as exc:
        launcher.environment(tmp_path, launcher.Role.API, {"AI_GENERAL_API_KEY": "override"})
    assert "do-not-print" not in str(exc.value)


def test_nonlocal_cannot_use_local_files(tmp_path):
    with pytest.raises(ValueError, match="APP_ENV=local"):
        launcher.environment(tmp_path, launcher.Role.API, {"APP_ENV": "dev"})


def test_api_without_chatbot_receives_no_general_secret(tmp_path):
    make_files(tmp_path)
    api = launcher.environment(tmp_path, launcher.Role.API, {"CHATBOT_ENABLED": "false"})
    assert "AI_GENERAL_API_KEY" not in api
    assert "AI_GENERAL_BASE_URL" not in api
    assert "AI_VLLM_SLLM_API_KEY" in api
