"""Review and reconcile existing RunPod Templates without creating credentials.

Plans contain hashes and redacted diffs, never provider response bodies. RunPod's
PATCH API has no compare-and-swap contract: operators must run these commands
serially; we re-read immediately before writing and validate again afterwards.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import manage_runpod_control as control

INFRA = Path(__file__).resolve().parents[1]
FIELDS = (
    "imageName",
    "name",
    "containerDiskInGb",
    "containerRegistryAuthId",
    "dockerEntrypoint",
    "dockerStartCmd",
    "env",
    "isPublic",
    "isServerless",
    "ports",
    "volumeInGb",
    "volumeMountPath",
)
ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
SECRET_REF = re.compile(r"\{\{ RUNPOD_SECRET_[A-Z0-9_]+ \}\}\Z")


def fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _normalized(template: dict) -> dict:
    result = {field: template.get(field) for field in FIELDS}
    for field, default in (
        ("dockerEntrypoint", []),
        ("isPublic", False),
        ("isServerless", False),
        ("volumeInGb", 0),
    ):
        if result[field] is None:
            result[field] = default
    if isinstance(result["ports"], list):
        result["ports"] = sorted(result["ports"])
    return result


def _display(field: str, value: Any) -> Any:
    """Untrusted actual values cannot smuggle tokens into the reviewed plan."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if field == "imageName":
        return (
            value
            if isinstance(value, str) and control.IMAGE_PATTERN.fullmatch(value)
            else "<redacted>"
        )
    if field == "env" and isinstance(value, dict):
        return {
            key if re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", key) else "<redacted-key>": (
                item
                if isinstance(item, str) and SECRET_REF.fullmatch(item)
                else {"configured": True, "sha256": fingerprint(item)}
            )
            for key, item in value.items()
        }
    if field in {"dockerStartCmd", "dockerEntrypoint"} and isinstance(value, list):
        public_arguments = {
            "python",
            "python3",
            "/opt/f2-runtime/scripts/supervisor.py",
            "/opt/general/general_runtime.py",
        }
        if all(isinstance(item, str) and item in public_arguments for item in value):
            return value
    if field == "ports" and isinstance(value, list):
        return [
            item
            if isinstance(item, str) and re.fullmatch(r"\d+/(http|tcp)", item)
            else "<redacted>"
            for item in value
        ]
    if (
        field in {"name", "containerRegistryAuthId"}
        and isinstance(value, str)
        and ID.fullmatch(value)
    ):
        return value
    # Commands and arbitrary strings can contain credentials, even without URLs.
    return {"configured": True, "sha256": fingerprint(value)}


class TemplateReconciler:
    def __init__(self, serving: Any, *, template_paths: dict[str, Path] | None = None):
        self.serving = serving
        self.paths = template_paths or {
            "f2": INFRA / "runpod/template.json",
            "general": INFRA / "serving/general-template.json",
        }

    def _context(self, workload: str, spec: dict) -> tuple:
        if workload not in {"f2", "general"} or spec.get("cloud") != "runpod":
            raise control.ToolError(
                "Template reconciliation requires a selected RunPod workload"
            )
        image = spec.get("image", "")
        if not isinstance(image, str) or not control.IMAGE_PATTERN.fullmatch(image):
            raise control.ToolError("selection requires a pinned workflow image")
        settings = self.serving.settings
        aws = control.AwsStore(
            control.Settings(
                account_id=settings.account_id,
                profile=settings.profile,
                region=settings.region,
                project=settings.project,
                workload=workload,
            ),
            self.serving.session,
        )
        aws.verify_identity()
        registration = aws.control()
        template_id, registry_id = (
            registration.get("template_id"),
            registration.get("registry_auth_id"),
        )
        if any(
            not isinstance(item, str) or not ID.fullmatch(item)
            for item in (template_id, registry_id)
        ):
            raise control.ToolError(
                "register existing Console Template and registry IDs before starting"
            )
        _, secret_version = control.load_ai_secret(aws)
        _, operator_version = aws.secret_value(aws.settings.secrets["operator"])
        api = self.serving.runpod()
        managed_name = (
            control.SHARED_POD_NAME if workload == "f2" else "skn30-general-serving-dev"
        )
        pods = [
            {
                "id": pod.get("id"),
                "name": pod.get("name"),
                "template_id": pod.get("templateId", pod.get("template_id")),
                "image": pod.get("imageName"),
                "status": pod.get("desiredStatus"),
                "env": pod.get("env"),
            }
            for pod in api.pods()
            if pod.get("templateId", pod.get("template_id")) == template_id
            or pod.get("name") == managed_name
        ]
        registry = api.registry(registry_id)
        if control.resource_id(registry, "RunPod registry") != registry_id:
            raise control.ToolError("RunPod registry ID mismatch")
        actual = api.template(template_id)
        if control.resource_id(actual, "RunPod Template") != template_id:
            raise control.ToolError("RunPod Template ID mismatch")
        try:
            source = control.as_object(
                json.loads(self.paths[workload].read_text()), "repository Template"
            )
        except (OSError, json.JSONDecodeError):
            raise control.ToolError("repository Template is unreadable") from None
        if image.split("@", 1)[0] != str(source.get("image", "")).split("@", 1)[0]:
            raise control.ToolError(
                "selection image must belong to the workload workflow repository"
            )
        expected = control.template_payload(source, image, registry_id, source["name"])
        return (
            aws,
            api,
            registration,
            actual,
            expected,
            {
                "registration": registration,
                "template": actual,
                "expected": expected,
                "registry": registry,
                "endpoint": aws.endpoint(),
                "pods": sorted(pods, key=lambda pod: str(pod["id"])),
                "provider_secret_version": secret_version,
                "operator_secret_version": operator_version,
            },
        )

    def _review(self, workload: str, spec: dict, context: tuple) -> dict:
        _, _, registration, actual, expected, snapshot = context
        before, after = _normalized(actual), _normalized(expected)
        record = {
            "schema_version": 2,
            "status": "ready",
            "image": spec["image"],
            "template_id": registration["template_id"],
            "registry_auth_id": registration["registry_auth_id"],
        }
        result = {
            "workload": workload,
            "template_id": record["template_id"],
            "registry_id": record["registry_auth_id"],
            "image": spec["image"],
            "snapshot_hash": fingerprint(snapshot),
            "changes": [
                {
                    "field": field,
                    "before": _display(field, before[field]),
                    "after": _display(field, after[field]),
                }
                for field in FIELDS
                if before[field] != after[field]
            ],
            "registration_changed": any(
                registration.get(key) != value for key, value in record.items()
            )
            or bool(set(registration) - set(record) - {"updated_at"}),
        }
        endpoint, pods = snapshot["endpoint"], snapshot["pods"]
        result["read_only_resume"] = False
        if endpoint.get("status") != "offline" or pods:
            if (
                not result["changes"]
                and not result["registration_changed"]
                and self._can_resume(
                    workload, spec, endpoint, pods, record["template_id"]
                )
            ):
                result["read_only_resume"] = True
            elif endpoint.get("status") != "offline":
                raise control.ToolError(
                    "Template changes require an offline endpoint; only an unchanged matching managed Pod can resume"
                )
            else:
                raise control.ToolError(
                    "Template is still referenced by a Pod; stop or remove that Pod first"
                )
        return result

    @staticmethod
    def _can_resume(
        workload: str, spec: dict, endpoint: dict, pods: list, template_id: str
    ) -> bool:
        if (
            endpoint.get("status") != "active"
            or endpoint.get("cloud", "runpod") != "runpod"
            or len(pods) != 1
        ):
            return False
        pod = pods[0]
        expected_name = (
            control.SHARED_POD_NAME if workload == "f2" else "skn30-general-serving-dev"
        )
        endpoint_id = (
            endpoint.get("pod_id") if workload == "f2" else endpoint.get("resource_id")
        )
        if not (
            pod["id"]
            and pod["id"] == endpoint_id
            and pod["name"] == expected_name
            and pod["template_id"] == template_id
            and pod["image"] == spec["image"]
            and pod["status"] == "RUNNING"
        ):
            return False
        if workload == "f2" and spec.get("release_id"):
            return endpoint.get("sllm_release_id") == spec["release_id"]
        if workload == "general" and spec.get("model_profile"):
            return endpoint.get("model_profile") == spec["model_profile"]
        return True

    def plan(self, workload: str, spec: dict) -> dict:
        return self._review(workload, spec, self._context(workload, spec))

    def apply(self, reviewed_plan: dict, spec: dict) -> dict:
        workload = reviewed_plan.get("workload")
        context = self._context(workload, spec)
        if self._review(workload, spec, context) != reviewed_plan:
            raise control.ToolError(
                "RunPod Template plan is stale; review a new start plan"
            )
        aws, api, registration, _, expected, _ = context
        if reviewed_plan["read_only_resume"]:
            # Prepared GPUs survive app-deploy. Revalidate the reviewed snapshot
            # above, but never PATCH or invoke Registrar against an active Pod.
            return {
                key: value for key, value in registration.items() if key != "updated_at"
            }
        template_id = registration["template_id"]
        if reviewed_plan["changes"]:
            # Patch only fields reviewed above; preserve server-owned metadata.
            api.request(
                "PATCH",
                f"/templates/{template_id}",
                {
                    change["field"]: expected[change["field"]]
                    for change in reviewed_plan["changes"]
                },
            )
        actual = api.template(template_id)
        if control.resource_id(actual, "RunPod Template") != template_id:
            raise control.ToolError("RunPod Template ID changed during reconciliation")
        control.validate_template(actual, expected)
        if _normalized(actual) != _normalized(expected):
            raise control.ToolError("RunPod Template changed during reconciliation")
        # Registrar rechecks account, secrets, endpoint, registry, and Template.
        # A failed PATCH/verification must never promote the SSM registration.
        if any(
            pod.get("templateId", pod.get("template_id")) == template_id
            for pod in api.pods()
        ):
            raise control.ToolError(
                "a Pod began using the Template; registration was not updated"
            )
        if aws.control() != registration:
            raise control.ToolError(
                "SSM registration changed during reconciliation; review a new start plan"
            )
        return control.Registrar(aws, self.paths[workload]).register(
            spec["image"],
            template_id,
            registration["registry_auth_id"],
            apply=True,
        )
