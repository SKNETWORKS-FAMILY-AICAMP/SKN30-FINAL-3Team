"""Verify a manually reviewed summary against its exact raw report, without model calls."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from collections import Counter
from pathlib import Path

ARTIFACT_KIND = "chatbot_evaluation_reviewed_summary"
SCHEMA_VERSION = 1
VERIFIER_VERSION = "chatbot-summary-verifier:v1"

_SPEC = importlib.util.spec_from_file_location(
    "chatbot_summary_aggregation", Path(__file__).with_name("evaluate.py")
)
assert _SPEC and _SPEC.loader
_EVALUATION = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_EVALUATION)


def _counts(rows: list[dict]) -> dict:
    correct = sum(row["passed"] for row in rows)
    return {"correct": correct, "total": len(rows), "accuracy": correct / len(rows)}


def recompute_aggregates(rows: list[dict]) -> dict:
    """Reproduce numerical/failure evidence; human review notes are intentionally separate."""
    return {
        "summary": _EVALUATION.summarize(rows),
        "basic_and_units": _counts([r for r in rows if r["group"] in {"basic", "units"}]),
        "multiturn": _counts([r for r in rows if r["group"] == "multi"]),
        "ambiguity": _counts([r for r in rows if r["group"] == "ambiguous"]),
        "rounds": {
            str(n): {
                **_EVALUATION.summarize(selected := [r for r in rows if r["round"] == n]),
                "basic_and_units": _counts(
                    [r for r in selected if r["group"] in {"basic", "units"}]
                ),
                "multiturn": _counts([r for r in selected if r["group"] == "multi"]),
            }
            for n in (1, 2, 3)
        },
        "failures": [
            {
                "id": r["id"],
                "round": r["round"],
                "actual": r.get("actual"),
                "error_type": r.get("error_type"),
            }
            for r in rows
            if not r["passed"]
        ],
    }


def verify_summary(raw_bytes: bytes, summary: dict) -> dict:
    if (summary.get("artifact_kind"), summary.get("schema_version")) != (
        ARTIFACT_KIND,
        SCHEMA_VERSION,
    ):
        raise ValueError("unsupported reviewed-summary artifact schema")
    if summary.get("creation_method") != "manual_aggregation_and_review":
        raise ValueError("summary must identify its manual review step")
    if summary.get("verification_tool_version") != VERIFIER_VERSION:
        raise ValueError("unsupported summary verifier version")
    raw = json.loads(raw_bytes)
    if raw.get("status") != "COMPLETED" or summary.get("status") != "COMPLETED":
        raise ValueError("both artifacts must be completed")
    # The original 2026-09-08 raw format predates diagnostic_subset. Its full 80x3
    # matrix is checked below; current reviewed summaries must declare it explicitly.
    if raw.get("diagnostic_subset", False) or summary.get("diagnostic_subset") is not False:
        raise ValueError("diagnostic subsets cannot be full acceptance evidence")
    provenance = summary["provenance"]
    if hashlib.sha256(raw_bytes).hexdigest() != provenance["raw_report_sha256"]:
        raise ValueError("raw report SHA256 does not match")
    for field in ("route", "fixture_sha256", "started_at"):
        if raw["provenance"].get(field) != provenance.get(field):
            raise ValueError(f"provenance.{field} differs from the raw report")
    if raw["provenance"]["route"]["provider"] != "openai":
        _EVALUATION.validate_self_hosted_provenance(raw["provenance"])
        for field in (
            "runtime_label",
            "runtime_image",
            "deployment_image",
            "artifact_revision",
            "artifact_sha256",
            "model_profile",
            "profiles_sha256",
            "profile",
            "expected_weights_manifest_sha256",
            "endpoint_attestation",
            "final_endpoint_attestation",
        ):
            if raw["provenance"].get(field) != provenance.get(field):
                raise ValueError(f"provenance.{field} differs from the raw report")
    if raw["provenance"]["prompt_sha256"] != provenance["evaluated_workflow_sha256"]:
        raise ValueError("evaluated workflow hash differs from the raw report")
    if raw.get("warmup_ms") != summary.get("warmup_ms"):
        raise ValueError("warm-up evidence differs from the raw report")
    rows = raw["rows"]
    groups = {"basic": 30, "units": 10, "multi": 10, "ambiguous": 10, "attack": 20}
    if len(rows) != 240 or len({(r["id"], r["round"]) for r in rows}) != 240:
        raise ValueError("expected 240 distinct case/round observations")
    for n in (1, 2, 3):
        if Counter(r["group"] for r in rows if r["round"] == n) != groups:
            raise ValueError("every round must contain the full agreed case groups")
    if not all(type(row["passed"]) is bool for row in rows):
        raise ValueError("case verdicts must be booleans")
    recomputed = recompute_aggregates(rows)
    for field, expected in recomputed.items():
        if summary.get(field) != expected:
            raise ValueError(f"summary field {field} differs from recomputed raw evidence")
    return {"verified": True, "verifier_version": VERIFIER_VERSION, "cases": len(rows)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = verify_summary(args.raw.read_bytes(), json.loads(args.summary.read_bytes()))
    except (KeyError, TypeError, ValueError, OSError) as error:
        # Report only our fixed field-level messages, never raw report content or SDK data.
        detail = str(error) if type(error) is ValueError else type(error).__name__
        raise SystemExit(f"Summary verification failed: {detail}") from None
    print(json.dumps(result))


if __name__ == "__main__":
    main()
