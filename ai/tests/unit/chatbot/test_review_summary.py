"""Offline review replay preserves raw evidence and rejects altered or unsafe artifacts."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest

from brokerage_ai.chatbot import ChatIntent

ROOT = Path(__file__).parents[3]
SPEC = importlib.util.spec_from_file_location(
    "chatbot_review_summary", ROOT / "eval/chatbot/review_summary.py"
)
assert SPEC and SPEC.loader
REVIEW = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REVIEW)


@pytest.fixture
def raw_report():
    fixture_bytes = (ROOT / "eval/chatbot/cases.json").read_bytes()
    fixture = json.loads(fixture_bytes)
    rows = [
        {
            "id": case["id"],
            "group": case["group"],
            "round": n,
            "passed": True,
            "actual": ChatIntent.model_validate(case["expected"]).model_dump(mode="json"),
            "attempts": [],
            "elapsed_ms": 1,
            "first_progress_ms": 0.1,
            "model_calls": 0,
            "read_calls": 0,
        }
        for n in (1, 2, 3)
        for case in fixture["cases"]
    ]
    return {
        "status": "COMPLETED",
        "diagnostic_subset": False,
        "rows": rows,
        "warmup_ms": 10,
        "provenance": {
            "route": {"provider": "openai", "model": "synthetic-model", "endpoint_alias": None},
            "fixture_sha256": hashlib.sha256(fixture_bytes).hexdigest(),
            "prompt_sha256": "a" * 64,
            "started_at": "2026-09-08T00:00:00+00:00",
        },
    }


def encoded(report):
    return json.dumps(report).encode()


def self_hosted(report):
    report = deepcopy(report)
    profile = {
        "model": "synthetic/model",
        "revision": "a" * 40,
        "runtime_image": "vllm/vllm-openai@sha256:" + "b" * 64,
        "runtime_version": "0.28.0",
        "quantization": "fp8",
        "load_format": "auto",
        "max_model_len": 8192,
        "max_num_seqs": 1,
        "gpu_memory_utilization": 0.85,
        "weights": [{"name": "model.safetensors", "size": 100, "sha256": "c" * 64}],
    }
    artifact = hashlib.sha256(
        json.dumps(profile["weights"], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    metadata = {
        "model": profile["model"],
        "revision": profile["revision"],
        "runtime_image": profile["runtime_image"],
        "runtime_version": profile["runtime_version"],
        "artifact_sha256": artifact,
        "profile": "synthetic-fp8",
        "checked_at": "2026-09-08T00:01:00+00:00",
    }
    report["provenance"].update(
        route={"provider": "vllm", "model": profile["model"], "endpoint_alias": "general-dev-gpu"},
        profile=profile,
        model_profile="synthetic-fp8",
        profiles_sha256="d" * 64,
        runtime_label=profile["runtime_version"],
        runtime_image=profile["runtime_image"],
        deployment_image="ghcr.io/example/general-serving@sha256:" + "e" * 64,
        artifact_revision=profile["revision"],
        artifact_sha256=artifact,
        expected_weights_manifest_sha256=artifact,
        endpoint_attestation=metadata,
        final_endpoint_attestation=deepcopy(metadata),
    )
    return report


def test_replay_creates_new_summary_and_verifies_existing_without_copying_manual_notes(
    raw_report, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    raw_path = tmp_path / "raw.json"
    raw_bytes = encoded(raw_report)
    raw_path.write_bytes(raw_bytes)
    existing, _ = REVIEW.prepare(raw_bytes)
    existing["review_notes"]["manual_cause_analysis"] = "Separately reviewed interpretation."
    prior_path = tmp_path / "existing.json"
    prior_path.write_text(json.dumps(existing))
    prior_bytes = prior_path.read_bytes()
    output = tmp_path / "new/summary.json"
    result = REVIEW.create_summary(raw_path, output, reviewed=True, verify_against=prior_path)
    regenerated = json.loads(output.read_bytes())
    assert result["existing_summary_verified"]
    assert regenerated["provenance"]["raw_report_sha256"] == hashlib.sha256(raw_bytes).hexdigest()
    assert regenerated["summary"] == existing["summary"]
    assert "manual_cause_analysis" not in regenerated["review_notes"]
    assert raw_path.read_bytes() == raw_bytes
    assert prior_path.read_bytes() == prior_bytes
    second_output = tmp_path / "second.json"
    REVIEW.create_summary(raw_path, second_output, reviewed=True, verify_against=prior_path)
    assert second_output.read_bytes() == output.read_bytes()


@pytest.mark.parametrize(
    "mutation",
    [
        "running",
        "diagnostic",
        "truncated",
        "duplicate",
        "unknown_id",
        "wrong_group",
        "wrong_verdict",
        "wrong_fixture",
    ],
)
def test_incomplete_or_altered_case_matrix_cannot_be_published(raw_report, mutation):
    if mutation == "running":
        raw_report["status"] = "RUNNING"
    elif mutation == "diagnostic":
        raw_report["diagnostic_subset"] = True
    elif mutation == "truncated":
        raw_report["rows"].pop()
    elif mutation == "duplicate":
        raw_report["rows"][1] = deepcopy(raw_report["rows"][0])
    elif mutation == "unknown_id":
        raw_report["rows"][0]["id"] = "unagreed-01"
    elif mutation == "wrong_group":
        raw_report["rows"][0]["group"] = "multi"
    elif mutation == "wrong_verdict":
        raw_report["rows"][0]["passed"] = False
    else:
        raw_report["provenance"]["fixture_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        REVIEW.prepare(encoded(raw_report))


@pytest.mark.parametrize("location", ["actual", "attempts"])
def test_unexpected_output_fields_are_rejected(raw_report, location):
    value = {"tool": "properties", "extra_field": "unexpected"}
    row = {"actual": value} if location == "actual" else {"attempts": [value]}
    with pytest.raises(ValueError):
        REVIEW.validate_outputs([row])


@pytest.mark.parametrize(
    "value",
    [
        "https://synthetic.invalid",
        "synthetic@example.invalid",
        "010-1234-5678",
        "SELECT * FROM synthetic",
        "Bearer synthetic-test-token",
    ],
)
def test_potentially_sensitive_structured_text_requires_manual_review(value):
    with pytest.raises(ValueError, match="sensitive-text review"):
        REVIEW.validate_outputs(
            [{"actual": {"tool": "properties", "filters": {"complex_name": value}}}]
        )


def test_profile_and_before_after_attestations_are_replayed_from_the_recorded_snapshot(raw_report):
    raw = self_hosted(raw_report)
    summary, result = REVIEW.prepare(encoded(raw))
    assert result["verified"]
    assert summary["provenance"]["profile"]["quantization"] == "fp8"


@pytest.mark.parametrize(
    "location", ["route", "profile", "weight", "attestation", "changed_runtime", "weight_hash"]
)
def test_unknown_metadata_and_deployment_mismatches_are_rejected(raw_report, location):
    raw = self_hosted(raw_report)
    p = raw["provenance"]
    if location == "route":
        p["route"]["base_url"] = "https://synthetic.invalid"
    elif location == "profile":
        p["profile"]["endpoint_url"] = "https://synthetic.invalid"
    elif location == "weight":
        p["profile"]["weights"][0]["source_url"] = "https://synthetic.invalid"
    elif location == "attestation":
        p["endpoint_attestation"]["api_key"] = "synthetic-key"
    elif location == "changed_runtime":
        p["final_endpoint_attestation"]["runtime_version"] = "changed"
    else:
        p["profile"]["weights"][0]["sha256"] = "0" * 64
    with pytest.raises(ValueError):
        REVIEW.prepare(encoded(raw))


def test_review_acknowledgement_and_existing_file_protection(raw_report, tmp_path):
    raw_path = tmp_path / "raw.json"
    raw_bytes = encoded(raw_report)
    raw_path.write_bytes(raw_bytes)
    output = tmp_path / "summary.json"
    with pytest.raises(ValueError, match="review"):
        REVIEW.create_summary(raw_path, output, reviewed=False)
    assert not output.exists()
    with pytest.raises(ValueError, match="new file"):
        REVIEW.create_summary(raw_path, raw_path, reviewed=True)
    output.write_text("preserved")
    with pytest.raises(ValueError, match="new file"):
        REVIEW.create_summary(raw_path, output, reviewed=True)
    assert raw_path.read_bytes() == raw_bytes
    assert output.read_text() == "preserved"


def test_altered_existing_summary_prevents_new_output(raw_report, tmp_path):
    raw_path = tmp_path / "raw.json"
    raw_path.write_bytes(encoded(raw_report))
    summary, _ = REVIEW.prepare(raw_path.read_bytes())
    summary["summary"]["supported_accuracy"] = 0.25
    existing = tmp_path / "existing.json"
    existing.write_text(json.dumps(summary))
    output = tmp_path / "new.json"
    with pytest.raises(ValueError, match="recomputed"):
        REVIEW.create_summary(raw_path, output, reviewed=True, verify_against=existing)
    assert not output.exists()


def test_cli_failure_never_prints_malformed_report_contents(tmp_path, capsys):
    raw_path = tmp_path / "raw.json"
    raw_path.write_text("sensitive synthetic endpoint details")
    with pytest.raises(SystemExit) as error:
        REVIEW.main(["--raw", str(raw_path), "--output", str(tmp_path / "new.json"), "--reviewed"])
    assert "sensitive" not in str(error.value)
    assert "sensitive" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "version", [None, REVIEW.LEGACY_SCORER_VERSION, REVIEW.CURRENT_SCORER_VERSION]
)
def test_review_replays_the_recorded_sort_rule_without_changing_raw(raw_report, version):
    if version is not None:
        raw_report["provenance"]["scorer_version"] = version
    target = next(row for row in raw_report["rows"] if row["id"] == "basic-01")
    target["actual"]["filters"]["sort"] = "recent"
    target["passed"] = version != REVIEW.CURRENT_SCORER_VERSION
    before = encoded(raw_report)
    summary, result = REVIEW.prepare(before)
    assert result["verified"]
    assert summary["summary"]["supported_accuracy"] == (
        149 / 150 if version == REVIEW.CURRENT_SCORER_VERSION else 1
    )
    assert encoded(raw_report) == before
    assert summary["provenance"].get("scorer_version") == version


@pytest.mark.parametrize("version", [None, "", "chatbot-intent-scorer:v99"])
def test_review_rejects_unknown_explicit_scorer_even_without_actual_outputs(raw_report, version):
    raw_report["provenance"]["scorer_version"] = version
    for row in raw_report["rows"]:
        row["actual"] = None
        row["passed"] = False
    with pytest.raises(ValueError, match="unsupported recorded scorer"):
        REVIEW.prepare(encoded(raw_report))


@pytest.mark.parametrize("active", [{}, {"sort": "price_desc"}])
def test_legacy_sort_replay_preserves_explicit_recent_blind_spot_and_does_not_mutate(active):
    case = {
        "active_filters": active,
        "expected": {"tool": "properties", "mode": "refine", "filters": {"sort": "recent"}},
    }
    actual = {"tool": "properties", "mode": "refine", "filters": {}}
    original = deepcopy((actual, case))
    assert REVIEW.recorded_intent_matches(actual, case, REVIEW.LEGACY_SCORER_VERSION)
    assert not REVIEW.recorded_intent_matches(actual, case, REVIEW.CURRENT_SCORER_VERSION)
    assert (actual, case) == original


def test_summary_verifier_binds_recorded_scorer_metadata(raw_report):
    raw_report["provenance"]["scorer_version"] = REVIEW.CURRENT_SCORER_VERSION
    raw_bytes = encoded(raw_report)
    summary, _ = REVIEW.prepare(raw_bytes)
    summary["provenance"]["scorer_version"] = REVIEW.LEGACY_SCORER_VERSION
    with pytest.raises(ValueError, match="scorer_version"):
        REVIEW.verifier.verify_summary(raw_bytes, summary)
