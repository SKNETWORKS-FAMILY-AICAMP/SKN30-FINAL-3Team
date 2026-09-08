"""Explicit model-only activation; never reset synthetic ledgers or run history."""

from __future__ import annotations

import json

import psycopg
from brokerage_ai import ModelRoute, ProviderKind

from core.config import AppEnvironment, Config, load_ai_config
from synthetic_seed import require_local_seed_target

MODEL = "unsloth/Qwen3.8-27B-unsloth-bnb-4bit"
REVISION = "8aa5f05d26b7205477066e1449e0af13f762a299"
ALIAS = "general-dev-gpu"
PROFILE = "dev-qwen38-vllm-bnb"
# Deployment contract allowlist; a test checks this against Infra's pinned manifest.
MODEL_PROFILES = {
    MODEL: (PROFILE, REVISION),
    "Qwen/Qwen3.8-27B-FP8": ("qwen38-27b-fp8", "017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"),
    "Qwen/Qwen3-14B-AWQ": ("qwen3-14b-awq", "31c69efc29464b6bb0aee1398b5a7b50a99340c3"),
    "Qwen/Qwen3-32B-AWQ": ("qwen3-32b-awq", "0499c3ac83fdef8810b907a23894ba91e95eddd8"),
}
CAPABILITIES = ("POSITION_CARD", "BROKERAGE_JUDGMENT")


def general_route(model: str = MODEL) -> ModelRoute:
    if model not in MODEL_PROFILES:
        raise ValueError("unsupported general model")
    return ModelRoute(provider=ProviderKind.VLLM, model=model, endpoint_alias=ALIAS)


def activate_general(
    config: Config,
    brokerage_id: int,
    *,
    apply: bool,
    shared_dev: bool,
    workloads_stopped: bool,
    model: str = MODEL,
) -> None:
    general_route(model)
    profile, revision = MODEL_PROFILES[model]
    if brokerage_id < 1:
        raise ValueError("a positive brokerage ID is required")
    if config.app.environment is AppEnvironment.LOCAL:
        require_local_seed_target(config)
        if shared_dev:
            raise ValueError("local model selection cannot target shared dev")
    elif config.app.environment is not AppEnvironment.DEV or not shared_dev:
        raise ValueError("dev activation requires explicit --shared-dev")
    if apply and not workloads_stopped:
        raise ValueError("stop API/Worker and confirm workloads before activation")
    ai = load_ai_config(config.app.environment.value)
    if not any(endpoint.alias == ALIAS for endpoint in ai.llm_endpoints):
        raise ValueError("general GPU endpoint must be configured first")
    url = config.db.url.get_secret_value().replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(url, connect_timeout=5) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT id FROM brokerage WHERE id=%s FOR UPDATE", (brokerage_id,))
        if cursor.fetchone() is None:
            raise ValueError("brokerage does not exist")
        cursor.execute(
            "SELECT count(*) FROM agent_run WHERE brokerage_id=%s "
            "AND status NOT IN ('COMPLETED', 'FAILED_TERMINAL', 'SUPERSEDED')",
            (brokerage_id,),
        )
        row = cursor.fetchone()
        if row is None or row[0]:
            raise ValueError("settle queued/in-progress runs before changing the model")
        if not apply:
            return
        for capability in CAPABILITIES:
            cursor.execute(
                "SELECT provider, model_name, model_version, endpoint_alias "
                "FROM ai_model_config "
                "WHERE brokerage_id=%s AND capability=%s "
                "AND config_key=%s AND config_version=1",
                (brokerage_id, capability, profile),
            )
            existing = cursor.fetchone()
            expected = ("vllm", model, revision, ALIAS)
            if existing is not None and existing != expected:
                raise ValueError("existing pinned model profile differs; do not overwrite it")
            cursor.execute(
                "UPDATE ai_model_config SET is_active=FALSE "
                "WHERE brokerage_id=%s AND capability=%s",
                (brokerage_id, capability),
            )
            cursor.execute(
                """INSERT INTO ai_model_config (
                brokerage_id, capability, config_key, config_version, provider,
                model_name, model_version, endpoint_alias, parameters, is_active)
                VALUES (%s,%s,%s,1,'vllm',%s,%s,%s,'{}'::jsonb,TRUE)
                ON CONFLICT (brokerage_id, capability, config_key, config_version)
                DO UPDATE SET is_active=TRUE""",
                (brokerage_id, capability, profile, model, revision, ALIAS),
            )
    print(
        json.dumps(
            {
                "model_activation": "complete",
                "brokerage_id": brokerage_id,
                "capabilities": CAPABILITIES,
                "model": model,
            }
        )
    )
