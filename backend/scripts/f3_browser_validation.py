"""Bounded real HTTP/PostgreSQL/Worker validation using explicit test generators.

Run only against a disposable local *_validation database with the F3_SYNTHETIC seed.
This does not add a fake-model switch to the application or call an external model.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import threading
from pathlib import Path
from urllib.parse import urlparse

import httpx
from dotenv import dotenv_values
from sqlalchemy import text
from sqlmodel import Session, create_engine

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "backend/src"), str(ROOT / "backend/tests/integration")]

from brokerage_ai.f3 import (  # noqa: E402
    BROKERAGE_JUDGMENT_PROMPT_VERSION,
    BROKERAGE_JUDGMENT_WORKFLOW_VERSION,
    POSITION_CARD_PROMPT_VERSION,
    POSITION_CARD_WORKFLOW_VERSION,
    BrokerageJudgmentGeneratorVersions,
    InputPrivacyMode,
    PositionCardGeneratorVersions,
)
from brokerage_judgment_fixtures import FakeCardGenerator, FakeJudgmentGenerator  # noqa: E402

from domain.agent_execution import automation, pipeline  # noqa: E402
from domain.agent_execution.anchor_card import GenerationBinding  # noqa: E402
from domain.agent_execution.judgment import JudgmentBinding  # noqa: E402
from f3_worker_reliability import execution_slot, renew_lease  # noqa: E402
from worker import build_worker_id, run_worker_loop  # noqa: E402


class ValidationCards(FakeCardGenerator):
    @property
    def versions(self) -> PositionCardGeneratorVersions:
        return PositionCardGeneratorVersions(
            prompt_version=POSITION_CARD_PROMPT_VERSION,
            workflow_version=POSITION_CARD_WORKFLOW_VERSION,
        )


class ValidationJudgments(FakeJudgmentGenerator):
    @property
    def versions(self) -> BrokerageJudgmentGeneratorVersions:
        return BrokerageJudgmentGeneratorVersions(
            prompt_version=BROKERAGE_JUDGMENT_PROMPT_VERSION,
            workflow_version=BROKERAGE_JUDGMENT_WORKFLOW_VERSION,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-synthetic-validation", action="store_true", required=True)
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8103")
    args = parser.parse_args()
    if urlparse(args.api_base_url).hostname not in {"localhost", "127.0.0.1"}:
        parser.error("only a local validation API is allowed")
    values = dotenv_values(ROOT / "backend/.env")
    engine = create_engine(os.environ.get("DB_URL") or values.get("DB_URL") or "")
    if engine.url.host not in {"localhost", "127.0.0.1"} or not (
        engine.url.database or ""
    ).endswith("_validation"):
        parser.error("only a disposable local *_validation database is allowed")
    config_ids = {}
    with Session(engine) as session:
        tenant = session.execute(
            text("SELECT id FROM brokerage WHERE name='F3_SYNTHETIC 합성중개사무소'")
        ).scalar_one()
        listing = (
            session.execute(
                text(
                    "SELECT id,row_version,sale_price FROM property_listing "
                    "WHERE brokerage_id=:tenant AND custom_fields->>'seed_key'='L1'"
                ),
                {"tenant": tenant},
            )
            .mappings()
            .one()
        )
        target = dict(listing)
        requirement = session.execute(
            text(
                "SELECT id FROM property_requirement "
                "WHERE brokerage_id=:tenant AND custom_fields->>'seed_key'='R1'"
            ),
            {"tenant": tenant},
        ).scalar_one()
        for capability, model in (
            ("POSITION_CARD", "fake-delegate"),
            ("BROKERAGE_JUDGMENT", "fake-broker"),
        ):
            found = session.execute(
                text(
                    "SELECT id FROM ai_model_config WHERE brokerage_id=:tenant "
                    "AND capability=:capability AND config_key='browser-validation-fixture'"
                ),
                {"tenant": tenant, "capability": capability},
            ).scalar_one_or_none()
            if found is None:
                found = session.execute(
                    text("""INSERT INTO ai_model_config
                    (brokerage_id,capability,config_key,config_version,provider,model_name,
                     model_version,endpoint_alias,is_active)
                    SELECT :tenant,:capability,'browser-validation-fixture',
                        COALESCE(max(config_version),0)+1,'vllm',:model,
                        'deterministic-test-generator:v1','validation-only',true
                    FROM ai_model_config WHERE brokerage_id=:tenant RETURNING id"""),
                    {"tenant": tenant, "capability": capability, "model": model},
                ).scalar_one()
            config_ids[capability] = found
        session.commit()
    with httpx.Client(base_url=args.api_base_url, timeout=30) as client:
        client.post("/api/v1/auth/development-session").raise_for_status()
        me = client.get("/api/v1/auth/me").json()
        if me["user"]["brokerage_id"] != tenant:
            raise RuntimeError("the validation API session belongs to another brokerage")
        headers = {"X-CSRF-Token": me["csrf_token"]}
        saved = client.patch(
            f"/api/v1/property-listings/{target['id']}",
            headers=headers,
            json={"row_version": target["row_version"], "sale_price": target["sale_price"] - 1},
        )
        saved.raise_for_status()
        with Session(engine) as session:
            automation.expand_changes(session, debounce_seconds=0, batch_size=1)
            automation.enqueue_changed_targets(session, batch_size=2)
        requested = client.post(
            "/api/v1/f3/runs",
            headers=headers,
            json={"anchor_type": "REQUIREMENT", "anchor_id": requirement},
        )
        requested.raise_for_status()
    stop = threading.Event()
    worker_id = build_worker_id()
    completed = []
    generator = ValidationJudgments()
    bindings = pipeline.ExecutionBindings(
        card=GenerationBinding(
            generator=ValidationCards(),
            model_config_id=config_ids["POSITION_CARD"],
            input_privacy_mode=InputPrivacyMode.SYNTHETIC_PROTOTYPE,
        ),
        judgment=JudgmentBinding(
            generator=generator,
            model_config_id=config_ids["BROKERAGE_JUDGMENT"],
            input_privacy_mode=InputPrivacyMode.SYNTHETIC_PROTOTYPE,
        ),
    )
    with asyncio.Runner() as runner:

        def handle(session, run):
            with renew_lease(engine, run, worker_id):
                outcome = pipeline.drive_run(session, run, worker_id, bindings, runner.get_loop())
            completed.append(
                {
                    "run_id": run.id,
                    "anchor_type": "LISTING" if run.target_listing_id else "REQUIREMENT",
                    "anchor_id": run.target_listing_id or run.target_requirement_id,
                    "trigger_type": run.trigger_type,
                    "outcome": outcome.value,
                }
            )
            if len(completed) >= 2:
                stop.set()

        timer = threading.Timer(30, stop.set)
        timer.start()
        try:
            run_worker_loop(
                stop_event=stop,
                session_factory=lambda: Session(engine),
                handle=handle,
                worker_id=worker_id,
                idle_wait_seconds=0.25,
                claim_slot=lambda: execution_slot(engine),
            )
        finally:
            timer.cancel()
    with httpx.Client(base_url=args.api_base_url, timeout=30) as client:
        client.post("/api/v1/auth/development-session").raise_for_status()
        for item in completed:
            response = client.get(
                f"/api/v1/f3/judgment-targets/{item['anchor_type']}/{item['anchor_id']}"
            )
            response.raise_for_status()
            body = response.json()
            item.update(
                result_id=body["result_id"], freshness=body["freshness"], summary=body["summary"]
            )
    engine.dispose()
    print(
        json.dumps(
            {"model": "explicit deterministic test generator", "targets": completed},
            ensure_ascii=False,
            indent=2,
        )
    )
    if len(completed) != 2 or any(row["outcome"] != "COMPLETED" for row in completed):
        raise SystemExit("validation did not complete both targets")


if __name__ == "__main__":
    main()
