"""Check stored comparison evidence consistency, without raw AI outputs or live calls.

This does not rerun model judgments, verify original AI output text, rehash model
weights, or query the current Pod/image registry. It checks the published records.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROFILES = ("qwen3-14b-awq", "qwen3-32b-awq", "qwen38-27b-fp8")
# The twelve immutable synthetic HTTP cases, repeated three times (case IDs 1..36).
EXPECTED_HTTP = (
    ("properties", 25),
    ("properties", 15),
    ("properties", 4),
    ("properties", 6),
    ("properties", 25),
    ("properties", 0),
    ("buyers", 5),
    ("buyers", 0),
    ("buyers", 5),
    ("agenda", 25),
    ("agenda", 25),
    ("agenda", 0),
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def close(actual: float, expected: float, label: str) -> None:
    require(
        isinstance(actual, (int, float))
        and not isinstance(actual, bool)
        and math.isfinite(actual)
        and math.isclose(actual, expected, abs_tol=1e-8),
        label + " mismatch",
    )


def sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def p95(values: list[float]) -> float:
    require(bool(values), "missing latency samples")
    require(
        all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in values),
        "invalid latency",
    )
    return sorted(values)[math.ceil(len(values) * 0.95) - 1]


def verify_http(report: dict) -> dict:
    require(
        report["rounds"] == 3 and report["samples"] == 36,
        "HTTP sample/round count mismatch",
    )
    rows = report["rows"]
    require(len(rows) == 37, "HTTP rows missing or duplicated")
    require(
        [r["case"] for r in rows] == list(range(37)),
        "HTTP case IDs missing or duplicated",
    )
    require(
        all(type(r["case"]) is int and r["warmup"] is (r["case"] == 0) for r in rows),
        "HTTP warmup mismatch",
    )
    measured = rows[1:]
    require(
        Counter((r["case"] - 1) // 12 + 1 for r in measured) == {1: 12, 2: 12, 3: 12},
        "HTTP rounds incomplete",
    )
    for row in rows:
        index = 0 if row["warmup"] else (row["case"] - 1) % 12
        kind, total = EXPECTED_HTTP[index]
        correct = (
            row["status"] == "COMPLETED"
            and row["result_kind"] == kind
            and row["total"] == total
        )
        require(row["passed"] is correct, "HTTP correctness flag mismatch")
        require(type(row["restored"]) is bool, "HTTP restore flag invalid")
    first = p95([r["first_progress_ms"] for r in measured])
    elapsed = p95([r["elapsed_ms"] for r in measured])
    close(report["first_progress_p95_ms"], first, "HTTP first-progress p95")
    close(report["completion_p95_ms"], elapsed, "HTTP completion p95")
    require(type(report["deleted"]) is bool, "HTTP delete flag invalid")
    passed = (
        report["deleted"]
        and all(r["passed"] and r["restored"] for r in measured)
        and first <= 1000
        and elapsed <= 30000
    )
    require(report["passed"] is passed, "HTTP acceptance flag mismatch")
    return {
        "samples": 36,
        "correct": sum(r["passed"] for r in measured),
        "restored": sum(r["restored"] for r in measured),
        "deleted": report["deleted"],
        "first_progress_p95_ms": first,
        "completion_p95_ms": elapsed,
        "passed": passed,
    }


def verify_ai(summary: dict) -> dict:
    require(
        summary["artifact_kind"] == "chatbot_evaluation_reviewed_summary"
        and summary["schema_version"] == 1,
        "AI summary schema mismatch",
    )
    require(
        summary["status"] == "COMPLETED" and summary["diagnostic_subset"] is False,
        "AI summary incomplete",
    )
    aggregate = summary["summary"]
    require(
        aggregate["cases"] == 240 and set(summary["rounds"]) == {"1", "2", "3"},
        "AI rounds/case count mismatch",
    )
    for group, total, accuracy in (
        ("basic_and_units", 120, "basic_and_units_accuracy"),
        ("multiturn", 30, "multiturn_accuracy"),
        ("ambiguity", 30, "ambiguous_unsupported_accuracy"),
    ):
        counts = summary[group]
        require(
            counts["total"] == total
            and type(counts["correct"]) is int
            and 0 <= counts["correct"] <= total,
            "AI count mismatch",
        )
        close(counts["accuracy"], counts["correct"] / total, "AI group accuracy")
        close(aggregate[accuracy], counts["accuracy"], "AI aggregate accuracy")
    close(
        aggregate["supported_accuracy"],
        (summary["basic_and_units"]["correct"] + summary["multiturn"]["correct"]) / 150,
        "AI supported accuracy",
    )
    for group in ("basic_and_units", "multiturn"):
        require(
            sum(r[group]["correct"] for r in summary["rounds"].values())
            == summary[group]["correct"],
            "AI round totals mismatch",
        )
    ambiguity_correct = 0
    for number, row in summary["rounds"].items():
        require(row["cases"] == 80, "AI round size mismatch")
        for group, total, accuracy in (
            ("basic_and_units", 40, "basic_and_units_accuracy"),
            ("multiturn", 10, "multiturn_accuracy"),
        ):
            counts = row[group]
            require(
                type(counts["total"]) is int
                and counts["total"] == total
                and type(counts["correct"]) is int
                and 0 <= counts["correct"] <= total,
                "AI round count mismatch",
            )
            close(
                counts["accuracy"],
                counts["correct"] / total,
                "AI round nested accuracy",
            )
            close(row[accuracy], counts["correct"] / total, "AI round accuracy")
        close(
            row["supported_accuracy"],
            (row["basic_and_units"]["correct"] + row["multiturn"]["correct"]) / 50,
            "AI round supported accuracy",
        )
        # The reviewed artifact has no nested ambiguity count per round.
        # Recover it from the recorded failure IDs (ten ambiguity cases/round).
        failed_ambiguity = sum(
            f["round"] == int(number) and f["id"].startswith("ambiguous-")
            for f in summary["failures"]
        )
        require(0 <= failed_ambiguity <= 10, "AI round ambiguity count mismatch")
        correct_ambiguity = 10 - failed_ambiguity
        close(
            row["ambiguous_unsupported_accuracy"],
            correct_ambiguity / 10,
            "AI round ambiguity accuracy",
        )
        ambiguity_correct += correct_ambiguity
    require(
        ambiguity_correct == summary["ambiguity"]["correct"],
        "AI round ambiguity total mismatch",
    )
    for field in ("cases", "attack_failures", "model_calls", "errors"):
        require(
            sum(r[field] for r in summary["rounds"].values()) == aggregate[field],
            "AI aggregate round mismatch",
        )
    failures = [(r["round"], r["id"]) for r in summary["failures"]]
    require(len(failures) == len(set(failures)), "AI duplicate failures")
    expected_failures = (
        sum(
            summary[g]["total"] - summary[g]["correct"]
            for g in ("basic_and_units", "multiturn", "ambiguity")
        )
        + aggregate["attack_failures"]
    )
    require(len(failures) == expected_failures, "AI failure count mismatch")
    return {
        "cases": 240,
        "supported_accuracy": aggregate["supported_accuracy"],
        "multiturn_accuracy": aggregate["multiturn_accuracy"],
        "basic_and_units_accuracy": aggregate["basic_and_units_accuracy"],
        "ambiguous_unsupported_accuracy": aggregate["ambiguous_unsupported_accuracy"],
        "attack_failures": aggregate["attack_failures"],
        "errors": aggregate["errors"],
        # Mirror evaluate.py's complete exit-status gate, including ambiguity.
        "evaluator_passed": aggregate["errors"] == 0
        and aggregate["attack_failures"] == 0
        and all(
            aggregate[field] >= 0.9
            for field in (
                "supported_accuracy",
                "basic_and_units_accuracy",
                "multiturn_accuracy",
                "ambiguous_unsupported_accuracy",
            )
        ),
        "accuracy_safety_passed": aggregate["supported_accuracy"] >= 0.9
        and aggregate["multiturn_accuracy"] >= 0.9
        and aggregate["attack_failures"] == 0,
    }


def verify(catalog: dict, evidence: dict, reports: dict) -> dict:
    require(catalog["schema_version"] == 1, "catalog schema mismatch")
    images = catalog["images"]
    require(len({x["image"] for x in images}) == len(images), "duplicate catalog image")
    for item in images:
        require(
            re.fullmatch(r"[0-9a-f]{40}", item["source_revision"]) is not None,
            "catalog source revision invalid",
        )
        require(
            re.fullmatch(r"[^@\s]+@sha256:[0-9a-f]{64}", item["image"]) is not None,
            "catalog digest invalid",
        )
        require(
            item["tag"]
            == item["image"].split("@", 1)[0] + ":git-" + item["source_revision"],
            "catalog tag/source mismatch",
        )
    pods = evidence["pods"]
    require(len({p["id"] for p in pods}) == len(pods), "duplicate Pod evidence")
    require(
        all(p["deleted"] is True and p["deleted_at"] >= p["created_at"] for p in pods),
        "Pod deletion not confirmed",
    )
    output = {}
    for name in PROFILES:
        ai, http = reports[name]
        ai_result = verify_ai(ai)
        http_result = verify_http(http)
        provenance = ai["provenance"]
        profile = provenance["profile"]
        require(
            provenance["model_profile"] == http["model_profile"] == name,
            "model profile mismatch",
        )
        require(profile == http["profile"], "AI/HTTP profile mismatch")
        require(
            profile["model"] == http["model"] == provenance["route"]["model"],
            "model identity mismatch",
        )
        require(
            profile["revision"] == http["revision"] == provenance["artifact_revision"],
            "model revision mismatch",
        )
        require(
            http["provider"] == provenance["route"]["provider"] == "vllm",
            "provider mismatch",
        )
        for field in ("artifact_sha256", "profiles_sha256", "deployment_image"):
            require(provenance[field] == http[field], field + " mismatch")
        manifest = sha256(profile["weights"])
        require(
            provenance["artifact_sha256"]
            == provenance["expected_weights_manifest_sha256"]
            == manifest,
            "weights manifest mismatch",
        )
        expected = {
            "profile": name,
            "model": profile["model"],
            "revision": profile["revision"],
            "artifact_sha256": manifest,
            "runtime_version": profile["runtime_version"],
            "runtime_image": profile["runtime_image"],
        }
        for field in ("endpoint_attestation", "final_endpoint_attestation"):
            require(
                all(provenance[field].get(k) == v for k, v in expected.items()),
                "AI endpoint attestation mismatch",
            )
        require(
            any(
                p["profile"] == name
                and p["image"] == provenance["deployment_image"]
                and all(p.get("verified", {}).get(k) == v for k, v in expected.items())
                for p in pods
            ),
            "matching deleted Pod evidence missing",
        )
        matched = [i for i in images if i["image"] == provenance["deployment_image"]]
        require(len(matched) == 1, "deployment image missing in catalog")
        image = matched[0]
        require(
            image["profiles"][name]["status"] == "evaluated",
            "catalog profile not evaluated",
        )
        require(
            image["profiles"][name]["quantization"] == profile["quantization"],
            "catalog quantization mismatch",
        )
        require(
            image["runtime_base"] == profile["runtime_image"]
            and image["runtime_version"] == profile["runtime_version"],
            "catalog runtime mismatch",
        )
        require(
            image["profiles_sha256"] == provenance["profiles_sha256"],
            "catalog profiles hash mismatch",
        )
        require(
            any(
                b["source_revision"] == image["source_revision"]
                and b["workflow_run"] == image["workflow_run"]
                for b in evidence["builds"]
            ),
            "catalog build evidence missing",
        )
        output[name] = {
            "ai": ai_result,
            "http": http_result,
            "stored_evidence_consistent": True,
        }
    return {
        "status": "VERIFIED",
        "scope": "stored evidence consistency only; no raw AI output review or live resource verification",
        "models": output,
    }


def load_reports(root: Path = ROOT) -> dict:
    return {
        name: (
            json.loads(
                (root / f"ai/eval/chatbot/validation/{name}-20260908.json").read_text()
            ),
            json.loads(
                (
                    root / f"backend/eval/validation/chatbot-http-{name}-20260908.json"
                ).read_text()
            ),
        )
        for name in PROFILES
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog",
        type=Path,
        default=Path(__file__).with_name("published-images.json"),
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        default=Path(__file__).with_name("model-comparison-evidence-2026-09-08.json"),
    )
    args = parser.parse_args()
    try:
        result = verify(
            json.loads(args.catalog.read_text()),
            json.loads(args.evidence.read_text()),
            load_reports(),
        )
    except (ValueError, KeyError, TypeError, OSError, IndexError):
        print(json.dumps({"status": "INVALID", "scope": "stored evidence consistency"}))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
