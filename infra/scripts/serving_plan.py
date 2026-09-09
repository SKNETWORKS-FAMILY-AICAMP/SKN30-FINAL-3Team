"""Reviewed shared-dev start plan bound to desired state and Terraform inputs."""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

import plan_guard
from env_doctor import private_write
from manage_dev_power import ToolError, emit
from model_profiles import load_profile
from serving_selection import confirm, fingerprint
from serving_templates import TemplateReconciler

INFRA = Path(__file__).resolve().parents[1]
ROOT = INFRA / "environments/dev"


def run(command: list[str], *, env: dict | None = None) -> str:
    result = subprocess.run(
        command, env=env, text=True, capture_output=True, check=False
    )
    if result.returncode:
        raise ToolError(
            f"{Path(command[0]).name} {command[1]} failed; inspect local configuration (raw output withheld)"
        )
    return result.stdout


def desired_inputs(selection: dict, retained: dict, existing: set[str]) -> dict:
    profiles = {
        name: {"root_volume_gb": 160, **value} for name, value in retained.items()
    }
    if set(profiles) - {"f2", "general"} or any(
        set(p) - {"ami_id", "image", "root_volume_gb"} for p in profiles.values()
    ):
        raise ToolError("unsupported GPU profile fields; use gpu-profiles-import")
    capacity = set(existing)
    if existing - profiles.keys():
        raise ToolError(
            "retained AWS GPU profiles are missing; import their reviewed profiles before planning"
        )
    for name in ("f2", "general"):
        spec = selection[name]
        if spec and spec["cloud"] == "aws":
            if name not in profiles:
                raise ToolError(
                    "AWS requires a reviewed AMI profile: gpu-profiles-import before dev-start"
                )
            profiles[name]["image"] = spec["image"]
            capacity.add(name)
    if not selection.get("general"):
        raise ToolError("ai-select must select the shared dev general model")
    return {
        "gpu_profiles": profiles,
        "gpu_provisioned_workloads": sorted(capacity),
        "general_model_selection": {
            "provider": "vllm",
            "model": load_profile(selection["general"]["model_profile"])["model"],
            "aws_region": None,
        },
        "dev_edge_enabled": True,
        "dev_gpu_enabled": True,
        "app_deployment_mode": "maintenance",
    }


def validate_intent(payload: dict, expected: dict) -> list[dict]:
    variables = payload.get("variables", {})
    for name, value in expected.items():
        if variables.get(name, {}).get("value") != value:
            raise ToolError(
                f"Terraform planned {name} differs from shared selection; remove conflicting inputs"
            )
    result = []
    for resource in payload.get("resource_changes", []):
        actions = resource["change"]["actions"]
        if actions != ["no-op"]:
            result.append({"address": resource["address"], "actions": actions})
    return result


class StartPlan:
    def __init__(self, serving, *, infra: Path = INFRA):
        self.serving, self.infra = serving, infra
        self.root = infra / "environments/dev"
        self.path = self.root / "dev-serving.tfplan"
        self.metadata = self.root / "dev-serving.lifecycle.plan-meta.json"
        self.templates = TemplateReconciler(serving)
        # Terraform's provider owns AssumeRole. Reusing the SDK's already-assumed
        # session would attempt a second role assumption and fail the trust policy.
        self.env = {
            key: value
            for key, value in os.environ.items()
            if key
            not in {
                "AWS_ACCESS_KEY_ID",
                "AWS_SECRET_ACCESS_KEY",
                "AWS_SESSION_TOKEN",
                "AWS_SECURITY_TOKEN",
            }
        }
        self.env.update(
            AWS_PROFILE=serving.settings.profile, AWS_REGION=serving.settings.region
        )
        self.expected = None
        self.approved = False

    def terraform(self, *args: str) -> str:
        return run(["terraform", f"-chdir={self.root}", *args], env=self.env)

    def inventory(self) -> dict:
        return {
            name: [
                {"id": i["InstanceId"], "state": i["State"]["Name"]}
                for i in self.serving.instances(name)
            ]
            for name in ("f2", "general")
        }

    def build(self, *, hours: float = 2, rates: dict | None = None) -> dict:
        if not math.isfinite(hours) or hours <= 0:
            raise ToolError("planned hours must be positive and finite")
        # Keep the login-profile guard even though Terraform itself uses assumed-role credentials.
        preflight_env = {
            **os.environ,
            "TARGET_ACCOUNT_ID": self.serving.settings.account_id,
            "AWS_PROFILE": self.serving.settings.profile,
            "AWS_REGION": self.serving.settings.region,
        }
        run(["bash", str(self.infra / "scripts/preflight.sh")], env=preflight_env)
        self.serving.no_deployment()
        selection = self.serving.selection_document()
        if not all(selection[name] for name in ("f2", "general")):
            raise ToolError("select both F2 and general with ai-select first")
        group = self.serving.power.describe_asg()
        if group.get("DesiredCapacity", 0):
            # Maintenance host prepared by this lifecycle is an allowed resume point.
            self.serving.require_app_stopped()
        before = self.inventory()
        for name in ("f2", "general"):
            if self.serving.endpoint(name).get("status") == "active":
                self.serving.require_app_stopped()
        for name in ("f2", "general"):
            if name == "f2":
                self.serving.validate_release(selection[name])
        changes = [
            self.templates.plan(name, selection[name])
            for name in ("f2", "general")
            if selection[name]["cloud"] == "runpod"
        ]
        profile_file = self.root / "gpu-profiles.auto.tfvars.json"
        if profile_file.is_symlink():
            raise ToolError("GPU profile input must not be a symlink")
        retained = (
            json.loads(profile_file.read_text())["gpu_profiles"]
            if profile_file.exists()
            else {}
        )
        expected = desired_inputs(
            selection, retained, {name for name, values in before.items() if values}
        )
        generated = self.root / "serving-selection.auto.tfvars.json"
        private_write(generated, json.dumps(expected, indent=2) + "\n")
        self.expected = expected
        self.terraform("fmt", "-check")
        self.terraform("validate")
        self.terraform(
            "plan",
            "-input=false",
            "-var-file=dev.tfvars",
            "-var-file=" + generated.name,
            "-out=" + self.path.name,
        )
        payload = json.loads(self.terraform("show", "-json", self.path.name))
        resources = validate_intent(payload, expected)
        # Reuse the exact first-deploy deployment-target guard on every start.
        plan_guard.validate_first_deploy(payload)
        plan_guard.seal(self.infra, self.path)
        rates = rates or {}
        cost = {
            name: {
                "hourly_usd": rates.get(name),
                "hours": hours,
                "estimated_compute_usd": round(rates[name] * hours, 4)
                if name in rates
                else None,
                "hardware_profile": selection[name]["hardware_profile"],
            }
            for name in ("f2", "general")
        }
        data = {
            "schema_version": 1,
            "created_at": time.time(),
            "selection": selection,
            "selection_hash": fingerprint(selection),
            "inventory": before,
            "templates": changes,
            "terraform_changes": resources,
            "cost": cost,
            "terraform_inputs": expected,
        }
        private_write(self.metadata, json.dumps(data, indent=2) + "\n")
        emit(
            "dev-start-plan",
            selection=selection,
            terraform_changes=resources,
            templates=changes,
            cost=cost,
            billing="GPU billed while idle; AWS EBS/IPv4, RunPod disk, app/RDS/edge extra; hours is an estimate, not an automatic shutdown timer",
            missing_rates="supply --hourly-usd f2=RATE --hourly-usd general=RATE from current provider quote before applying",
            saved_plan=str(self.path),
            applied=False,
        )
        return data

    def check(self, data: dict, *, templates: bool = True) -> None:
        if not 0 <= time.time() - data["created_at"] <= plan_guard.MAX_AGE:
            raise ToolError("start plan expired; review a new plan")
        plan_guard.check(self.infra, self.path)
        if fingerprint(self.serving.selection_document()) != data["selection_hash"]:
            raise ToolError("shared selection changed; review a new start plan")
        if templates:
            for expected in data["templates"]:
                actual = self.templates.plan(
                    expected["workload"], data["selection"][expected["workload"]]
                )
                if actual != expected:
                    raise ToolError(
                        "RunPod registration/template changed; review a new start plan"
                    )

    def apply(self, data: dict, *, confirm_fn=confirm) -> None:
        for name, estimate in data["cost"].items():
            if estimate["hourly_usd"] is None:
                if not sys.stdin.isatty():
                    raise ToolError(
                        f"current {name} hourly quote required; use --hourly-usd {name}=RATE"
                    )
                value = float(
                    input(
                        f"{name} ({estimate['hardware_profile']}) current provider hourly quote in USD: "
                    )
                )
                if not math.isfinite(value) or value <= 0:
                    raise ToolError("hourly quote must be positive and finite")
                estimate["hourly_usd"] = value
                estimate["estimated_compute_usd"] = round(value * estimate["hours"], 4)
        emit(
            "dev-start-cost-review",
            cost=data["cost"],
            extra="storage/app/RDS/edge/IPv4 separate; no automatic timer",
        )
        private_write(self.metadata, json.dumps(data, indent=2) + "\n")
        confirm_fn("Apply this Terraform/Template plan and start billed dev resources?")
        self.check(data)
        if self.inventory() != data["inventory"]:
            raise ToolError("AWS GPU inventory changed; review the start plan again")
        self.serving.no_deployment()
        # Recheck app quiescence immediately before mutation, not just at preview.
        if self.serving.power.describe_asg().get("DesiredCapacity", 0):
            self.serving.require_app_stopped()
        self.approved = True
        if data["terraform_changes"]:
            self.terraform("apply", "-input=false", self.path.name)
        self.check(data)
        for expected in data["templates"]:
            self.templates.apply(expected, data["selection"][expected["workload"]])
        self.check(data, templates=False)
        # Drift is tested against the exact generated selection inputs.
        self.terraform(
            "plan",
            "-input=false",
            "-var-file=dev.tfvars",
            "-var-file=serving-selection.auto.tfvars.json",
            "-out=dev-serving-drift.tfplan",
        )
        drift = json.loads(self.terraform("show", "-json", "dev-serving-drift.tfplan"))
        if validate_intent(drift, data["terraform_inputs"]):
            raise ToolError("post-apply Terraform drift remains; maintenance retained")
