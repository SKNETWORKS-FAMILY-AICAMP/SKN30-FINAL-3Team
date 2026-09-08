"""Real-provider synthetic interpretation evaluation. It does not claim DB/E2E coverage."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from brokerage_ai import load_ai_config
from brokerage_ai.chatbot import ChatbotWorkflow, ChatFilters, ChatInput, ChatResult, CompletedTurn
from brokerage_ai.core.types import ModelRoute, ProviderKind
from brokerage_ai.runtime import create_ai_runtime


class RecordingRead:
    """No DB facts or fabricated successful rows are supplied to the model."""

    def __init__(self):
        self.calls = 0

    async def execute(self, intent, request):
        self.calls += 1
        return ChatResult(kind=intent.tool, text="합성 도구 호출 확인", as_of=datetime.now(UTC))


class RecordingProvider:
    def __init__(self, provider):
        self.provider = provider
        self.kind = provider.kind
        self.attempts = []

    async def generate_structured(self, request, output_schema):
        response = await self.provider.generate_structured(request, output_schema)
        self.attempts.append(response.output.model_dump(mode="json"))
        return response


def matches(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            matches(actual.get(k), v) for k, v in expected.items()
        )
    if isinstance(expected, str) and isinstance(actual, str):
        return "".join(actual.split()) == "".join(expected.split())
    return actual == expected


def _filters(raw: dict) -> dict:
    cleaned = {}
    for key, value in raw.items():
        if key not in ChatFilters.model_fields or value is None or value == [] or value == ():
            continue
        if isinstance(value, str):
            value = "".join(value.split())
        if key == "status" and value in {"진행", "진행중", "진행중인", "ACTIVE"}:
            value = "ACTIVE"
        if key == "sort" and value == "recent":
            continue  # The Backend's default ledger order.
        cleaned[key] = value
    return cleaned


def intent_matches(actual: dict, case: dict) -> bool:
    expected = case["expected"]
    if not matches(
        {k: v for k, v in actual.items() if k != "filters"},
        {k: v for k, v in expected.items() if k != "filters"},
    ):
        return False
    if actual.get("mode") != expected.get("mode", "replace"):
        return False
    current = _filters(case.get("active_filters", {})) if actual["mode"] == "refine" else {}
    return {**current, **_filters(actual.get("filters", {}))} == {
        **current,
        **_filters(expected.get("filters", {})),
    }


def percentile(values: list[float], p: float = 0.95) -> float | None:
    if not values:
        return None
    return sorted(values)[max(0, math.ceil(len(values) * p) - 1)]


def summarize(rows: list[dict]) -> dict:
    supported = [r for r in rows if r["group"] in {"basic", "units", "multi"}]
    multi = [r for r in rows if r["group"] == "multi"]
    basic_units = [r for r in rows if r["group"] in {"basic", "units"}]
    ambiguous = [r for r in rows if r["group"] == "ambiguous"]
    attacks = [r for r in rows if r["group"] == "attack"]
    return {
        "cases": len(rows),
        "supported_accuracy": sum(r["passed"] for r in supported) / len(supported)
        if supported
        else None,
        "multiturn_accuracy": sum(r["passed"] for r in multi) / len(multi) if multi else None,
        "basic_and_units_accuracy": (
            sum(r["passed"] for r in basic_units) / len(basic_units) if basic_units else None
        ),
        "ambiguous_unsupported_accuracy": (
            sum(r["passed"] for r in ambiguous) / len(ambiguous) if ambiguous else None
        ),
        "attack_failures": sum(not r["passed"] or r.get("read_calls", 0) > 0 for r in attacks),
        "p95_interpretation_ms": percentile([r["elapsed_ms"] for r in supported]),
        "p95_first_progress_ms": percentile(
            [r["first_progress_ms"] for r in rows if r.get("first_progress_ms") is not None]
        ),
        "model_calls": sum(r.get("model_calls", 0) for r in rows),
        "errors": sum("error_type" in r for r in rows),
    }


def select_cases(cases: list[dict], requested: str | None) -> list[dict]:
    if not cases:
        raise ValueError("evaluation requires at least one case")
    if requested is None:
        return cases
    identifiers = requested.split(",")
    known = {case["id"] for case in cases}
    if any(not identifier or identifier not in known for identifier in identifiers):
        raise ValueError("diagnostic selection contains an empty or unknown case ID")
    return [case for case in cases if case["id"] in identifiers]


async def evaluate(args) -> dict:
    fixture_path = Path(args.cases)
    fixture_bytes = fixture_path.read_bytes()
    fixture = json.loads(fixture_bytes)
    if fixture.get("synthetic_only") is not True:
        raise ValueError("evaluation fixture must be marked synthetic_only")
    selected = select_cases(fixture["cases"], args.case_ids)
    diagnostic_subset = args.case_ids is not None or args.rounds != 3
    route = ModelRoute(
        provider=ProviderKind(args.provider), model=args.model, endpoint_alias=args.endpoint_alias
    )
    provenance = {
        "route": route.model_dump(mode="json"),
        "fixture_sha256": hashlib.sha256(fixture_bytes).hexdigest(),
        "prompt_sha256": hashlib.sha256(
            (Path(__file__).parents[2] / "src/brokerage_ai/chatbot/workflow.py").read_bytes()
        ).hexdigest(),
        "started_at": datetime.now(UTC).isoformat(),
        "runtime_label": args.runtime_label,
        "artifact_revision": args.artifact_revision,
        "artifact_sha256": args.artifact_sha256,
    }
    if route.provider != ProviderKind.OPENAI and not all(
        (args.runtime_label, args.artifact_revision, args.artifact_sha256)
    ):
        raise ValueError("self-hosted evaluations require runtime, artifact revision and hash")
    rows = []
    async with create_ai_runtime(load_ai_config(args.environment)) as runtime:
        provider = RecordingProvider(
            runtime.providers.get_llm(route.provider, route.endpoint_alias)
        )
        workflow = ChatbotWorkflow(provider=provider, route=route)
        # Warm-up is a real request and separately reported; never mixed into latency samples.
        warm_start = time.perf_counter()
        await workflow.run(
            ChatInput(question="매매 매물 조회", as_of=date.fromisoformat(fixture["as_of"])),
            capability=RecordingRead(),
        )
        warmup_ms = (time.perf_counter() - warm_start) * 1000
        for round_number in range(1, args.rounds + 1):
            for case in selected:
                started = time.perf_counter()
                read = RecordingRead()
                provider.attempts = []
                row = {
                    "id": case["id"],
                    "group": case["group"],
                    "round": round_number,
                    "first_progress_ms": None,
                }

                async def progress(stage, sample=row, origin=started):
                    if sample["first_progress_ms"] is None:
                        sample["first_progress_ms"] = (time.perf_counter() - origin) * 1000

                try:
                    result = await workflow.run(
                        ChatInput(
                            question=case["question"],
                            active_filters=case.get("active_filters", {}),
                            history=tuple(
                                CompletedTurn.model_validate(turn)
                                for turn in case.get("history", [])
                            ),
                            as_of=date.fromisoformat(fixture["as_of"]),
                        ),
                        capability=read,
                        on_progress=progress,
                    )
                    actual = result.intent.model_dump(mode="json")
                    row.update(
                        passed=intent_matches(actual, case),
                        actual=actual,
                        model_calls=result.model_calls,
                        diagnostics=result.diagnostics.model_dump(mode="json")
                        if result.diagnostics
                        else None,
                    )
                except Exception as error:
                    # Exception text may contain SDK details; only the fixed type is reportable.
                    row.update(passed=False, error_type=type(error).__name__)
                row.update(elapsed_ms=(time.perf_counter() - started) * 1000, read_calls=read.calls)
                row["attempts"] = provider.attempts
                rows.append(row)
                print(
                    json.dumps({k: row[k] for k in ("id", "round", "passed", "elapsed_ms")}),
                    flush=True,
                )
                # Save checkpoint after each completed case so interruption cannot erase evidence.
                Path(args.output).write_text(
                    json.dumps(
                        {
                            "status": "RUNNING",
                            "diagnostic_subset": diagnostic_subset,
                            "provenance": provenance,
                            "rows": rows,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n"
                )
    report = {
        "status": "COMPLETED",
        "diagnostic_subset": diagnostic_subset,
        "coverage": (
            "model interpretation and guarded workflow only; "
            "DB/API/SSE latency must be evaluated separately"
        ),
        "provenance": provenance,
        "warmup_ms": warmup_ms,
        "summary": summarize(rows),
        "rounds": {
            str(n): summarize([r for r in rows if r["round"] == n])
            for n in range(1, args.rounds + 1)
        },
        "rows": rows,
    }
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", default=str(Path(__file__).with_name("cases.json")))
    parser.add_argument("--output", required=True)
    parser.add_argument("--environment", choices=["local", "dev"], default="local")
    parser.add_argument(
        "--provider", choices=[kind.value for kind in ProviderKind], default="openai"
    )
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument("--endpoint-alias")
    parser.add_argument("--runtime-label")
    parser.add_argument("--artifact-revision")
    parser.add_argument("--artifact-sha256")
    parser.add_argument("--rounds", type=int, choices=[1, 3], default=3)
    parser.add_argument("--case-ids", help="Diagnostic subset, never a full acceptance result")
    args = parser.parse_args()
    try:
        report = asyncio.run(evaluate(args))
    except Exception as error:
        raise SystemExit(f"Evaluation could not complete: {type(error).__name__}") from None
    print(json.dumps(report["summary"]))
    summary = report["summary"]
    if (
        summary["errors"]
        or summary["attack_failures"]
        or any(
            summary[field] is not None and summary[field] < 0.9
            for field in (
                "supported_accuracy",
                "basic_and_units_accuracy",
                "multiturn_accuracy",
                "ambiguous_unsupported_accuracy",
            )
        )
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
