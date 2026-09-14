"""Build and verify a reviewed Qwen summary from a completed immutable raw report.

Run with the AI Python environment. This does not run models or change a raw report.
The caller must review the raw synthetic outputs before supplying --reviewed.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
from copy import deepcopy
from pathlib import Path

from brokerage_ai.chatbot import ChatIntent

REPO = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "qwen_summary_verifier", REPO / "ai/eval/chatbot/verify_summary.py"
)
assert spec and spec.loader
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)

PROVENANCE_FIELDS = {
    "scorer_version",
    "route",
    "fixture_sha256",
    "started_at",
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
}
PROFILE_FIELDS = {
    "model",
    "revision",
    "runtime_image",
    "runtime_version",
    "quantization",
    "load_format",
    "max_model_len",
    "max_num_seqs",
    "gpu_memory_utilization",
    "weights",
}
ATTESTATION_FIELDS = {
    "model",
    "revision",
    "artifact_sha256",
    "runtime_version",
    "runtime_image",
    "profile",
    "checked_at",
}
SENSITIVE = re.compile(
    r"https?://|\bBearer\s|\bsk-[A-Za-z0-9_-]{12,}|\bAKIA[A-Z0-9]{16}\b|"
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|"
    r"(?<!\d)01[016789][- ]?\d{3,4}[- ]?\d{4}(?!\d)|"
    r"\b(?:select|insert|update|delete|drop|alter|create)\b",
    re.IGNORECASE,
)


def validate_outputs(rows):
    count = 0
    for row in rows:
        values = list(row.get("attempts", []))
        if row.get("actual") is not None:
            values.append(row["actual"])
        for value in values:
            parsed = ChatIntent.model_validate(value)
            for field, text in parsed.filters.model_dump().items():
                if isinstance(text, str) and SENSITIVE.search(text):
                    raise ValueError(f"output requires sensitive-text review in filter {field}")
            count += 1
        if row.get("error_type") is not None and not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*", row["error_type"]
        ):
            raise ValueError("error_type must contain an exception class name only")
    return count


def validate_deployment_metadata(provenance: dict) -> None:
    """Recheck the recorded deployment snapshot without querying a live endpoint."""
    route = provenance["route"]
    if route["provider"] == "openai":
        return
    verifier._EVALUATION.validate_self_hosted_provenance(provenance)
    profile = provenance["profile"]
    if set(profile) != PROFILE_FIELDS:
        raise ValueError("incomplete or unexpected serving profile fields")
    if not profile["weights"]:
        raise ValueError("profile must include a pinned weight manifest")
    for weight in profile["weights"]:
        if (
            Path(weight["name"]).name != weight["name"]
            or not re.fullmatch(r"[A-Za-z0-9_.-]+", weight["name"])
            or not re.fullmatch(r"[0-9a-f]{64}", weight["sha256"])
            or type(weight["size"]) is not int
            or weight["size"] <= 0
        ):
            raise ValueError("invalid weight manifest entry")
    expected_hash = hashlib.sha256(
        json.dumps(profile["weights"], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if expected_hash != provenance["artifact_sha256"]:
        raise ValueError("profile weight manifest differs from attested artifact hash")
    for field, value in (
        ("model", route["model"]),
        ("revision", provenance["artifact_revision"]),
        ("runtime_image", provenance["runtime_image"]),
        ("runtime_version", provenance["runtime_label"]),
    ):
        if profile[field] != value:
            raise ValueError("profile differs from the recorded evaluation route")
    expected = {
        "model": route["model"],
        "revision": provenance["artifact_revision"],
        "runtime_image": provenance["runtime_image"],
        "runtime_version": provenance["runtime_label"],
        "artifact_sha256": provenance["artifact_sha256"],
        "profile": provenance["model_profile"],
    }
    for key in ("endpoint_attestation", "final_endpoint_attestation"):
        metadata = provenance[key]
        if set(metadata) != ATTESTATION_FIELDS:
            raise ValueError("incomplete or unexpected endpoint metadata")
        if any(metadata.get(field) != value for field, value in expected.items()):
            raise ValueError("endpoint metadata differs from the pinned deployment snapshot")


LEGACY_SCORER_VERSION = "chatbot-intent-scorer:v1"
CURRENT_SCORER_VERSION = "chatbot-intent-scorer:v2"


def recorded_intent_matches(actual: dict, case: dict, version: str) -> bool:
    """Replay the recorded rule, including v1's historical recent-sort blind spot.

    The original reports did not record a scorer version; callers map that original
    format to v1. Never silently regrade those reports using the corrected v2 rule.
    """
    if version not in {LEGACY_SCORER_VERSION, CURRENT_SCORER_VERSION}:
        raise ValueError("unsupported recorded scorer version")
    if verifier._EVALUATION.SCORER_VERSION != CURRENT_SCORER_VERSION:
        raise ValueError("review replay requires an explicit scorer compatibility update")
    if version == LEGACY_SCORER_VERSION:
        actual = deepcopy(actual)
        case = deepcopy(case)
        # v1 stripped recent after whitespace normalization from all three inputs,
        # before active conditions and refinements were merged. Preserve that bug.
        for filters in (
            actual.get("filters", {}),
            case["expected"].get("filters", {}),
            case.get("active_filters", {}),
        ):
            value = filters.get("sort")
            if isinstance(value, str) and "".join(value.split()) == "recent":
                filters.pop("sort")
    return verifier._EVALUATION.intent_matches(actual, case)


def prepare(raw_bytes):
    raw = json.loads(raw_bytes)
    if raw.get("status") != "COMPLETED" or raw.get("diagnostic_subset") is not False:
        raise ValueError("only completed full-matrix reports can become a reviewed summary")
    fixture_bytes = (REPO / "ai/eval/chatbot/cases.json").read_bytes()
    fixture = json.loads(fixture_bytes)
    if fixture.get("synthetic_only") is not True:
        raise ValueError("fixture is not marked synthetic")
    if raw["provenance"]["fixture_sha256"] != hashlib.sha256(fixture_bytes).hexdigest():
        raise ValueError("raw fixture does not match the checked-in synthetic fixture")
    scorer_version = raw["provenance"].get("scorer_version", LEGACY_SCORER_VERSION)
    if scorer_version not in {LEGACY_SCORER_VERSION, CURRENT_SCORER_VERSION}:
        raise ValueError("unsupported recorded scorer version")
    expected = {case["id"]: case for case in fixture["cases"]}
    if {(r["id"], r["round"]) for r in raw["rows"]} != {
        (key, n) for key in expected for n in (1, 2, 3)
    }:
        raise ValueError("raw case identifiers do not match the agreed fixture and repeats")
    for row in raw["rows"]:
        case = expected[row["id"]]
        if row["group"] != case["group"]:
            raise ValueError("case group differs from fixture")
        score = (
            recorded_intent_matches(row["actual"], case, scorer_version)
            if row.get("actual") is not None
            else False
        )
        if row["passed"] is not score:
            raise ValueError("stored verdict differs from the recorded scorer")
    checked_outputs = validate_outputs(raw["rows"])
    provenance = {
        key: raw["provenance"][key] for key in PROVENANCE_FIELDS if key in raw["provenance"]
    }
    if set(provenance["route"]) - {"provider", "model", "endpoint_alias"}:
        raise ValueError("unexpected route metadata fields")
    if set(provenance.get("profile", {})) - PROFILE_FIELDS:
        raise ValueError("unexpected serving profile fields require review")
    for weight in provenance.get("profile", {}).get("weights", []):
        if set(weight) != {"name", "size", "sha256"}:
            raise ValueError("unexpected weight metadata fields")
    for key in ("endpoint_attestation", "final_endpoint_attestation"):
        if set(provenance.get(key, {})) - ATTESTATION_FIELDS:
            raise ValueError("unexpected endpoint metadata fields require review")
    validate_deployment_metadata(provenance)
    provenance.update(
        raw_report_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        evaluated_workflow_sha256=raw["provenance"]["prompt_sha256"],
    )
    summary = {
        "artifact_kind": verifier.ARTIFACT_KIND,
        "schema_version": verifier.SCHEMA_VERSION,
        "creation_method": "manual_aggregation_and_review",
        "verification_tool_version": verifier.VERIFIER_VERSION,
        "status": "COMPLETED",
        "diagnostic_subset": False,
        "warmup_ms": raw["warmup_ms"],
        "provenance": provenance,
        **verifier.recompute_aggregates(raw["rows"]),
        "review_notes": {
            "scope": (
                "synthetic model interpretation and guarded workflow; "
                "not DB/API/SSE or F3 judgment quality"
            ),
            "outputs_checked_against_chat_intent_schema": checked_outputs,
            "sensitive_output_scan": (
                "no flagged patterns; automated scan supplements caller review"
            ),
            "attack_scope": "pre-model application guard; not intrinsic model attack resistance",
            "deployment_identity": (
                "operator must compare wrapper digest with RunPod API; "
                "endpoint metadata alone is not container identity proof"
            ),
        },
    }
    verification = verifier.verify_summary(raw_bytes, summary)
    return summary, verification


def create_summary(
    raw_path: Path, output_path: Path, *, reviewed: bool, verify_against: Path | None = None
) -> dict:
    """Create a new artifact; the exact raw bytes and every existing file stay unchanged."""
    if not reviewed:
        raise ValueError("review the completed raw synthetic outputs before passing --reviewed")
    if raw_path.resolve() == output_path.resolve() or output_path.exists():
        raise ValueError("output must be a new file distinct from the immutable raw report")
    raw_bytes = raw_path.read_bytes()
    summary, verification = prepare(raw_bytes)
    if verify_against is not None:
        # Manual interpretation notes remain separate; both numerical artifacts bind these bytes.
        verifier.verify_summary(raw_bytes, json.loads(verify_against.read_bytes()))
        verification["existing_summary_verified"] = True
    serialized = json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x") as output:
        output.write(serialized)
    return verification


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reviewed", action="store_true")
    parser.add_argument(
        "--verify-against",
        type=Path,
        help="Also verify an existing reviewed summary against the same immutable raw bytes",
    )
    args = parser.parse_args(argv)
    try:
        verification = create_summary(
            args.raw, args.output, reviewed=args.reviewed, verify_against=args.verify_against
        )
    except Exception as error:
        # Neither provider text nor data-validation error bodies are printed.
        raise SystemExit(
            f"Summary creation refused: {type(error).__name__}; inspect local evidence."
        ) from None
    print(json.dumps({"output": str(args.output), **verification}))


if __name__ == "__main__":
    main()
