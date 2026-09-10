"""Explicit synthetic verification of already running resources; never starts them."""

from __future__ import annotations

import json
import math
import shlex
from datetime import UTC, datetime

from gpu_metrics import safe_identity
from manage_dev_power import ToolError, emit
from model_profiles import load_profile
from probe import verify
from selection_catalog import load_catalog
from serving_contract import GENERAL_KEY, POD_NAME, endpoint_urls
from serving_selection import fingerprint


def expected_identities(serving, workload: str, spec: dict) -> list[dict]:
    common = {"image": spec["image"]}
    if workload == "general":
        profile = load_profile(spec["model_profile"])
        return [
            {
                **common,
                "profile": spec["model_profile"],
                "model": profile["model"],
                "revision": profile["revision"],
            }
        ]
    manifest, checksum, _ = serving.release(spec, presign=False)
    return [
        {
            **common,
            "release_id": spec["release_id"],
            "artifact_sha256": checksum,
            "model": manifest["base_model"]["id"],
            "revision": manifest["base_model"]["revision"],
        },
        {
            **common,
            "model": "openai/whisper-large-v3-turbo",
            "revision": "41f01f3fe87f28c78e2fbf8b568835947dd65ed9",
        },
    ]


def checked_result(result: object, expected: list[dict]) -> dict:
    """Recheck host output against CENTRAL desired state, not host-local manifests."""
    if (
        not isinstance(result, dict)
        or type(result.get("passed")) is not bool
        or not isinstance(result.get("services"), list)
        or len(result["services"]) != len(expected)
    ):
        raise ToolError(
            "invalid verification service count/result; no success recorded"
        )
    rows = []
    for raw, target in zip(result["services"], expected, strict=True):
        if (
            not isinstance(raw, dict)
            or type(raw.get("passed")) is not bool
            or type(raw.get("inference_passed")) is not bool
        ):
            raise ToolError("invalid verification result; no success recorded")
        identity = safe_identity(raw.get("identity"))
        checks = {
            key: "unavailable"
            if key not in identity
            else "match"
            if identity[key] == value
            else "mismatch"
            for key, value in target.items()
        }
        latency = raw.get("latency_seconds")
        if (
            isinstance(latency, bool)
            or not isinstance(latency, (int, float))
            or not math.isfinite(latency)
            or latency < 0
        ):
            raise ToolError("invalid verification latency")
        gpu = raw.get("gpu") if isinstance(raw.get("gpu"), dict) else {}
        numbers = {
            key: value if type(value) is int and value >= 0 else None
            for key in ("observed_peak_used_mib", "total_mib", "samples")
            for value in [gpu.get(key)]
        }
        sampled = gpu.get("status") == "sampled" and all(
            value is not None for value in numbers.values()
        )
        rows.append(
            {
                "passed": raw["passed"]
                and raw["inference_passed"]
                and not raw.get("identity_changed", False)
                and all(v == "match" for v in checks.values()),
                "inference_passed": raw["inference_passed"],
                "identity": identity,
                "identity_checks": checks,
                "latency_seconds": latency,
                "gpu": {
                    "status": "sampled" if sampled else "unavailable",
                    **numbers,
                    "scope": "observed device samples; not guaranteed peak",
                },
            }
        )
    return {
        "passed": result["passed"] and all(row["passed"] for row in rows),
        "services": rows,
    }


def verify_running(serving, workload: str) -> dict:
    desired = serving.selection_document()
    spec = desired[workload]
    endpoint = serving.endpoint(workload)
    if not spec or endpoint.get("status") != "active":
        raise ToolError("selected workload must already be active; run dev-start first")
    cloud = endpoint.get("cloud", "runpod")
    if cloud != spec["cloud"]:
        raise ToolError("active endpoint cloud differs from selection")
    if workload == "f2" and endpoint.get("sllm_release_id") != spec["release_id"]:
        raise ToolError("active F2 release differs from selection")
    if workload == "general" and (
        endpoint.get("model_profile") != spec["model_profile"]
        or endpoint.get("model") != load_profile(spec["model_profile"])["model"]
    ):
        raise ToolError("active general model differs from selection")
    expected = expected_identities(serving, workload, spec)
    hardware = load_catalog()["profiles"][spec["hardware_profile"]]
    hardware_status = "unavailable"
    if cloud == "aws":
        identifier = (
            endpoint.get("instance_id")
            if workload == "f2"
            else endpoint.get("resource_id")
        )
        instances = [
            i for i in serving.instances(workload) if i["InstanceId"] == identifier
        ]
        if len(instances) != 1 or instances[0]["State"]["Name"] != "running":
            raise ToolError("selected AWS GPU is not running")
        if instances[0].get("InstanceType") != hardware["instance_type"]:
            raise ToolError("AWS instance type differs from selected GPU profile")
        hardware_status = "match"
        tags = {tag["Key"]: tag["Value"] for tag in instances[0].get("Tags", [])}
        if tags.get("ServingImage") != spec["image"]:
            raise ToolError("AWS serving image differs from selection")
        # Exit status is encoded separately, so failed identity checks retain safe metrics.
        command = "python3 /opt/brokerage-gpu/probe.py --verify"
        if workload == "general":
            command += " --model " + shlex.quote(
                load_profile(spec["model_profile"])["model"]
            )
        raw = serving.command(
            identifier, command + "; result=$?; test $result -le 1", timeout=600
        )
        try:
            result = json.loads(raw)
        except ValueError:
            raise ToolError("invalid host verification JSON") from None
    else:
        identifier = (
            endpoint.get("pod_id") if workload == "f2" else endpoint.get("resource_id")
        )
        pod = serving.runpod().pod(identifier)
        if (
            pod.get("name") != POD_NAME[workload]
            or pod.get("imageName") != spec["image"]
        ):
            raise ToolError("RunPod image/resource differs from selection")
        keys = serving.secret("ai/provider-api-keys")
        urls = endpoint_urls(cloud, identifier, workload)
        # GPU API schemas vary. Never label a requested type as an observed type.
        observed_gpu = (pod.get("machine") or {}).get("gpuTypeId")
        if observed_gpu is not None:
            if observed_gpu != spec["gpu_id"]:
                raise ToolError("RunPod GPU differs from selected hardware")
            hardware_status = "match"
        if workload == "general":
            services = [
                verify(
                    urls[0],
                    keys[GENERAL_KEY],
                    expected[0]["model"],
                    expected_identity=expected[0],
                )
            ]
        else:
            services = [
                verify(
                    urls[0],
                    keys["AI_VLLM_SLLM_API_KEY"],
                    "sllm",
                    expected_identity=expected[0],
                ),
                verify(
                    urls[1],
                    keys["AI_VLLM_STT_API_KEY"],
                    "stt",
                    stt=True,
                    expected_identity=expected[1],
                ),
            ]
        result = {
            "passed": all(item["passed"] for item in services),
            "services": services,
        }
    result = checked_result(result, expected)
    if fingerprint(serving.selection_document()) != fingerprint(desired):
        raise ToolError(
            "selection changed during verification; result cannot be attributed"
        )
    application_passed = False
    try:
        serving.application_smoke(workload)
        application_passed = True
    except ToolError:
        pass
    result.update(
        workload=workload,
        selection_id=desired["selection_id"],
        resource_id=identifier,
        cloud=cloud,
        image=spec["image"],
        hardware_profile=spec["hardware_profile"],
        hardware_verification=hardware_status,
        application_passed=application_passed,
        checked_at=datetime.now(UTC).isoformat(),
    )
    result["passed"] = result["passed"] and application_passed
    emit("dev-verification", **result)
    if not result["passed"]:
        raise ToolError(
            "verification incomplete; missing identity requires the updated published image; see dev-verification checks"
        )
    return result
