import importlib.util
import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "infra/delivery/lambda/runpod_monitor.py"
SPEC = importlib.util.spec_from_file_location("runpod_monitor", PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

NOW = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
POD_ID = "pod123"
KEYS = {
    "AI_VLLM_SLLM_API_KEY": "s" * 43,
    "AI_VLLM_STT_API_KEY": "t" * 43,
}


def pod(*, pod_id=POD_ID, status="RUNNING", age_hours=1):
    return {
        "id": pod_id,
        "name": MODULE.SHARED_POD_NAME,
        "desiredStatus": status,
        "lastStartedAt": (NOW - timedelta(hours=age_hours)).isoformat(),
        "adjustedCostPerHr": 0.69,
    }


def endpoint(*, status="active", pod_id=POD_ID):
    return {
        "status": status,
        "pod_id": pod_id,
        "sllm_base_url": f"https://{pod_id}-8001.proxy.runpod.net/v1",
        "stt_base_url": f"https://{pod_id}-8002.proxy.runpod.net/v1",
        "updated_at": (NOW - timedelta(hours=2)).isoformat(),
    }


class ObserveTests(unittest.TestCase):
    def test_healthy_active_pod_emits_runtime_and_cost(self):
        with patch.object(MODULE, "_health", return_value=1.0):
            metrics = MODULE.observe([pod(age_hours=8)], endpoint(), KEYS, NOW)
        self.assertEqual(metrics["RunPodControlPlaneReachable"], 1)
        self.assertEqual(metrics["RunPodEndpointConsistent"], 1)
        self.assertEqual(metrics["RunPodSllmHealthy"], 1)
        self.assertEqual(metrics["RunPodSttHealthy"], 1)
        self.assertEqual(metrics["RunPodRuntimeHours"], 8)
        self.assertEqual(metrics["RunPodHourlyCostUsd"], 0.69)

    def test_endpoint_mismatch_does_not_probe_or_mutate(self):
        with patch.object(MODULE, "_health") as health:
            metrics = MODULE.observe([pod(pod_id="other")], endpoint(), KEYS, NOW)
        self.assertEqual(metrics["RunPodEndpointConsistent"], 0)
        health.assert_not_called()

    def test_offline_orphan_age_is_reported(self):
        metrics = MODULE.observe(
            [pod(age_hours=2)], endpoint(status="offline", pod_id=None), KEYS, NOW
        )
        self.assertEqual(metrics["RunPodOrphanPodAgeMinutes"], 120)
        self.assertEqual(metrics["RunPodSllmHealthy"], 1)

    def test_health_401_404_and_timeout_are_failures(self):
        for failure in (
            MODULE.MonitorError("HTTP_401"),
            MODULE.MonitorError("HTTP_404"),
            MODULE.MonitorError("UNREACHABLE"),
        ):
            with self.subTest(failure=failure), patch.object(
                MODULE, "_request_json", side_effect=failure
            ):
                self.assertEqual(
                    MODULE._health("https://pod-8001.proxy.runpod.net/v1", "key"),
                    0,
                )

    def test_non_running_pod_is_not_healthy_probed(self):
        with patch.object(MODULE, "_health") as health:
            metrics = MODULE.observe(
                [pod(status="EXITED")], endpoint(), KEYS, NOW
            )
        self.assertEqual(metrics["RunPodSharedPodRunning"], 0)
        self.assertEqual(metrics["RunPodSllmHealthy"], 0)
        self.assertEqual(metrics["RunPodSttHealthy"], 0)
        health.assert_not_called()


if __name__ == "__main__":
    unittest.main()
