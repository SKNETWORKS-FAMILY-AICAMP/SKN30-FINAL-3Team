"""Preview or explicitly apply the AI-owned selection to one brokerage/capability."""

from __future__ import annotations

import argparse
import hashlib
import json
from enum import StrEnum

from brokerage_ai.core.model_catalog import GeneralModel, GeneralSelection
from brokerage_ai.core.types import ProviderKind
from sqlalchemy import text
from sqlmodel import Session

from core.config import AppEnvironment, get_config, load_ai_config
from domain.engine import create_database_engine
from synthetic_seed import require_local_seed_target


class Capability(StrEnum):
    POSITION_CARD = "POSITION_CARD"
    BROKERAGE_JUDGMENT = "BROKERAGE_JUDGMENT"
    CHATBOT = "CHATBOT"


def lock_selection_inputs(session: Session) -> None:
    # Maintenance-only, bounded transaction: prevent even writers that do not use
    # the brokerage row-lock convention from changing inputs after this snapshot.
    # EXCLUSIVE also conflicts with single-target SELECT FOR UPDATE (ROW SHARE),
    # so acquire brokerage first before downstream table locks; plain reads work.
    session.execute(text("SET LOCAL lock_timeout = '5s'"))
    session.execute(text("SET LOCAL statement_timeout = '30s'"))
    session.execute(
        text("LOCK TABLE brokerage, ai_model_config, agent_run, chat_request IN EXCLUSIVE MODE")
    )


def apply_selection(
    session: Session, brokerage_id: int, capability: Capability, selection: GeneralSelection
) -> None:
    """Caller holds an explicit maintenance window. Transaction preserves old versions."""
    lock_selection_inputs(session)
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
            "ORDER BY config_version DESC,id DESC"
        ),
        params,
    ).all()
    if len(current) == 1 and tuple(current[0]) == (
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


def selection_values(selection: GeneralSelection) -> dict:
    return dict(
        provider=selection.provider.value,
        model_name=selection.model.value,
        model_version=selection.revision,
        endpoint_alias=selection.route.endpoint_alias,
    )


def list_targets(session: Session, selection: GeneralSelection) -> dict:
    """Only operational IDs/configuration are returned; no brokerage contact information."""
    brokerages = session.execute(text("SELECT id FROM brokerage ORDER BY id")).scalars().all()
    current = (
        session.execute(
            text(
                "SELECT id,brokerage_id,capability,config_version,provider,model_name,"
                "model_version,"
                "endpoint_alias FROM ai_model_config WHERE is_active=TRUE "
                "ORDER BY brokerage_id,capability,id"
            )
        )
        .mappings()
        .all()
    )
    pending = {}
    for table, predicate in (
        ("agent_run", "status NOT IN ('COMPLETED','FAILED_TERMINAL','SUPERSEDED')"),
        ("chat_request", "status IN ('ACCEPTED','RUNNING')"),
    ):
        for row in session.execute(
            text(
                f"SELECT brokerage_id,count(*) AS count FROM {table} "
                f"WHERE {predicate} GROUP BY brokerage_id"
            )
        ).mappings():
            pending[row["brokerage_id"]] = pending.get(row["brokerage_id"], 0) + row["count"]
    desired = selection_values(selection)
    targets = []
    for brokerage_id in brokerages:
        for capability in Capability:
            rows = [
                dict(row)
                for row in current
                if row["brokerage_id"] == brokerage_id and row["capability"] == capability.value
            ]
            targets.append(
                dict(
                    brokerage_id=brokerage_id,
                    capability=capability.value,
                    current=rows,
                    compatible=all(
                        all(row[key] == value for key, value in desired.items()) for row in rows
                    ),
                    pending_work=pending.get(brokerage_id, 0),
                )
            )
    result: dict = dict(desired=desired, targets=targets)
    result["snapshot"] = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
    return result


def parse_target(value: str) -> tuple[int, Capability]:
    try:
        identifier, capability = value.split(":", 1)
        if int(identifier) < 1:
            raise ValueError
        return int(identifier), Capability(capability)
    except (ValueError, TypeError) as error:
        raise ValueError("target must be positive BROKERAGE_ID:CAPABILITY") from error


def apply_targets(
    session: Session,
    selection: GeneralSelection,
    targets: list[tuple[int, Capability]],
    expected_snapshot: str,
) -> dict:
    """One transaction checks the reviewed snapshot, then changes explicit targets only."""
    lock_selection_inputs(session)
    preview = list_targets(session, selection)
    if preview["snapshot"] != expected_snapshot:
        raise ValueError("model targets changed after review; list and confirm again")
    selected = set(targets)
    known = {(row["brokerage_id"], Capability(row["capability"])) for row in preview["targets"]}
    if not selected <= known:
        raise ValueError("selected brokerage/capability does not exist")
    for row in preview["targets"]:
        target = (row["brokerage_id"], Capability(row["capability"]))
        if row["pending_work"]:
            raise ValueError("settle all queued/in-progress requests before changing models")
        if row["current"] and not row["compatible"] and target not in selected:
            raise ValueError("incompatible active configuration remains outside selected targets")
    applied, skipped = [], []
    for brokerage_id, capability in sorted(selected):
        row = next(
            row
            for row in preview["targets"]
            if row["brokerage_id"] == brokerage_id and row["capability"] == capability.value
        )
        key = f"{brokerage_id}:{capability.value}"
        if row["current"] and row["compatible"]:
            skipped.append(key)
        else:
            apply_selection(session, brokerage_id, capability, selection)
            applied.append(key)
    return dict(applied=applied, skipped=skipped)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brokerage-id", type=int)
    parser.add_argument("--capability", type=Capability, choices=list(Capability))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--workloads-stopped", action="store_true")
    parser.add_argument("--shared-dev", action="store_true")
    parser.add_argument("--list-targets", action="store_true")
    parser.add_argument("--target", action="append", default=[])
    parser.add_argument("--expected-snapshot")
    parser.add_argument("--provider", type=ProviderKind, choices=list(ProviderKind))
    parser.add_argument("--model", type=GeneralModel, choices=list(GeneralModel))
    args = parser.parse_args()
    try:
        if args.brokerage_id is not None and args.brokerage_id < 1:
            raise ValueError("brokerage ID must be positive")
        config = get_config()
        if config.app.environment is AppEnvironment.LOCAL:
            require_local_seed_target(config)
        elif config.app.environment is not AppEnvironment.DEV or not args.shared_dev:
            raise ValueError("only local or explicitly selected shared dev is supported")
        if args.list_targets or args.expected_snapshot is not None:
            if args.provider is None or args.model is None:
                raise ValueError("explicit provider and model required for target operations")
            if args.brokerage_id is not None or args.capability is not None:
                raise ValueError("use --target for target operations")
            if args.list_targets and args.apply:
                raise ValueError("listing never applies changes")
            if args.expected_snapshot is not None and (
                not args.apply or not args.workloads_stopped
            ):
                raise ValueError("target application requires --apply --workloads-stopped")
            selection = GeneralSelection(provider=args.provider, model=args.model)
            targets = [parse_target(value) for value in args.target]
            engine = create_database_engine(config)
            try:
                with Session(engine) as session, session.begin():
                    if args.list_targets:
                        result = list_targets(session, selection)
                    else:
                        if not isinstance(args.expected_snapshot, str):
                            raise ValueError("target application requires an expected snapshot")
                        result = apply_targets(session, selection, targets, args.expected_snapshot)
                print(json.dumps(result))
            finally:
                engine.dispose()
            return
        if args.target or args.provider is not None or args.model is not None:
            raise ValueError("explicit model/targets require --list-targets or --expected-snapshot")
        if args.brokerage_id is None or args.capability is None:
            raise ValueError("brokerage ID and capability are required")
        ai = load_ai_config(config.app.environment.value)
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
