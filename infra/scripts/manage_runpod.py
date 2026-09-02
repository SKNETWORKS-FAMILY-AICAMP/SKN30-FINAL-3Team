#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13,<3.14"
# dependencies = [
#   "boto3>=1.40,<2",
# ]
# ///
"""Create, inspect, and delete the ephemeral shared RunPod F2 development Pod."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import boto3
import manage_sllm_artifact as artifact
from botocore.exceptions import BotoCoreError, ClientError

SHARED_POD_NAME = "skn30-f2-serving-dev"
DEFAULT_TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "runpod" / "template.json"
DEFAULT_TIMEOUT_SECONDS = 1_800
DEFAULT_REGION = "ap-northeast-2"
REQUIRED_PORTS = {"8001/http", "8002/http"}
REQUIRED_SECRET_REFERENCES = {
    "AI_VLLM_SLLM_API_KEY": "{{ RUNPOD_SECRET_AI_VLLM_SLLM_API_KEY }}",
    "AI_VLLM_STT_API_KEY": "{{ RUNPOD_SECRET_AI_VLLM_STT_API_KEY }}",
}
IMAGE_PATTERN = re.compile(r"ghcr\.io/[a-z0-9._/-]+@sha256:[0-9a-f]{64}\Z")
PLACEHOLDER_IMAGE_PATTERN = re.compile(
    r"ghcr\.io/[a-z0-9._/-]+@sha256:REPLACE_AFTER_FIRST_PUBLISH\Z"
)
IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9_.-]{3,200}\Z")
POD_ID_PATTERN = re.compile(r"[a-z0-9]{5,64}\Z")
API_KEY_PATTERN = re.compile(r"[A-Za-z0-9_-]{43,128}\Z")


class ToolError(RuntimeError):
    """An operator-safe failure that does not include credentials or response bodies."""


def emit(event: str, **fields: object) -> None:
    print(json.dumps({"event": event, **fields}, ensure_ascii=False, sort_keys=True))


def redact_text(value: str) -> str:
    value = re.sub(r"(?i)Bearer\s+\S+", "Bearer [REDACTED]", value)
    value = re.sub(
        r"(?i)(api[_-]?key|token|password|secret|X-Amz-Signature)(\s*[=:]\s*)\S+",
        r"\1\2[REDACTED]",
        value,
    )
    return value


def field(item: Mapping[str, Any], *names: str) -> Any:
    return next((item[name] for name in names if name in item), None)


def resource_id(item: Mapping[str, Any], resource: str = "pod") -> str:
    value = field(item, "id", f"{resource}Id", f"{resource}_id")
    if not isinstance(value, str) or not value:
        raise ToolError(f"RunPod {resource} response is missing its ID")
    return value


def resource_name(item: Mapping[str, Any]) -> str:
    value = field(item, "name", "podName", "pod_name")
    return value if isinstance(value, str) else ""


def pod_status(item: Mapping[str, Any]) -> str:
    return str(field(item, "desiredStatus", "status", "podStatus") or "UNKNOWN").upper()


def object_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        values = payload
    elif isinstance(payload, Mapping):
        values = next(
            (
                payload[key]
                for key in ("pods", "items", "data")
                if isinstance(payload.get(key), list)
            ),
            None,
        )
        if values is None:
            raise ToolError("RunPod API returned an unexpected collection")
    else:
        raise ToolError("RunPod API returned an unexpected collection")
    if not all(isinstance(item, Mapping) for item in values):
        raise ToolError("RunPod API returned an invalid collection")
    return [dict(item) for item in values]


def one_object(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ToolError("RunPod API returned an unexpected object")
    for key in ("pod", "user", "registry", "data"):
        if isinstance(payload.get(key), Mapping):
            return dict(payload[key])
    return dict(payload)


def shared_pods(pods: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dict(pod) for pod in pods if resource_name(pod) == SHARED_POD_NAME]


class HttpRequester(Protocol):
    def __call__(self, request: urllib.request.Request, timeout: float) -> bytes: ...


def urlopen_request(request: urllib.request.Request, timeout: float) -> bytes:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


class RunpodApi:
    base_url = "https://rest.runpod.io/v1"

    def __init__(
        self,
        api_key: str,
        requester: HttpRequester = urlopen_request,
        timeout: float = 20,
    ) -> None:
        if not api_key or any(char.isspace() for char in api_key):
            raise ToolError("RunPod API key is empty or invalid")
        self._api_key = api_key
        self._requester = requester
        self._timeout = timeout

    def request(
        self, method: str, path: str, payload: Mapping[str, Any] | None = None
    ) -> Any:
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        try:
            raw = self._requester(request, self._timeout)
            return json.loads(raw or b"null")
        except urllib.error.HTTPError as error:
            raise ToolError(
                f"RunPod API {method} {path} failed with HTTP {error.code}"
            ) from None
        except (urllib.error.URLError, TimeoutError):
            raise ToolError(f"RunPod API {method} {path} was unreachable") from None
        except json.JSONDecodeError:
            raise ToolError(f"RunPod API {method} {path} returned invalid JSON") from None

    def registry(self, registry_id: str) -> dict[str, Any]:
        return one_object(
            self.request("GET", f"/containerregistryauth/{registry_id}")
        )

    def pods(self) -> list[dict[str, Any]]:
        return object_list(self.request("GET", "/pods"))

    def pod(self, pod_id: str) -> dict[str, Any]:
        return one_object(self.request("GET", f"/pods/{pod_id}"))

    def create(
        self,
        *,
        template_id: str,
        gpu_id: str,
        environment: Mapping[str, str],
        terminate_after: str | None,
    ) -> dict[str, Any]:
        if terminate_after is not None:
            raise ToolError("automatic Pod termination is outside the operating contract")
        return one_object(
            self.request(
                "POST",
                "/pods",
                {
                    "name": SHARED_POD_NAME,
                    "cloudType": "SECURE",
                    "computeType": "GPU",
                    "gpuCount": 1,
                    "gpuTypeIds": [gpu_id],
                    "gpuTypePriority": "availability",
                    "interruptible": False,
                    "locked": False,
                    "supportPublicIp": True,
                    "templateId": template_id,
                    "env": dict(environment),
                    "volumeInGb": 0,
                },
            )
        )

    def delete(self, pod_id: str) -> None:
        self.request("DELETE", f"/pods/{pod_id}")


@dataclass(frozen=True)
class TemplateSpec:
    version: int
    name: str
    image: str
    container_disk_gb: int
    ports: tuple[str, ...]
    env: dict[str, str]
    docker_start_cmd: str


def load_template_spec(path: Path, *, allow_placeholder: bool = False) -> TemplateSpec:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ToolError(
            f"could not read a valid RunPod Template spec: {path}"
        ) from error
    if not isinstance(payload, dict):
        raise ToolError("RunPod Template spec must be an object")
    version = payload.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ToolError("Template version must be a positive integer")
    name = payload.get("name")
    if name != f"skn30-f2-serving-v{version}":
        raise ToolError("Template name must be skn30-f2-serving-v<version>")
    image = str(payload.get("image", ""))
    if IMAGE_PATTERN.fullmatch(image) is None and not (
        allow_placeholder and PLACEHOLDER_IMAGE_PATTERN.fullmatch(image)
    ):
        raise ToolError("Template image must be a private GHCR image pinned by digest")
    ports = payload.get("ports")
    if not isinstance(ports, list) or set(ports) != REQUIRED_PORTS:
        raise ToolError("Template ports must be 8001/http and 8002/http")
    if "volume_disk_gb" in payload or "volume_mount_path" in payload:
        raise ToolError("ephemeral serving Template must not attach a Volume Disk")
    container_disk = payload.get("container_disk_gb")
    if (
        isinstance(container_disk, bool)
        or not isinstance(container_disk, int)
        or container_disk < 30
    ):
        raise ToolError("Template container disk must be at least 30 GB")
    env = payload.get("env")
    if not isinstance(env, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in env.items()
    ):
        raise ToolError("Template env must be a string map")
    for secret_name, expected in REQUIRED_SECRET_REFERENCES.items():
        if env.get(secret_name) != expected:
            raise ToolError(f"Template must reference RunPod Secret {secret_name}")
    forbidden = {
        "F2_SLLM_MODEL_ID",
        "F2_SLLM_MODEL_REVISION",
        "F2_SLLM_LORA_PATH",
        "F2_SLLM_BUNDLE_URL",
    }
    if forbidden & env.keys():
        raise ToolError("Template must not hardcode a SLLM release or bundle URL")
    command = payload.get("docker_start_cmd")
    if command != "python,/opt/f2-runtime/scripts/supervisor.py":
        raise ToolError("Template must start the supervisor directly")
    return TemplateSpec(
        version, str(name), image, container_disk, tuple(ports), dict(env), str(command)
    )


def validate_identifier(value: str, label: str) -> str:
    if IDENTIFIER_PATTERN.fullmatch(value) is None:
        raise ToolError(f"{label} is required and has an invalid format")
    return value


def validate_api_keys(sllm: str, stt: str) -> tuple[str, str]:
    if (
        API_KEY_PATTERN.fullmatch(sllm) is None
        or API_KEY_PATTERN.fullmatch(stt) is None
    ):
        raise ToolError(
            "local SLLM and STT API keys must be 43-128 URL-safe characters"
        )
    if sllm == stt:
        raise ToolError("SLLM and STT API keys must be different")
    return sllm, stt


@dataclass(frozen=True)
class OperationalValues:
    runpod_api_key: str
    f2_keys: tuple[str, str]
    template_id: str
    registry_id: str
    image: str


def aws_operational_values(
    *, account_id: str, profile: str, region: str, project: str
) -> OperationalValues:
    if re.fullmatch(r"[0-9]{12}", account_id) is None:
        raise ToolError("TARGET_ACCOUNT_ID must be an explicit 12-digit account ID")
    if region != DEFAULT_REGION:
        raise ToolError(f"AWS region must be {DEFAULT_REGION}")
    prefix = f"{project}-dev"
    try:
        session = boto3.Session(profile_name=profile, region_name=region)
        actual_account = session.client("sts").get_caller_identity().get("Account")
        if actual_account != account_id:
            raise ToolError("the active AWS identity does not match TARGET_ACCOUNT_ID")
        secrets_client = session.client("secretsmanager")
        ssm_client = session.client("ssm")
        operator = secrets_client.get_secret_value(
            SecretId=f"/{prefix}/runpod/operator-api-key"
        ).get("SecretString")
        ai_raw = secrets_client.get_secret_value(
            SecretId=f"/{prefix}/ai/provider-api-keys"
        ).get("SecretString")
        control_raw = ssm_client.get_parameter(
            Name=f"/{prefix}/runpod/RUNPOD_CONTROL_SET"
        ).get("Parameter", {}).get("Value")
    except ToolError:
        raise
    except (BotoCoreError, ClientError) as error:
        raise ToolError(
            "could not read the AWS RunPod operational secrets and control document"
        ) from error
    try:
        ai = json.loads(ai_raw)
        control = json.loads(control_raw)
    except (TypeError, json.JSONDecodeError) as error:
        raise ToolError("AWS RunPod operational data is not valid JSON") from error
    if not isinstance(ai, Mapping) or not isinstance(control, Mapping):
        raise ToolError("AWS RunPod operational data has an invalid shape")
    if control.get("status") != "ready":
        raise ToolError("RunPod control status is not ready; resume bootstrap first")
    raw_values = (
        operator,
        ai.get("AI_VLLM_SLLM_API_KEY"),
        ai.get("AI_VLLM_STT_API_KEY"),
        control.get("template_id"),
        control.get("registry_auth_id"),
        control.get("image"),
    )
    if not all(isinstance(value, str) and value for value in raw_values):
        raise ToolError("AWS RunPod operational data is incomplete")
    if IMAGE_PATTERN.fullmatch(str(raw_values[5])) is None:
        raise ToolError("AWS RunPod control image is not an immutable GHCR digest")
    f2_keys = validate_api_keys(str(raw_values[1]), str(raw_values[2]))
    return OperationalValues(
        runpod_api_key=str(raw_values[0]),
        f2_keys=f2_keys,
        template_id=str(raw_values[3]),
        registry_id=str(raw_values[4]),
        image=str(raw_values[5]),
    )


def proxy_urls(pod_id: str) -> tuple[str, str]:
    return (
        f"https://{pod_id}-8001.proxy.runpod.net/v1",
        f"https://{pod_id}-8002.proxy.runpod.net/v1",
    )


def verify_pod(
    details: Mapping[str, Any], *, spec: TemplateSpec, template_id: str
) -> None:
    actual_image = field(details, "imageName", "image", "containerImage")
    if actual_image is not None and actual_image != spec.image:
        raise ToolError("shared Pod image digest does not match template.json")
    actual_template = field(details, "templateId", "template_id")
    if actual_template is not None and actual_template != template_id:
        raise ToolError("shared Pod Template ID does not match RUNPOD_TEMPLATE_ID")
    gpu_count = field(details, "gpuCount", "gpu_count")
    if gpu_count is not None and str(gpu_count) != "1":
        raise ToolError("shared Pod must use exactly one GPU")


def request_models(base_url: str, api_key: str) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{base_url}/models", headers={"Authorization": f"Bearer {api_key}"}
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    started = time.monotonic()
    try:
        with opener.open(request, timeout=15) as response:
            payload = json.loads(response.read(1024 * 1024))
            ok = (
                response.status == 200
                and isinstance(payload, dict)
                and isinstance(payload.get("data"), list)
            )
            return {
                "ok": ok,
                "status": response.status,
                "latency_ms": round((time.monotonic() - started) * 1000),
            }
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return {"ok": False, "status": "unreachable", "latency_ms": None}


class AwsOperations:
    def __init__(
        self, client: artifact.AwsCli, *, bucket: str, parameter_name: str, project: str
    ) -> None:
        self.client = client
        self.bucket = bucket
        self.parameter_name = parameter_name
        self.project = project

    def release(self, release_id: str) -> tuple[dict[str, Any], str, str]:
        if artifact.RELEASE_ID.fullmatch(release_id) is None:
            raise ToolError("release-id is invalid")
        prefix = artifact.release_prefix(release_id)
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "release.json"
            self.client.run(
                "s3api",
                "get-object",
                "--bucket",
                self.bucket,
                "--key",
                f"{prefix}/release.json",
                str(manifest_path),
            )
            try:
                manifest = artifact._validate_manifest(
                    json.loads(manifest_path.read_text(encoding="utf-8"))
                )
            except (OSError, json.JSONDecodeError, artifact.ToolError) as error:
                raise ToolError("published SLLM release manifest is invalid") from error
        head = self.client.run(
            "s3api",
            "head-object",
            "--bucket",
            self.bucket,
            "--key",
            f"{prefix}/bundle.tar.gz",
        )
        try:
            bundle_sha = json.loads(head)["Metadata"]["sha256"]
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise ToolError(
                "published SLLM bundle is missing its checksum metadata"
            ) from error
        if (
            not isinstance(bundle_sha, str)
            or artifact.SHA256.fullmatch(bundle_sha) is None
        ):
            raise ToolError("published SLLM bundle checksum metadata is invalid")
        url = self.client.presign(
            bucket=self.bucket, key=f"{prefix}/bundle.tar.gz", expires=3600
        )
        return manifest, bundle_sha, url

    def current_endpoint(self) -> dict[str, Any]:
        raw = self.client.run(
            "ssm",
            "get-parameter",
            "--name",
            self.parameter_name,
            "--query",
            "Parameter.Value",
            "--output",
            "text",
        )
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ToolError("current endpoint set is not JSON") from error
        if not isinstance(value, dict) or not isinstance(value.get("revision"), int):
            raise ToolError("current endpoint set has no valid revision")
        return value

    def write_endpoint(self, value: Mapping[str, Any]) -> None:
        self.client.run(
            "ssm",
            "put-parameter",
            "--name",
            self.parameter_name,
            "--type",
            "String",
            "--overwrite",
            "--value",
            json.dumps(dict(value), separators=(",", ":")),
        )

    def _run_dev_script(self, script: str, comment: str) -> None:
        instances = self.client.run(
            "ec2",
            "describe-instances",
            "--filters",
            f"Name=tag:Project,Values={self.project}",
            "Name=tag:Environment,Values=dev",
            "Name=instance-state-name,Values=running",
            "--query",
            "Reservations[].Instances[].InstanceId",
            "--output",
            "json",
        )
        try:
            ids = json.loads(instances)
        except json.JSONDecodeError as error:
            raise ToolError(
                "could not identify the dev application instance"
            ) from error
        if not isinstance(ids, list) or len(ids) != 1 or not isinstance(ids[0], str):
            raise ToolError("expected exactly one running dev application instance")
        response = self.client.run(
            "ssm",
            "send-command",
            "--instance-ids",
            ids[0],
            "--document-name",
            "AWS-RunShellScript",
            "--comment",
            comment,
            "--parameters",
            json.dumps({"commands": [f"sudo /opt/brokerage/revision/scripts/{script}"]}),
            "--query",
            "Command.CommandId",
            "--output",
            "text",
        )
        command_id = response.strip()
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            status = self.client.run(
                "ssm",
                "get-command-invocation",
                "--command-id",
                command_id,
                "--instance-id",
                ids[0],
                "--query",
                "Status",
                "--output",
                "text",
            )
            if status == "Success":
                return
            if status in {"Cancelled", "Failed", "TimedOut", "Cancelling"}:
                raise ToolError("AWS endpoint refresh command failed")
            time.sleep(3)
        raise ToolError("AWS endpoint refresh timed out")

    def refresh(self) -> None:
        self._run_dev_script(
            "refresh_ai_endpoints.sh", "Refresh ephemeral RunPod F2 endpoints"
        )

    def smoke(self) -> None:
        self._run_dev_script("smoke_f2.sh", "Smoke test ephemeral RunPod F2 release")


def endpoint_value(
    *,
    previous: Mapping[str, Any],
    status: str,
    pod_id: str | None = None,
    release_id: str | None = None,
) -> dict[str, Any]:
    revision = previous.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ToolError("current endpoint revision is invalid")
    value: dict[str, Any] = {
        "revision": revision + 1,
        "status": status,
        "pod_id": pod_id,
        "sllm_release_id": release_id,
        "sllm_base_url": None,
        "stt_base_url": None,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    if status == "active":
        if not pod_id or not release_id:
            raise ToolError("active endpoint requires pod and release IDs")
        value["sllm_base_url"], value["stt_base_url"] = proxy_urls(pod_id)
    elif status != "offline":
        raise ToolError("endpoint status must be active or offline")
    return value


@dataclass
class Controller:
    runpod: RunpodApi
    aws: AwsOperations
    spec: TemplateSpec
    template_id: str
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    requester: Callable[[str, str], dict[str, Any]] = request_models
    sleeper: Callable[[float], None] = time.sleep

    def health(self, pod_id: str, keys: tuple[str, str]) -> dict[str, Any]:
        sllm, stt = proxy_urls(pod_id)
        return {
            "sllm": self.requester(sllm, keys[0]),
            "stt": self.requester(stt, keys[1]),
        }

    def wait_ready(self, pod_id: str, keys: tuple[str, str]) -> dict[str, Any]:
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            details = self.runpod.pod(pod_id)
            verify_pod(details, spec=self.spec, template_id=self.template_id)
            if pod_status(details) == "RUNNING":
                health = self.health(pod_id, keys)
                if all(value.get("ok") is True for value in health.values()):
                    return health
            self.sleeper(5)
        raise ToolError("shared Pod did not become ready before timeout")

    def create(
        self,
        *,
        release_id: str,
        gpu_id: str,
        terminate_after: str | None,
        apply: bool,
        keys: tuple[str, str],
    ) -> None:
        if shared_pods(self.runpod.pods()):
            raise ToolError(
                f"a Pod named {SHARED_POD_NAME!r} already exists; delete it first"
            )
        manifest, bundle_sha, url = self.aws.release(release_id)
        emit(
            "pod-create-plan",
            release_id=release_id,
            base_model=manifest["base_model"],
            gpu_id=gpu_id,
            cloud_type="SECURE",
            volume_disk_gb=0,
            apply=apply,
        )
        if not apply:
            return
        created = self.runpod.create(
            template_id=self.template_id,
            gpu_id=gpu_id,
            environment={
                "F2_SLLM_RELEASE_ID": release_id,
                "F2_SLLM_BUNDLE_SHA256": bundle_sha,
                "F2_SLLM_BUNDLE_URL": url,
            },
            terminate_after=terminate_after,
        )
        pod_id = resource_id(created)
        try:
            health = self.wait_ready(pod_id, keys)
            previous = self.aws.current_endpoint()
            active = endpoint_value(
                previous=previous, status="active", pod_id=pod_id, release_id=release_id
            )
            self.aws.write_endpoint(active)
            try:
                self.aws.refresh()
                self.aws.smoke()
            except Exception:
                self.aws.write_endpoint(previous)
                self.aws.refresh()
                raise
        except Exception:
            self.runpod.delete(pod_id)
            raise
        emit(
            "pod-create-complete",
            pod_id=pod_id,
            release_id=release_id,
            proxy_urls=proxy_urls(pod_id),
            health=health,
            delete_command=f"just -f infra/justfile runpod-delete {pod_id}",
        )

    def status(self, keys: tuple[str, str] | None) -> None:
        matches = shared_pods(self.runpod.pods())
        if not matches:
            emit("pod-status", status="ABSENT", endpoint=self.aws.current_endpoint())
            return
        if len(matches) != 1:
            raise ToolError(f"expected zero or one shared Pod; found {len(matches)}")
        summary = matches[0]
        pod_id = resource_id(summary)
        verify_pod(
            self.runpod.pod(pod_id), spec=self.spec, template_id=self.template_id
        )
        status = pod_status(summary)
        health: object = "not-checked"
        if status == "RUNNING" and keys:
            health = self.health(pod_id, keys)
        emit(
            "pod-status",
            pod_id=pod_id,
            status=status,
            proxy_urls=proxy_urls(pod_id),
            health=health,
            endpoint=self.aws.current_endpoint(),
        )

    def reconcile(
        self,
        *,
        keys: tuple[str, str],
        apply: bool,
        endpoint_offline_confirmed: bool,
    ) -> None:
        pods = self.runpod.pods()
        matches = shared_pods(pods)
        endpoint = self.aws.current_endpoint()
        status = endpoint.get("status")
        if status not in {"active", "offline"}:
            raise ToolError("endpoint status must be active or offline")
        if len(matches) > 1:
            emit(
                "runpod-reconcile-blocked",
                reason="multiple-shared-pods",
                pod_ids=[resource_id(pod) for pod in matches],
            )
            raise ToolError("multiple shared Pods require an operator decision")
        if status == "offline":
            if not matches:
                emit("runpod-reconcile-plan", state="offline-clean", actions=[])
                return
            pod_id = resource_id(matches[0])
            emit(
                "runpod-reconcile-plan",
                state="offline-orphan",
                pod_id=pod_id,
                actions=[
                    f"just -f infra/justfile runpod-delete {pod_id}",
                ],
                mutates=False,
            )
            return

        endpoint_pod_id = endpoint.get("pod_id")
        if not isinstance(endpoint_pod_id, str) or not endpoint_pod_id:
            raise ToolError("active endpoint has no Pod ID")
        if not matches:
            if any(resource_id(pod) == endpoint_pod_id for pod in pods):
                emit(
                    "runpod-reconcile-blocked",
                    reason="endpoint-points-to-different-pod",
                    endpoint_pod_id=endpoint_pod_id,
                )
                raise ToolError("active endpoint points to a non-shared Pod")
            actions = ["set endpoint offline", "refresh API and Worker environment"]
            emit(
                "runpod-reconcile-plan",
                state="active-pod-absent",
                actions=actions,
                apply=apply,
            )
            if not apply:
                return
            if not endpoint_offline_confirmed:
                raise ToolError("reconcile apply requires --endpoint-offline-confirmed")
            offline = endpoint_value(previous=endpoint, status="offline")
            self.aws.write_endpoint(offline)
            try:
                self.aws.refresh()
            except Exception:
                self.aws.write_endpoint(endpoint)
                self.aws.refresh()
                raise
            emit("runpod-reconcile-complete", endpoint_status="offline")
            return

        pod_id = resource_id(matches[0])
        if pod_id != endpoint_pod_id:
            emit(
                "runpod-reconcile-blocked",
                reason="endpoint-pod-mismatch",
                endpoint_pod_id=endpoint_pod_id,
                shared_pod_id=pod_id,
            )
            raise ToolError("active endpoint and shared Pod IDs differ")
        health = self.health(pod_id, keys) if pod_status(matches[0]) == "RUNNING" else {}
        if not health or not all(item.get("ok") is True for item in health.values()):
            emit(
                "runpod-reconcile-plan",
                state="active-health-failed",
                actions=[],
                mutates=False,
            )
            return
        emit(
            "runpod-reconcile-plan",
            state="active-consistent",
            health=health,
            actions=[],
        )

    def delete(self, *, pod_id: str, confirmed: bool, apply: bool) -> None:
        if not confirmed:
            raise ToolError("pod-delete requires --workloads-stopped-confirmed")
        matches = shared_pods(self.runpod.pods())
        if len(matches) != 1 or resource_id(matches[0]) != pod_id:
            raise ToolError("--pod-id must exactly match the single shared Pod")
        emit(
            "pod-delete-plan",
            pod_id=pod_id,
            data_loss="none; release remains in private S3",
            apply=apply,
        )
        if not apply:
            return
        previous = self.aws.current_endpoint()
        offline = endpoint_value(previous=previous, status="offline")
        self.aws.write_endpoint(offline)
        try:
            self.aws.refresh()
        except Exception:
            self.aws.write_endpoint(previous)
            self.aws.refresh()
            raise
        try:
            self.runpod.delete(pod_id)
        except Exception:
            self.aws.write_endpoint(previous)
            self.aws.refresh()
            raise
        emit(
            "pod-delete-complete",
            pod_id=pod_id,
            endpoint_status="offline",
            retained=f"s3://{self.aws.bucket}/releases/sllm/",
        )


def doctor(
    client: RunpodApi,
    spec: TemplateSpec,
    *,
    template_id: str,
    registry_id: str,
) -> None:
    for value, label in (
        (template_id, "RUNPOD_TEMPLATE_ID"),
        (registry_id, "RUNPOD_REGISTRY_AUTH_ID"),
    ):
        validate_identifier(value, label)
    client.pods()
    client.registry(registry_id)
    emit(
        "doctor-complete",
        api="rest-v1",
        template_name=spec.name,
        image=spec.image,
        ssh_required=False,
        lifecycle="create/delete",
    )


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE_PATH)
    cli.add_argument("--account-id", default=os.environ.get("TARGET_ACCOUNT_ID", ""))
    cli.add_argument("--bucket", default=os.environ.get("SLLM_MODEL_BUCKET", ""))
    cli.add_argument(
        "--profile", default=os.environ.get("AWS_PROFILE", "skn30-session")
    )
    cli.add_argument("--region", default=os.environ.get("AWS_REGION", DEFAULT_REGION))
    cli.add_argument(
        "--project", default=os.environ.get("PROJECT_NAME", "skn30-final-3team")
    )
    cli.add_argument(
        "--endpoint-parameter",
        default=os.environ.get(
            "AI_VLLM_ENDPOINT_PARAMETER",
            "/skn30-final-3team-dev/ai/AI_VLLM_ENDPOINT_SET",
        ),
    )
    cli.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    commands = cli.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")
    create = commands.add_parser("pod-create")
    create.add_argument("--release-id", required=True)
    create.add_argument("--gpu-id", required=True)
    create.add_argument("--apply", action="store_true")
    commands.add_parser("pod-status")
    commands.add_parser("pod-smoke")
    delete = commands.add_parser("pod-delete")
    delete.add_argument("--pod-id", required=True)
    delete.add_argument("--workloads-stopped-confirmed", action="store_true")
    delete.add_argument("--apply", action="store_true")
    reconcile = commands.add_parser("pod-reconcile")
    reconcile.add_argument("--apply", action="store_true")
    reconcile.add_argument("--endpoint-offline-confirmed", action="store_true")
    return cli


def main() -> int:
    args = parser().parse_args()
    try:
        operational = aws_operational_values(
            account_id=args.account_id,
            profile=args.profile,
            region=args.region,
            project=args.project,
        )
        spec = replace(
            load_template_spec(args.template, allow_placeholder=True),
            image=operational.image,
        )
        runpod = RunpodApi(operational.runpod_api_key)
        template_id = operational.template_id
        registry_id = operational.registry_id
        if args.command == "doctor":
            doctor(
                runpod,
                spec,
                template_id=template_id,
                registry_id=registry_id,
            )
            return 0
        if not args.bucket:
            raise ToolError("--bucket or SLLM_MODEL_BUCKET is required")
        template_id = validate_identifier(template_id, "RUNPOD_TEMPLATE_ID")
        aws = AwsOperations(
            artifact.AwsCli(profile=args.profile, region=args.region),
            bucket=args.bucket,
            parameter_name=args.endpoint_parameter,
            project=args.project,
        )
        if args.command == "pod-smoke":
            aws.smoke()
            emit("pod-smoke-complete")
            return 0
        controller = Controller(runpod, aws, spec, template_id, args.timeout_seconds)
        if args.command == "pod-create":
            controller.create(
                release_id=args.release_id,
                gpu_id=args.gpu_id,
                terminate_after=None,
                apply=args.apply,
                keys=operational.f2_keys,
            )
        elif args.command == "pod-status":
            controller.status(operational.f2_keys)
        elif args.command == "pod-delete":
            controller.delete(
                pod_id=args.pod_id,
                confirmed=args.workloads_stopped_confirmed,
                apply=args.apply,
            )
        else:
            controller.reconcile(
                keys=operational.f2_keys,
                apply=args.apply,
                endpoint_offline_confirmed=args.endpoint_offline_confirmed,
            )
        return 0
    except (ToolError, artifact.ToolError) as error:
        emit("error", message=redact_text(str(error))[:1000])
        return 2
    except KeyboardInterrupt:
        emit("error", message="interrupted; run pod-status before retrying")
        return 130


if __name__ == "__main__":
    sys.exit(main())
