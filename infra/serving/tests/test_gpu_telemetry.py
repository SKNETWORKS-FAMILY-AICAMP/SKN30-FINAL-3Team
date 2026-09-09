"""Synthetic telemetry and identity checks: no GPU or live endpoint required."""

import io
import json
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gpu_metrics
import probe


class GpuTelemetry(unittest.TestCase):
    def test_sampling_valid_zero_and_unavailable_are_distinct(self):
        for stdout, expected in (("0, 24576\n", 0), ("500,24576\n600,24576\n", 1100)):
            with patch.object(
                gpu_metrics.subprocess, "run", return_value=Mock(stdout=stdout)
            ):
                self.assertEqual(gpu_metrics.sample_gpu()["used_mib"], expected)
        for error in (FileNotFoundError(), subprocess.TimeoutExpired("nvidia-smi", 2)):
            with patch.object(gpu_metrics.subprocess, "run", side_effect=error):
                result = gpu_metrics.sample_gpu()
                self.assertEqual(result["status"], "unavailable")
                self.assertIsNone(result["used_mib"])
        for stdout in ("", "N/A,24576", "25000,24576", "-1,24576", "2,3,4"):
            with patch.object(
                gpu_metrics.subprocess, "run", return_value=Mock(stdout=stdout)
            ):
                self.assertEqual(gpu_metrics.sample_gpu()["status"], "unavailable")

    def test_runtime_identity_drops_extra_or_unsafe_fields(self):
        identity = gpu_metrics.safe_identity(
            {
                "model": "Qwen/Qwen3-4B",
                "revision": "a" * 40,
                "image": "https://user:secret@host?token=x",
                "api_key": "secret",
                "release_id": "consultation-v3",
            }
        )
        self.assertEqual(set(identity), {"model", "revision", "release_id"})
        self.assertNotIn("secret", json.dumps(identity))

    def test_f2_and_general_context_helpers_remain_identical(self):
        infra = Path(__file__).resolve().parents[2]
        self.assertEqual(
            (infra / "serving/gpu_metrics.py").read_text(),
            (infra / "runpod/scripts/gpu_metrics.py").read_text(),
        )

    def test_remote_bad_or_old_telemetry_is_unavailable(self):
        for data in (
            {},
            {"gpu": {"status": "sampled", "used_mib": True, "total_mib": 20}},
            {"gpu": {"status": "sampled", "used_mib": 21, "total_mib": 20}},
            [],
        ):
            with patch.object(
                probe.urllib.request,
                "build_opener",
                return_value=Mock(
                    open=Mock(return_value=io.BytesIO(json.dumps(data).encode()))
                ),
            ):
                self.assertIsNone(
                    probe.read_telemetry("http://localhost/v1", "secret")["gpu"]
                )

    def test_expected_identity_is_required_but_old_image_inference_still_runs(self):
        with (
            patch.object(
                probe, "read_telemetry", return_value={"identity": {}, "gpu": None}
            ),
            patch.object(probe, "probe") as inference,
        ):
            result = probe.verify(
                "http://localhost/v1",
                "secret",
                "sllm",
                expected_identity={"release_id": "consultation-v3"},
            )
        inference.assert_called_once()
        self.assertTrue(result["inference_passed"])
        self.assertFalse(result["passed"])
        self.assertEqual(result["identity_checks"], {"release_id": "unavailable"})
        self.assertIsNone(result["gpu"]["observed_peak_used_mib"])
        self.assertNotIn("secret", json.dumps(result))

    def test_inference_sample_peak_is_observed_not_fabricated(self):
        identity = {"release_id": "consultation-v3"}
        samples = iter((10, 90, 40, 20, 20, 20))

        def telemetry(*args):
            return {
                "identity": identity,
                "gpu": {"used_mib": next(samples, 20), "total_mib": 24576},
            }

        with (
            patch.object(probe, "read_telemetry", side_effect=telemetry),
            patch.object(
                probe, "probe", side_effect=lambda *args, **kwargs: time.sleep(0.13)
            ),
        ):
            result = probe.verify(
                "http://localhost/v1",
                "secret",
                "sllm",
                expected_identity=identity,
                sample_interval=0.05,
            )
        self.assertTrue(result["passed"])
        self.assertEqual(result["gpu"]["observed_peak_used_mib"], 90)
        self.assertGreaterEqual(result["gpu"]["samples"], 3)
        self.assertIn("not guaranteed", result["gpu"]["scope"])

    def test_mismatch_and_inference_error_are_reported_without_exception_text(self):
        with (
            patch.object(
                probe,
                "read_telemetry",
                return_value={"identity": {"release_id": "previous"}, "gpu": None},
            ),
            patch.object(probe, "probe", side_effect=ValueError("credential=secret")),
        ):
            result = probe.verify(
                "http://localhost/v1",
                "secret",
                "sllm",
                expected_identity={"release_id": "consultation-v3"},
            )
        self.assertFalse(result["passed"])
        self.assertEqual(result["identity_checks"]["release_id"], "mismatch")
        self.assertEqual(result["error"], "synthetic-inference-failed")
        self.assertNotIn("secret", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
