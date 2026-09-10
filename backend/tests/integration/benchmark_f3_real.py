"""Synthetic-only before/after Worker benchmark. Never prints model/user content."""

import argparse
import asyncio
import json
import os
from pathlib import Path
from time import perf_counter
from urllib.parse import urlsplit

from brokerage_ai.runtime import create_ai_runtime
from sqlalchemy import text
from sqlmodel import Session

from core.config import get_config, load_ai_config
from domain.agent_execution import pipeline, results, service
from domain.agent_execution.models import AnchorType
from domain.engine import create_database_engine
from worker import process_run

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--confirm-isolated", action="store_true", required=True)
parser.add_argument("--label", required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--repetitions", type=int, choices=range(1, 31), default=3)
parser.add_argument("--anchor-type", choices=("LISTING", "REQUIREMENT"))
parser.add_argument("--cache", choices=("cold", "warm"))
args = parser.parse_args()
label = args.label
config = get_config()
if config.app.environment.value != "local" or urlsplit(
    config.db.url.get_secret_value()
).hostname not in {"localhost", "127.0.0.1", "::1"}:
    parser.error("a dedicated local synthetic database is required")
engine = create_database_engine(config)
ai_config = load_ai_config("local", os.environ)
runtime = create_ai_runtime(ai_config)
route = ai_config.general.route
provider = runtime.providers.get_llm(route.provider, route.endpoint_alias)
original_generate = provider.generate_structured
calls = []
stages = []


async def generate(*args, **kwargs):
    begin = perf_counter()
    request = args[0] if args else kwargs["request"]
    record = {
        "stage": active_stage,
        "ok": False,
        "input_chars": sum(len(message.content) for message in request.messages),
    }
    try:
        result = await original_generate(*args, **kwargs)
        record["ok"] = True
        record["provider_ms"] = result.diagnostics.latency_ms
        if result.diagnostics.usage is not None:
            record["usage"] = result.diagnostics.usage.model_dump()
        return result
    except Exception as error:
        record["error_type"] = type(error).__name__
        context = error.__context__
        http_status = getattr(context, "status_code", None)
        if isinstance(http_status, int):
            record["http_status"] = http_status
        raise
    finally:
        record["wall_ms"] = round((perf_counter() - begin) * 1000, 2)
        calls.append(record)
        print(json.dumps({"model_call": record}), flush=True)


provider.generate_structured = generate
original_advance = pipeline.advance_run
active_stage = ""


def advance(*args, **kwargs):
    global active_stage
    active_stage = pipeline.failure_stage(args[1].status).value
    begin = perf_counter()
    outcome = original_advance(*args, **kwargs)
    stages.append(
        {
            "stage": active_stage,
            "wall_ms": round((perf_counter() - begin) * 1000, 2),
            "outcome": outcome.value,
        }
    )
    return outcome


pipeline.advance_run = advance
loop = asyncio.new_event_loop()
records = []
try:
    with Session(engine) as db:
        pending = db.execute(
            text(
                "SELECT count(*) FROM agent_run WHERE status NOT IN "
                "('COMPLETED','FAILED_TERMINAL','SUPERSEDED')"
            )
        ).scalar_one()
        if pending:
            raise RuntimeError("benchmark requires an idle dedicated database without a Worker")
        b = db.execute(
            text("SELECT id FROM brokerage WHERE name='F3_SYNTHETIC 합성중개사무소'")
        ).scalar_one()
        u = db.execute(
            text("SELECT id FROM app_user WHERE brokerage_id=:b AND login_id='f3_synthetic_dev'"),
            {"b": b},
        ).scalar_one()
        # Fixed seed anchors, independent of sequence-generated IDs.
        listing = db.execute(
            text(
                "SELECT id FROM property_listing WHERE brokerage_id=:b "
                "AND custom_fields->>'seed_key'='L1'"
            ),
            {"b": b},
        ).scalar_one()
        requirement = db.execute(
            text(
                "SELECT id FROM property_requirement WHERE brokerage_id=:b "
                "AND custom_fields->>'seed_key'='R1'"
            ),
            {"b": b},
        ).scalar_one()
        db.rollback()
        for kind, target in [("LISTING", listing), ("REQUIREMENT", requirement)]:
            if args.anchor_type and kind != args.anchor_type:
                continue
            for repetition in range(1, args.repetitions + 1):
                for cache in [args.cache] if args.cache else ["cold", "warm"]:
                    if cache == "cold":
                        db.execute(
                            text(
                                "UPDATE negotiation_position_analysis SET invalidated_at=now() "
                                "WHERE brokerage_id=:b AND invalidated_at IS NULL"
                            ),
                            {"b": b},
                        )
                        db.commit()
                    calls.clear()
                    stages.clear()
                    begin = perf_counter()
                    queued = service.queue_cross_judgment_run(db, b, u, AnchorType(kind), target)
                    run_id = queued.id
                    assert run_id is not None
                    intake_ms = (perf_counter() - begin) * 1000
                    claimed = service.claim_next_run(db, "f3-benchmark")
                    assert claimed and claimed.id == run_id, (
                        "Unexpected pending execution in dedicated benchmark DB"
                    )
                    picked_ms = (perf_counter() - begin) * 1000
                    outcome = process_run(db, claimed, "f3-benchmark", runtime, loop)
                    total_ms = (perf_counter() - begin) * 1000
                    value = results.load_run_result(db, b, run_id)
                    entry = dict(
                        label=label,
                        provider=route.provider.value,
                        model=route.model,
                        timeout_seconds=ai_config.general_timeout_seconds,
                        anchor_type=kind,
                        cache=cache,
                        repetition=repetition,
                        run_id=run_id,
                        outcome=outcome.value,
                        status=value.run.status,
                        candidates=value.total_count,
                        carded=value.carded_count,
                        intake_ms=round(intake_ms, 2),
                        pickup_ms=round(picked_ms, 2),
                        total_ms=round(total_ms, 2),
                        stages=list(stages),
                        model_calls=list(calls),
                    )
                    records.append(entry)
                    args.output.write_text(json.dumps(records, ensure_ascii=False, indent=2))
                    print(
                        json.dumps(
                            {k: v for k, v in entry.items() if k not in ("stages", "model_calls")},
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
                    db.rollback()
                    if value.run.status != "COMPLETED":
                        raise SystemExit("Incomplete run recorded; stop before queuing another run")
finally:
    loop.run_until_complete(runtime.close())
    loop.run_until_complete(loop.shutdown_asyncgens())
    loop.close()
    engine.dispose()
