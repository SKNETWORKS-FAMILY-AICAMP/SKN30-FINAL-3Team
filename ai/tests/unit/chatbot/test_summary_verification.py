from __future__ import annotations

import hashlib
import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[3]
SPEC = importlib.util.spec_from_file_location(
    "chatbot_summary_verifier", ROOT / "eval/chatbot/verify_summary.py"
)
assert SPEC and SPEC.loader
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


def artifacts():
    rows = [
        {
            "id": f"{group}-{i}",
            "round": n,
            "group": group,
            "passed": True,
            "elapsed_ms": i + 1,
            "first_progress_ms": 0.1,
            "model_calls": 1,
            "read_calls": 0 if group == "attack" else 1,
        }
        for n in (1, 2, 3)
        for group, count in {
            "basic": 30,
            "units": 10,
            "multi": 10,
            "ambiguous": 10,
            "attack": 20,
        }.items()
        for i in range(count)
    ]
    raw = {
        "status": "COMPLETED",
        "warmup_ms": 10,
        "rows": rows,
        "provenance": {
            "route": {"provider": "openai", "model": "fake"},
            "fixture_sha256": "fixture",
            "started_at": "2026-09-08",
            "prompt_sha256": "workflow",
        },
    }
    raw_bytes = json.dumps(raw).encode()
    summary = {
        "artifact_kind": VERIFY.ARTIFACT_KIND,
        "schema_version": VERIFY.SCHEMA_VERSION,
        "creation_method": "manual_aggregation_and_review",
        "verification_tool_version": VERIFY.VERIFIER_VERSION,
        "status": "COMPLETED",
        "diagnostic_subset": False,
        "warmup_ms": 10,
        "provenance": {
            **raw["provenance"],
            "raw_report_sha256": hashlib.sha256(raw_bytes).hexdigest(),
            "evaluated_workflow_sha256": "workflow",
        },
        **VERIFY.recompute_aggregates(rows),
    }
    return raw_bytes, summary


def test_manual_summary_is_reproduced_from_raw_rows_without_model_or_database():
    raw, summary = artifacts()
    assert VERIFY.verify_summary(raw, summary)["cases"] == 240


@pytest.mark.parametrize("field", ["summary", "rounds", "failures", "basic_and_units"])
def test_altered_aggregates_or_failure_evidence_are_rejected(field):
    raw, summary = artifacts()
    summary[field] = {}
    with pytest.raises(ValueError, match="recomputed"):
        VERIFY.verify_summary(raw, summary)


def test_raw_bytes_are_bound_even_when_json_values_are_unchanged():
    raw, summary = artifacts()
    with pytest.raises(ValueError, match="SHA256"):
        VERIFY.verify_summary(raw + b"\n", summary)


def test_duplicate_observation_cannot_replace_a_missing_case():
    raw, summary = artifacts()
    changed = json.loads(raw)
    changed["rows"][1] = deepcopy(changed["rows"][0])
    changed_bytes = json.dumps(changed).encode()
    summary["provenance"]["raw_report_sha256"] = hashlib.sha256(changed_bytes).hexdigest()
    with pytest.raises(ValueError, match="distinct"):
        VERIFY.verify_summary(changed_bytes, summary)


def test_raw_cli_output_cannot_be_misidentified_as_reviewed_summary():
    raw, _ = artifacts()
    with pytest.raises(ValueError, match="artifact schema"):
        VERIFY.verify_summary(raw, json.loads(raw))
