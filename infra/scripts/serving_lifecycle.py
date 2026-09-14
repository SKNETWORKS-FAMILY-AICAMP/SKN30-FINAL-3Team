"""One reviewed start transaction, with attempt-owned GPU cleanup on failure."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from botocore.exceptions import BotoCoreError, ClientError
from manage_dev_power import ToolError, emit
from serving_deployment import require_general_selection, require_maintenance_deployment
from serving_model_targets import AppDeploymentRequired, ModelTargets
from serving_plan import StartPlan
from serving_selection import WORKLOADS, fingerprint


class Lifecycle:
    def __init__(self, serving):
        self.serving = serving
        self.attempt_id = str(uuid4())
        serving.attempt_id = self.attempt_id
        self.application_revision = None
        self.receipts = []
        self.stage = "planning"
        self.plan = StartPlan(serving)
        self.data = None

    def record(self, state: str) -> None:
        if self.data is None:
            return
        value = {
            "schema_version": 1,
            "selection_id": self.data["selection"]["selection_id"],
            "selection_hash": self.data["selection_hash"],
            "stage": self.stage,
            "status": state,
            "updated_at": datetime.now(UTC).isoformat(),
            "attempt_resources": self.receipts,
            "attempt_id": self.attempt_id,
            "application_revision": self.application_revision,
        }
        try:
            # Terraform creates the container; do not create it through the SDK.
            self.serving.read("serving/APPLIED")
            self.serving.write("serving/APPLIED", value)
        except (BotoCoreError, ClientError):
            emit(
                "apply-record-unavailable",
                stage=self.stage,
                status=state,
                next="inspect dev-status; apply the reviewed serving/APPLIED Terraform resource",
            )

    def checkpoint(self, stage: str) -> None:
        if (
            fingerprint(self.serving.selection_document())
            != self.data["selection_hash"]
        ):
            raise ToolError(
                "shared selection changed during start; stop and review a new plan"
            )
        self.stage = stage
        self.record("applying")

    def collect_terraform_resources(self) -> None:
        if not self.data:
            return
        before = {
            item["id"] for items in self.data["inventory"].values() for item in items
        }
        owned = {r["resource_id"] for r in self.receipts}
        for name in WORKLOADS:
            for item in self.serving.instances(name):
                if item["InstanceId"] not in before | owned:
                    self.receipts.append(
                        {
                            "cloud": "aws",
                            "resource_id": item["InstanceId"],
                            "workload": name,
                        }
                    )

    def cleanup(self) -> None:
        candidate = getattr(self.serving, "started_candidate", None)
        if isinstance(candidate, dict) and candidate.get("resource_id") not in {
            r["resource_id"] for r in self.receipts
        }:
            self.receipts.append(candidate)
        try:
            # A POST may succeed remotely before its response is lost. Only adopt
            # Pods carrying this exact attempt token, never name matches alone.
            if any(
                self.data["selection"][name]["cloud"] == "runpod" for name in WORKLOADS
            ):
                client = self.serving.runpod()
                for pod in self.serving.managed_pods():
                    details = client.pod(pod["id"])
                    if details.get("env", {}).get(
                        "SERVING_ATTEMPT_ID"
                    ) == self.attempt_id and pod["id"] not in {
                        r["resource_id"] for r in self.receipts
                    }:
                        self.receipts.append(
                            {"cloud": "runpod", "resource_id": pod["id"]}
                        )
        except (
            RuntimeError,
            BotoCoreError,
            ClientError,
            OSError,
            ValueError,
            KeyError,
            TypeError,
        ):
            emit("runpod-attempt-inventory-unavailable", attempt_id=self.attempt_id)
        try:
            self.collect_terraform_resources()
        except (
            RuntimeError,
            BotoCoreError,
            ClientError,
            OSError,
            ValueError,
            KeyError,
        ):
            emit("cleanup-inventory-unavailable", next="dev-status; dev-stop")
        # Remove routes first; never leave a failed attempt's endpoint advertised ready.
        for name in WORKLOADS:
            try:
                self.serving.activate(name, {}, None)
            except (
                RuntimeError,
                BotoCoreError,
                ClientError,
                OSError,
                ValueError,
                KeyError,
            ):
                emit("endpoint-cleanup-incomplete", workload=name)
        for receipt in self.receipts:
            try:
                if receipt["cloud"] == "aws":
                    self.serving.ec2.stop_instances(
                        InstanceIds=[receipt["resource_id"]]
                    )
                    self.serving.ec2.get_waiter("instance_stopped").wait(
                        InstanceIds=[receipt["resource_id"]]
                    )
                else:
                    self.serving.runpod().delete(receipt["resource_id"])
            except (
                RuntimeError,
                BotoCoreError,
                ClientError,
                OSError,
                ValueError,
                KeyError,
            ):
                emit("gpu-cleanup-incomplete", **receipt)
        emit(
            "dev-start-incomplete",
            stage=self.stage,
            remaining="RDS/maintenance host and AWS EBS may remain billable; existing unrelated resources preserved",
            next="dev-status; dev-stop (deep removal requires its reviewed plan)",
        )

    def endpoints(self) -> dict:
        deployments = {}
        for name in WORKLOADS:
            self.checkpoint("prepare-" + name)
            spec = self.data["selection"][name]
            deployment = self.serving.prepare(name, spec)
            receipt = self.serving.started_candidate
            if receipt and receipt["resource_id"] not in {
                r["resource_id"] for r in self.receipts
            }:
                self.receipts.append({**receipt, "workload": name})
            deployments[name] = deployment
            self.checkpoint("register-" + name)
            self.serving.activate(name, spec, deployment)
        return deployments

    def run(self, *, prepare_only=False, apply=False, hours=2, rates=None) -> None:
        self.data = self.plan.build(hours=hours, rates=rates)
        if not apply:
            return
        try:
            previous = self.serving.read("serving/APPLIED")
            if isinstance(previous, dict):
                self.application_revision = previous.get("application_revision")
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") != "ParameterNotFound":
                raise
        # Snapshot before any billed changes; partial Terraform apply is cleaned too.
        try:
            self.stage = "infrastructure"
            self.plan.apply(self.data)
            self.collect_terraform_resources()
            selected = self.data["selection"]
            require_maintenance_deployment(self.serving.session, self.serving.settings)
            require_general_selection(self.serving.ssm, self.serving.prefix, selected)
            self.checkpoint("maintenance-host")
            self.serving.power.start()
            instance = self.serving.app_id()
            self.serving.command(
                instance,
                "install -d -m 0700 /opt/brokerage; touch /opt/brokerage/serving-maintenance",
            )
            targets = ModelTargets(self.serving)
            try:
                targets.require_host()
            except AppDeploymentRequired:
                if not prepare_only:
                    from serving_app_revision import restore

                    if not restore(self.serving, self.application_revision):
                        raise AppDeploymentRequired(
                            "first deployment needs dev-prepare-app → app-deploy → dev-start"
                        ) from None
                    targets.require_host()
                else:
                    self.endpoints()
                    self.stage = "awaiting-app-deploy"
                    self.record("prepared")
                    emit(
                        "deployment-host-ready",
                        next="app-deploy → dev-start",
                        application_verified=False,
                        billing="prepared GPUs and RDS/host remain running; dev-stop to abandon",
                    )
                    return
            self.serving.app("stop")
            self.checkpoint("model-target-preview")
            preview = targets.preview(selected)
            chosen = targets.choose(preview)
            self.endpoints()
            self.checkpoint("model-target-apply")
            targets.apply(selected, chosen, preview["snapshot"])
            targets.require_compatible(selected)
            if prepare_only:
                self.stage = "awaiting-app-deploy"
                self.record("prepared")
                emit(
                    "deployment-host-ready",
                    next="app-deploy → dev-start",
                    application_verified=False,
                )
                return
            self.checkpoint("application-start")
            self.serving.command(instance, "rm -f /opt/brokerage/serving-maintenance")
            self.serving.app("start")
            self.checkpoint("application-verify")
            for name in WORKLOADS:
                self.serving.application_smoke(name)
            from serving_app_revision import capture

            self.application_revision = capture(self.serving)
            self.stage = "complete"
            self.record("applied")
            emit(
                "dev-serving-start-complete",
                selection_id=selected["selection_id"],
                next="dev-verify; dev-stop when finished",
            )
        except BaseException:
            # No cleanup before the operator accepted the plan (no resources were started).
            if self.plan.approved:
                try:
                    instance = self.serving.app_id()
                    if instance:
                        self.serving.command(
                            instance, "touch /opt/brokerage/serving-maintenance"
                        )
                        self.serving.app("stop")
                except (
                    RuntimeError,
                    BotoCoreError,
                    ClientError,
                    OSError,
                    ValueError,
                    KeyError,
                ):
                    emit(
                        "app-maintenance-incomplete",
                        next="inspect app processes before retry",
                    )
                self.cleanup()
                self.record("failed")
            raise
