"""Remote verification cannot attest stale host manifests or empty results."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "scripts"),
    str(ROOT / "serving"),
    str(ROOT / "deploy/scripts"),
]
from manage_dev_power import ToolError
from serving_verification import checked_result


class Verification(unittest.TestCase):
    def row(self, release="consultation-v3"):
        return {
            "passed": True,
            "inference_passed": True,
            "identity": {"release_id": release},
            "latency_seconds": 1.25,
            "gpu": {"status": "unavailable"},
        }

    def test_stale_host_release_fails_central_identity_check(self):
        result = checked_result(
            {"passed": True, "services": [self.row("old-release")]},
            [{"release_id": "consultation-v3"}],
        )
        self.assertFalse(result["passed"])
        self.assertEqual(
            result["services"][0]["identity_checks"]["release_id"], "mismatch"
        )

    def test_empty_or_malformed_results_never_pass(self):
        for result in (
            {"passed": True, "services": []},
            {"passed": 1, "services": [self.row()]},
            {"passed": True, "services": [{}]},
            None,
        ):
            with self.subTest(result=result), self.assertRaises(ToolError):
                checked_result(result, [{"release_id": "consultation-v3"}])

    def test_unknown_remote_fields_are_not_forwarded(self):
        row = {**self.row(), "secret": "do-not-log"}
        row["identity"]["token"] = "do-not-log"
        result = checked_result(
            {"passed": True, "services": [row], "raw": "do-not-log"},
            [{"release_id": "consultation-v3"}],
        )
        self.assertTrue(result["passed"])
        self.assertNotIn("do-not-log", str(result))
        self.assertIsNone(result["services"][0]["gpu"]["observed_peak_used_mib"])

    def test_both_f2_services_are_required_and_checked(self):
        result = checked_result(
            {
                "passed": True,
                "services": [self.row(), {**self.row(), "inference_passed": False}],
            },
            [{"release_id": "consultation-v3"}] * 2,
        )
        self.assertFalse(result["passed"])
