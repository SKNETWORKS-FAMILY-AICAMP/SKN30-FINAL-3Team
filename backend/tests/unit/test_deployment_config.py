"""Real renderer output must bind to the same AI contract as local configuration."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from brokerage_ai import bind_ai_config

root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(root / "infra/deploy/scripts"))
spec = importlib.util.spec_from_file_location(
    "deployment_env", root / "infra/deploy/scripts/render_env.py"
)
assert spec and spec.loader
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)


@pytest.mark.parametrize(
    "provider,model,extra,secrets",
    [
        (
            "openai",
            "gpt-5.6-luna",
            {},
            {"AI_OPENAI_API_KEY": "openai-secret", "AI_GENERAL_API_KEY": "gpu-secret"},
        ),
        (
            "bedrock",
            "global.openai.gpt-5.6-luna",
            {"AI_GENERAL_AWS_REGION": "ap-northeast-2"},
            {"AI_OPENAI_API_KEY": "unused", "AI_GENERAL_API_KEY": "unused"},
        ),
        (
            "vllm",
            "Qwen/Qwen3.8-27B-FP8",
            {"AI_GENERAL_BASE_URL": "https://server.example/v1"},
            {"AI_GENERAL_API_KEY": "gpu-secret"},
        ),
    ],
)
@pytest.mark.parametrize("chatbot", [False, True])
def test_renderer_roundtrip_keeps_role_and_provider_secret_scope(
    provider, model, extra, secrets, chatbot
):
    offline = dict(
        revision=1,
        status="offline",
        pod_id=None,
        sllm_release_id=None,
        sllm_base_url=None,
        stt_base_url=None,
        updated_at="2026-09-09T00:00:00Z",
    )
    api, worker, migration = renderer.build_process_environments(
        public={
            "backend": {"APP_ENV": "dev", "CHATBOT_ENABLED": str(chatbot).lower()},
            "ai": {
                "AI_GENERAL_PROVIDER": provider,
                "AI_GENERAL_MODEL": model,
                "AI_VLLM_ENDPOINT_SET": json.dumps(offline),
                **extra,
            },
        },
        runtime_url="runtime-db",
        migration_url="migration-db",
        ai_provider_keys=secrets,
    )
    for source in (api, worker):
        config = bind_ai_config(source, "dev")
        assert config.general.provider.value == provider
        assert config.general.model.value == model
        assert config.f2.provider_status.value == "offline"
        assert "_f2_status" not in source
        assert "AI_OPENAI_API_KEY" not in source
    if provider == "bedrock":
        assert "AI_GENERAL_API_KEY" not in api and "AI_GENERAL_API_KEY" not in worker
    else:
        assert ("AI_GENERAL_API_KEY" in api) is chatbot
        assert worker["AI_GENERAL_API_KEY"] == (
            "openai-secret" if provider == "openai" else "gpu-secret"
        )
    assert migration == {"DB_MIGRATION_URL": "migration-db"}
