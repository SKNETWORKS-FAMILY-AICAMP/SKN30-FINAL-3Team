"""Explicit, local-only CHATBOT model selection without changing F3 or business data."""

from __future__ import annotations

import argparse
import json

from sqlalchemy import text
from sqlmodel import Session

from core.config import AppEnvironment, Config, get_config, load_ai_config
from domain.engine import create_database_engine
from synthetic_seed import require_local_seed_target

PROFILES = {
    "local-openai": ("openai", "gpt-5.6-luna", None, None),
    "dev-qwen38-vllm-bnb": (
        "vllm",
        "unsloth/Qwen3.8-27B-unsloth-bnb-4bit",
        "8aa5f05d26b7205477066e1449e0af13f762a299",
        "general-dev-gpu",
    ),
}


def activate_chatbot(config: Config, brokerage_id: int, profile: str, *, apply: bool) -> None:
    if config.app.environment is not AppEnvironment.LOCAL:
        raise ValueError("CHATBOT model selection only supports a local database")
    require_local_seed_target(config)
    if brokerage_id < 1 or profile not in PROFILES:
        raise ValueError("a valid brokerage and model profile are required")
    ai_config = load_ai_config(config.app.environment.value)
    provider, model, revision, alias = PROFILES[profile]
    if provider == "openai" and ai_config.openai is None:
        raise ValueError("configure AI_OPENAI_API_KEY first")
    if alias is not None and not any(e.alias == alias for e in ai_config.llm_endpoints):
        raise ValueError("configure the general-dev-gpu endpoint first")
    engine = create_database_engine(config)
    try:
        with Session(engine) as session, session.begin():
            if (
                session.execute(
                    text("SELECT id FROM brokerage WHERE id=:id FOR UPDATE"), {"id": brokerage_id}
                ).scalar_one_or_none()
                is None
            ):
                raise ValueError("brokerage does not exist")
            active = session.execute(
                text(
                    "SELECT count(*) FROM chat_request WHERE brokerage_id=:id "
                    "AND status IN ('ACCEPTED','RUNNING')"
                ),
                {"id": brokerage_id},
            ).scalar_one()
            if active:
                raise ValueError("settle active chatbot requests before changing models")
            existing = session.execute(
                text(
                    "SELECT provider,model_name,model_version,endpoint_alias FROM ai_model_config "
                    "WHERE brokerage_id=:id AND capability='CHATBOT' AND config_key=:profile "
                    "AND config_version=1"
                ),
                {"id": brokerage_id, "profile": profile},
            ).one_or_none()
            if existing is not None and tuple(existing) != (provider, model, revision, alias):
                raise ValueError("existing pinned CHATBOT profile differs; do not overwrite it")
            if not apply:
                return
            session.execute(
                text(
                    "UPDATE ai_model_config SET is_active=FALSE "
                    "WHERE brokerage_id=:id AND capability='CHATBOT'"
                ),
                {"id": brokerage_id},
            )
            session.execute(
                text(
                    "INSERT INTO ai_model_config (brokerage_id,capability,config_key,"
                    "config_version,provider,model_name,model_version,endpoint_alias,is_active) "
                    "VALUES (:id,'CHATBOT',:profile,1,:provider,:model,:revision,:alias,TRUE) "
                    "ON CONFLICT (brokerage_id,capability,config_key,config_version) "
                    "DO UPDATE SET is_active=TRUE"
                ),
                dict(
                    id=brokerage_id,
                    profile=profile,
                    provider=provider,
                    model=model,
                    revision=revision,
                    alias=alias,
                ),
            )
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brokerage-id", type=int, required=True)
    parser.add_argument("--model-profile", choices=PROFILES, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        activate_chatbot(get_config(), args.brokerage_id, args.model_profile, apply=args.apply)
    except Exception:
        raise SystemExit(
            "CHATBOT model selection failed; check local DB and provider setup."
        ) from None
    print(
        json.dumps({"capability": "CHATBOT", "applied": args.apply, "profile": args.model_profile})
    )


if __name__ == "__main__":
    main()
