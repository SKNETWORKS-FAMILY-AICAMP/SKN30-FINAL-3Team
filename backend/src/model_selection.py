"""Preview or explicitly apply the AI-owned selection to one brokerage/capability."""

from __future__ import annotations

import argparse
import json
from enum import StrEnum

from brokerage_ai.core.model_catalog import GeneralSelection
from sqlalchemy import text
from sqlmodel import Session

from core.config import AppEnvironment, get_config, load_ai_config
from domain.engine import create_database_engine
from synthetic_seed import require_local_seed_target


class Capability(StrEnum):
    POSITION_CARD = "POSITION_CARD"
    BROKERAGE_JUDGMENT = "BROKERAGE_JUDGMENT"
    CHATBOT = "CHATBOT"


def apply_selection(
    session: Session, brokerage_id: int, capability: Capability, selection: GeneralSelection
) -> None:
    """Caller holds an explicit maintenance window. Transaction preserves old versions."""
    if (
        session.execute(
            text("SELECT id FROM brokerage WHERE id=:id FOR UPDATE"), {"id": brokerage_id}
        ).scalar_one_or_none()
        is None
    ):
        raise ValueError("brokerage does not exist")
    for table, predicate in (
        ("agent_run", "status NOT IN ('COMPLETED','FAILED_TERMINAL','SUPERSEDED')"),
        ("chat_request", "status IN ('ACCEPTED','RUNNING')"),
    ):
        if session.execute(
            text(f"SELECT count(*) FROM {table} WHERE brokerage_id=:id AND {predicate}"),
            {"id": brokerage_id},
        ).scalar_one():
            raise ValueError("settle all queued/in-progress requests before changing models")
    route = selection.route
    params = dict(
        id=brokerage_id,
        capability=capability.value,
        provider=route.provider.value,
        model=route.model,
        revision=selection.revision,
        alias=route.endpoint_alias,
    )
    current = session.execute(
        text(
            "SELECT provider,model_name,model_version,endpoint_alias FROM ai_model_config "
            "WHERE brokerage_id=:id AND capability=:capability AND is_active=TRUE "
            "ORDER BY config_version DESC,id DESC LIMIT 1"
        ),
        params,
    ).one_or_none()
    if current is not None and tuple(current) == (
        route.provider.value,
        route.model,
        selection.revision,
        route.endpoint_alias,
    ):
        return
    version = session.execute(
        text(
            "SELECT COALESCE(MAX(config_version),0)+1 FROM ai_model_config "
            "WHERE brokerage_id=:id AND capability=:capability"
        ),
        params,
    ).scalar_one()
    session.execute(
        text(
            "UPDATE ai_model_config SET is_active=FALSE "
            "WHERE brokerage_id=:id AND capability=:capability"
        ),
        params,
    )
    session.execute(
        text(
            "INSERT INTO ai_model_config (brokerage_id,capability,config_key,config_version,"
            "provider,model_name,model_version,endpoint_alias,parameters,is_active) "
            "VALUES (:id,:capability,'ai-selection',:version,:provider,:model,:revision,"
            ":alias,'{}'::jsonb,TRUE)"
        ),
        {**params, "version": version},
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brokerage-id", type=int, required=True)
    parser.add_argument("--capability", type=Capability, choices=list(Capability), required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--workloads-stopped", action="store_true")
    parser.add_argument("--shared-dev", action="store_true")
    args = parser.parse_args()
    try:
        if args.brokerage_id < 1:
            raise ValueError("brokerage ID must be positive")
        config = get_config()
        ai = load_ai_config(config.app.environment.value)
        if config.app.environment is AppEnvironment.LOCAL:
            require_local_seed_target(config)
        elif config.app.environment is not AppEnvironment.DEV or not args.shared_dev:
            raise ValueError("only local or explicitly selected shared dev is supported")
        if args.apply:
            if not args.workloads_stopped:
                raise ValueError("stop API/Worker before applying the model selection")
            if ai.openai is None and not ai.llm_endpoints:
                raise ValueError("configure the selected provider before applying")
            engine = create_database_engine(config)
            try:
                with Session(engine) as session, session.begin():
                    apply_selection(session, args.brokerage_id, args.capability, ai.general)
            finally:
                engine.dispose()
        print(
            json.dumps(
                dict(
                    applied=args.apply,
                    brokerage_id=args.brokerage_id,
                    capability=args.capability.value,
                    provider=ai.general.provider.value,
                    model=ai.general.model.value,
                )
            )
        )
    except ValueError as error:
        parser.exit(
            2,
            str(error) + "\n"
            if type(error) is ValueError
            else "Invalid configuration; values hidden.\n",
        )
    except Exception:
        parser.exit(
            2, "Model selection failed; check configuration and DB access. Values hidden.\n"
        )


if __name__ == "__main__":
    main()
