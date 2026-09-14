"""Mutation tests for the read-only published comparison verifier."""

import copy
import json
import sys
import unittest
from pathlib import Path

SERVING = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVING))
import verify_comparison as verifier  # noqa: E402 - load the repository script after adding its path


class StoredComparison(unittest.TestCase):
    def setUp(self):
        self.catalog = json.loads((SERVING / "published-images.json").read_text())
        self.evidence = json.loads(
            (SERVING / "model-comparison-evidence-2026-09-08.json").read_text()
        )
        self.reports = verifier.load_reports()

    def verify(self):
        return verifier.verify(self.catalog, self.evidence, self.reports)

    def test_published_records_verify_and_preserve_failed_acceptance(self):
        result = self.verify()
        self.assertEqual(result["status"], "VERIFIED")
        self.assertFalse(result["models"]["qwen3-14b-awq"]["http"]["passed"])
        self.assertFalse(
            result["models"]["qwen3-32b-awq"]["ai"]["accuracy_safety_passed"]
        )
        self.assertTrue(result["models"]["qwen38-27b-fp8"]["http"]["passed"])
        self.assertFalse(result["models"]["qwen38-27b-fp8"]["ai"]["evaluator_passed"])
        self.assertEqual(
            result["models"]["qwen38-27b-fp8"]["ai"]["ambiguous_unsupported_accuracy"],
            0.8,
        )

    def test_round_accuracy_and_counts_tampering_is_rejected(self):
        original = copy.deepcopy(self.reports)
        for field in (
            "supported_accuracy",
            "multiturn_accuracy",
            "basic_and_units_accuracy",
            "ambiguous_unsupported_accuracy",
            "nested_accuracy",
            "total",
            "correct_type",
        ):
            with self.subTest(field=field):
                self.reports = copy.deepcopy(original)
                row = self.reports["qwen3-14b-awq"][0]["rounds"]["1"]
                if field == "nested_accuracy":
                    row["basic_and_units"]["accuracy"] = 1.0
                elif field == "total":
                    row["multiturn"]["total"] = 11
                elif field == "correct_type":
                    row["multiturn"]["correct"] = 6.0
                else:
                    row[field] = 1.0
                with self.assertRaisesRegex(ValueError, "AI round"):
                    self.verify()

    def test_p95_tampering_is_rejected(self):
        self.reports["qwen38-27b-fp8"][1]["completion_p95_ms"] += 100
        with self.assertRaisesRegex(ValueError, "p95"):
            self.verify()

    def test_warmup_latency_is_excluded(self):
        report = self.reports["qwen38-27b-fp8"][1]
        report["rows"][0]["first_progress_ms"] = 100000
        report["rows"][0]["elapsed_ms"] = 200000
        self.assertTrue(self.verify()["models"]["qwen38-27b-fp8"]["http"]["passed"])

    def test_missing_and_duplicate_measurements_are_rejected(self):
        original = copy.deepcopy(self.reports)
        for mutation in ("missing", "duplicate"):
            with self.subTest(mutation=mutation):
                self.reports = copy.deepcopy(original)
                rows = self.reports["qwen3-14b-awq"][1]["rows"]
                if mutation == "missing":
                    rows.pop()
                else:
                    rows[-1] = copy.deepcopy(rows[-2])
                with self.assertRaisesRegex(ValueError, "missing or duplicated"):
                    self.verify()

    def test_correctness_restore_delete_and_acceptance_inconsistency_rejected(self):
        original = copy.deepcopy(self.reports)
        for mutation in ("correctness", "restore", "delete", "acceptance"):
            with self.subTest(mutation=mutation):
                self.reports = copy.deepcopy(original)
                report = self.reports["qwen38-27b-fp8"][1]
                if mutation == "correctness":
                    report["rows"][1]["total"] += 1
                elif mutation == "restore":
                    report["rows"][1]["restored"] = False
                elif mutation == "delete":
                    report["deleted"] = False
                else:
                    report["passed"] = False
                with self.assertRaisesRegex(ValueError, "flag mismatch"):
                    self.verify()

    def test_wrapper_digest_tampering_is_rejected_even_if_ai_http_agree(self):
        ai, http = self.reports["qwen38-27b-fp8"]
        fake = http["deployment_image"].split("@")[0] + "@sha256:" + "0" * 64
        ai["provenance"]["deployment_image"] = http["deployment_image"] = fake
        with self.assertRaisesRegex(ValueError, "Pod evidence"):
            self.verify()

    def test_manifest_and_profiles_hash_tampering_is_rejected(self):
        original = copy.deepcopy(self.reports)
        for field in ("weights", "profiles_sha256"):
            with self.subTest(field=field):
                self.reports = copy.deepcopy(original)
                ai, http = self.reports["qwen38-27b-fp8"]
                if field == "weights":
                    ai["provenance"]["profile"]["weights"][0]["sha256"] = "0" * 64
                    http["profile"] = copy.deepcopy(ai["provenance"]["profile"])
                else:
                    ai["provenance"][field] = http[field] = "0" * 64
                with self.assertRaisesRegex(ValueError, "manifest|profiles hash"):
                    self.verify()

    def test_deleted_pod_and_evaluated_image_are_required(self):
        pod = next(p for p in self.evidence["pods"] if p["profile"] == "qwen38-27b-fp8")
        pod["deleted"] = False
        with self.assertRaisesRegex(ValueError, "deletion"):
            self.verify()
        pod["deleted"] = True
        image = next(
            i
            for i in self.catalog["images"]
            if i["profiles"]["qwen38-27b-fp8"]["status"] == "evaluated"
        )
        image["profiles"]["qwen38-27b-fp8"]["status"] = "cpu_only"
        with self.assertRaisesRegex(ValueError, "not evaluated"):
            self.verify()

    def test_tag_source_mapping_and_ai_aggregate_tampering_rejected(self):
        self.catalog["images"][0]["tag"] += "-changed"
        with self.assertRaisesRegex(ValueError, "tag/source"):
            self.verify()
        self.catalog["images"][0]["tag"] = self.catalog["images"][0][
            "tag"
        ].removesuffix("-changed")
        self.reports["qwen38-27b-fp8"][0]["summary"]["supported_accuracy"] = 1.0
        with self.assertRaisesRegex(ValueError, "supported accuracy"):
            self.verify()


if __name__ == "__main__":
    unittest.main()
