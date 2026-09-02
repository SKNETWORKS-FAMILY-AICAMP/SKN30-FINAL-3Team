"""Read-only RunPod control-plane and authenticated F2 health monitor."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import boto3

RUNPOD_PODS_URL = "https://rest.runpod.io/v1/pods"
SHARED_POD_NAME = "skn30-f2-serving-dev"
ENDPOINT_STATUSES = frozenset({"active", "offline"})
F2_KEYS = {
    "RunPodSllmHealthy": "AI_VLLM_SLLM_API_KEY",
    "RunPodSttHealthy": "AI_VLLM_STT_API_KEY",
}


class MonitorError(RuntimeError):
    """A classified monitor failure whose message contains no external response."""


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise MonitorError(f"missing required setting: {name}")
    return value


def _request_json(url: str, authorization: str, timeout: float = 8) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": authorization,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        raise MonitorError(f"HTTP_{error.code}") from None
    except (urllib.error.URLError, TimeoutError):
        raise MonitorError("UNREACHABLE") from None
    except json.JSONDecodeError:
        raise MonitorError("INVALID_JSON") from None


def _secret_string(client: Any, secret_id: str) -> str:
    result = client.get_secret_value(SecretId=secret_id)
    value = result.get("SecretString")
    if not isinstance(value, str) or not value:
        raise MonitorError("secret has no string AWSCURRENT value")
    return value


def _json_object(raw: str, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise MonitorError(f"{label} is invalid JSON") from error
    if not isinstance(value, Mapping):
        raise MonitorError(f"{label} is not an object")
    return dict(value)


def _pod_id(pod: Mapping[str, Any]) -> str | None:
    value = pod.get("id")
    return value if isinstance(value, str) else None


def _pod_status(pod: Mapping[str, Any]) -> str:
    return str(pod.get("desiredStatus") or pod.get("status") or "UNKNOWN").upper()


def _safe_endpoint_status(endpoint: Mapping[str, Any]) -> str:
    value = endpoint.get("status")
    return value if isinstance(value, str) and value in ENDPOINT_STATUSES else "invalid"


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _age_hours(pod: Mapping[str, Any], observed_at: datetime) -> float:
    started = _timestamp(pod.get("lastStartedAt"))
    if started is None:
        return 0.0
    return max(0.0, (observed_at - started).total_seconds() / 3600)


def _cost(pod: Mapping[str, Any]) -> float:
    value = pod.get("adjustedCostPerHr", pod.get("costPerHr", 0))
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def _health(url: str, api_key: str) -> float:
    if not url.startswith("https://") or not url.endswith("/v1"):
        return 0.0
    try:
        _request_json(f"{url}/models", f"Bearer {api_key}")
        return 1.0
    except MonitorError:
        return 0.0


def observe(
    pods: Sequence[Mapping[str, Any]],
    endpoint: Mapping[str, Any],
    ai_keys: Mapping[str, Any],
    observed_at: datetime,
) -> dict[str, float]:
    shared = [pod for pod in pods if pod.get("name") == SHARED_POD_NAME]
    running = [pod for pod in shared if _pod_status(pod) == "RUNNING"]
    endpoint_active = endpoint.get("status") == "active"
    endpoint_pod = endpoint.get("pod_id")
    consistent = not endpoint_active or (
        len(shared) == 1 and _pod_id(shared[0]) == endpoint_pod
    )
    metrics = {
        "RunPodControlPlaneReachable": 1.0,
        "RunPodSharedPodPresent": float(bool(shared)),
        "RunPodSharedPodRunning": float(bool(running)),
        "RunPodEndpointConsistent": float(consistent),
        "RunPodSllmHealthy": 1.0,
        "RunPodSttHealthy": 1.0,
        "RunPodOrphanPodAgeMinutes": 0.0,
        "RunPodRuntimeHours": max(
            (_age_hours(pod, observed_at) for pod in running), default=0.0
        ),
        "RunPodHourlyCostUsd": sum(_cost(pod) for pod in running),
        "RunPodMonitorHeartbeat": 1.0,
    }
    if not endpoint_active and shared:
        offline_at = _timestamp(endpoint.get("updated_at"))
        if offline_at is not None:
            metrics["RunPodOrphanPodAgeMinutes"] = max(
                0.0, (observed_at - offline_at).total_seconds() / 60
            )
    if endpoint_active and consistent:
        metrics["RunPodSllmHealthy"] = 0.0
        metrics["RunPodSttHealthy"] = 0.0
    if endpoint_active and consistent and len(running) == 1:
        for metric, key_name in F2_KEYS.items():
            key = ai_keys.get(key_name)
            base_name = "sllm_base_url" if metric == "RunPodSllmHealthy" else "stt_base_url"
            base_url = endpoint.get(base_name)
            if not isinstance(key, str) or not isinstance(base_url, str):
                metrics[metric] = 0.0
            else:
                metrics[metric] = _health(base_url, key)
    return metrics


def _publish(client: Any, namespace: str, metrics: Mapping[str, float]) -> None:
    client.put_metric_data(
        Namespace=namespace,
        MetricData=[
            {
                "MetricName": name,
                "Value": value,
                "Unit": (
                    "Count"
                    if name
                    in {
                        "RunPodControlPlaneReachable",
                        "RunPodSharedPodPresent",
                        "RunPodSharedPodRunning",
                        "RunPodEndpointConsistent",
                        "RunPodSllmHealthy",
                        "RunPodSttHealthy",
                        "RunPodMonitorHeartbeat",
                    }
                    else "None"
                ),
            }
            for name, value in metrics.items()
        ],
    )


def handler(_event: Mapping[str, Any], _context: Any) -> dict[str, Any]:
    secrets_client = boto3.client("secretsmanager")
    ssm_client = boto3.client("ssm")
    cloudwatch_client = boto3.client("cloudwatch")
    namespace = _required("METRIC_NAMESPACE")
    monitor_key = _secret_string(secrets_client, _required("MONITOR_SECRET_ARN"))
    ai_keys = _json_object(
        _secret_string(secrets_client, _required("AI_PROVIDER_SECRET_ARN")),
        "AI provider secret",
    )
    endpoint_raw = ssm_client.get_parameter(Name=_required("ENDPOINT_PARAMETER_NAME"))
    endpoint = _json_object(
        endpoint_raw.get("Parameter", {}).get("Value", ""), "endpoint parameter"
    )
    try:
        payload = _request_json(RUNPOD_PODS_URL, f"Bearer {monitor_key}")
        if not isinstance(payload, list) or not all(
            isinstance(item, Mapping) for item in payload
        ):
            raise MonitorError("PODS_INVALID")
        metrics = observe(payload, endpoint, ai_keys, datetime.now(UTC))
        outcome = "ok"
    except MonitorError as error:
        metrics = {
            "RunPodControlPlaneReachable": 0.0,
            "RunPodMonitorHeartbeat": 1.0,
        }
        outcome = str(error)
    _publish(cloudwatch_client, namespace, metrics)
    summary = {
        "event": "runpod-monitor",
        "outcome": outcome,
        "endpoint_status": _safe_endpoint_status(endpoint),
        "metric_count": len(metrics),
    }
    print(json.dumps(summary, sort_keys=True))
    return summary
