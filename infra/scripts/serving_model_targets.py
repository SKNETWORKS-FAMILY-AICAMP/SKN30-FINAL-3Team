"""Bridge maintenance-host operations to the Backend-owned model-selection CLI."""

from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import Path

from manage_dev_power import ToolError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "serving"))
from model_profiles import load_profile

SCRIPT = "/opt/brokerage/revision/scripts/serving_maintenance.sh"
CAPABILITIES = ("POSITION_CARD", "BROKERAGE_JUDGMENT", "CHATBOT")


class AppDeploymentRequired(ToolError):
    """A maintenance host cannot provide the required Backend CLI until app-deploy."""


class ModelTargets:
    def __init__(self, serving):
        self.serving = serving

    def require_host(self) -> str:
        instance = self.serving.app_id()
        if not instance:
            raise AppDeploymentRequired(
                "maintenance host unavailable; run dev-prepare-app then app-deploy"
            )
        supported = self.serving.command(
            instance,
            f"if test -s /opt/brokerage/revision/backend-image.env && "
            f"test -x {SCRIPT} && grep -q model-targets-check {SCRIPT}; "
            "then echo supported; else echo app-deploy-required; fi",
        )
        if supported.strip() != "supported":
            raise AppDeploymentRequired(
                "deploy the new Backend revision with app-deploy, then retry dev-start"
            )
        result = self.serving.command(
            instance, f"{SCRIPT} model-targets-check", timeout=360
        )
        if result.strip().splitlines()[-1:] != ["model-targets-ready"]:
            raise AppDeploymentRequired(
                "Backend image lacks model-targets support; run app-deploy then dev-start"
            )
        return instance

    @staticmethod
    def _arguments(selection: dict) -> list[str]:
        profile_name = selection.get("general", {}).get("model_profile")
        if not profile_name:
            raise ToolError("explicit general model profile required")
        profile = load_profile(profile_name)
        return ["--provider", "vllm", "--model", profile["model"]]

    def _call(self, selection: dict, arguments: list[str]) -> dict:
        instance = self.require_host()
        self.serving.no_deployment()
        command = shlex.join(
            [SCRIPT, "model-targets", *self._arguments(selection), *arguments]
        )
        output = self.serving.command(instance, command, timeout=360)
        try:
            result = json.loads(output.strip().splitlines()[-1])
            if not isinstance(result, dict):
                raise TypeError
            return result
        except (ValueError, TypeError, IndexError):
            raise ToolError(
                "invalid or truncated model-targets response; no success recorded"
            ) from None

    def preview(self, selection: dict) -> dict:
        return self._call(selection, ["--list-targets"])

    @staticmethod
    def choose(preview: dict, input_fn=input) -> list[str]:
        """Print all current targets; require explicit IDs and a second before/after approval."""
        desired = preview["desired"]
        print(
            "DB desired model: "
            + json.dumps(desired, ensure_ascii=False, sort_keys=True)
        )
        known = {}
        incompatible = set()
        for row in preview["targets"]:
            key = f"{row['brokerage_id']}:{row['capability']}"
            known[key] = row
            if row["current"] and not row["compatible"]:
                incompatible.add(key)
            print(
                json.dumps(
                    {
                        "target": key,
                        "current": row["current"],
                        "compatible": row["compatible"],
                        "pending_work": row["pending_work"],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        if any(row["pending_work"] for row in preview["targets"]):
            raise ToolError(
                "queued/in-progress requests exist; settle requests before model changes/start"
            )
        raw = input_fn(
            "Change targets (comma-separated BROKERAGE_ID:CAPABILITY; empty keeps all): "
        )
        selected = sorted({part.strip() for part in raw.split(",") if part.strip()})
        if not set(selected) <= known.keys():
            raise ToolError(
                "unknown DB target; choose explicit IDs from the displayed list"
            )
        remaining = incompatible - set(selected)
        if remaining:
            raise ToolError(
                "incompatible active configurations remain: "
                + ", ".join(sorted(remaining))
            )
        for key in selected:
            print(
                json.dumps(
                    {"target": key, "before": known[key]["current"], "after": desired},
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        if (
            selected
            and input_fn(
                "Confirm only these DB changes after model readiness [yes/no]: "
            ).strip()
            != "yes"
        ):
            raise ToolError("DB target changes were not confirmed")
        return selected

    def apply(self, selection: dict, targets: list[str], snapshot: str) -> dict:
        if not re.fullmatch(r"[0-9a-f]{64}", snapshot):
            raise ToolError("reviewed DB snapshot required")
        arguments = ["--apply", "--workloads-stopped", "--expected-snapshot", snapshot]
        for target in targets:
            identifier, separator, capability = target.partition(":")
            if (
                not separator
                or not identifier.isdigit()
                or int(identifier) < 1
                or capability not in CAPABILITIES
            ):
                raise ToolError("invalid explicit DB target")
            arguments.extend(["--target", target])
        return self._call(selection, arguments)

    def require_compatible(self, selection: dict) -> dict:
        result = self.preview(selection)
        incompatible = [
            f"{row['brokerage_id']}:{row['capability']}"
            for row in result["targets"]
            if row["current"] and not row["compatible"]
        ]
        if incompatible:
            raise ToolError(
                "incompatible active DB configurations block app start: "
                + ", ".join(incompatible)
            )
        if any(row["pending_work"] for row in result["targets"]):
            raise ToolError(
                "queued/in-progress requests block model transition/app start"
            )
        return result
