# /// script
# requires-python = ">=3.13,<3.14"
# dependencies = ["boto3>=1.40,<2"]
# ///
"""Explicit dev serving operations; no daemon, auto-failover, or shadow state store."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import manage_dev_power as power
import manage_runpod as f2
import manage_runpod_control as control
import manage_sllm_artifact as artifact
from botocore.exceptions import BotoCoreError, ClientError

INFRA = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(INFRA / "deploy" / "scripts"))
sys.path.insert(0, str(INFRA / "serving"))
from model_profiles import load_profile
from probe import probe, read_status
from serving_cli import parser
from serving_contract import (
    DEFAULT_GENERAL_PROFILE,
    GENERAL_CUDA_VERSIONS,
    GENERAL_KEY,
    POD_NAME,
    WORKLOADS,
    endpoint_urls,
)

ToolError = power.ToolError
emit = power.emit


def general_profile(spec: dict) -> dict:
    if not spec.get("model_profile"):
        raise ToolError("explicit general model_profile is required")
    return load_profile(spec["model_profile"])


def general_metadata(spec: dict) -> dict:
    profile = general_profile(spec)
    return {
        "model_profile": spec.get("model_profile", DEFAULT_GENERAL_PROFILE),
        "model": profile["model"],
        "revision": profile["revision"],
        "runtime_image": profile["runtime_image"],
    }


def f2_record(previous: dict, deployment: dict | None, release_id: str | None) -> dict:
    record = {
        "revision": int(previous.get("revision", 0)) + 1,
        "status": "offline",
        "pod_id": None,
        "sllm_release_id": None,
        "sllm_base_url": None,
        "stt_base_url": None,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    if deployment is None:
        return record
    urls = endpoint_urls(
        deployment["cloud"],
        deployment["resource_id"],
        "f2",
        deployment.get("private_ip"),
    )
    record.update(
        status="active",
        sllm_release_id=release_id,
        sllm_base_url=urls[0],
        stt_base_url=urls[1],
    )
    if deployment["cloud"] == "runpod":
        record["pod_id"] = deployment["resource_id"]
    else:
        record.update(
            schema_version=2,
            cloud="aws",
            instance_id=deployment["resource_id"],
            private_ip=deployment["private_ip"],
        )
    return record


class Serving:
    def __init__(self, session: Any, settings: power.Settings):
        self.session, self.settings = session, settings
        self.prefix = settings.name_prefix
        self.ssm = session.client("ssm")
        self.ec2 = session.client("ec2")
        self.secrets = session.client("secretsmanager")
        self.power = power.PowerController(session, settings)

    def read(self, suffix: str) -> dict:
        raw = self.ssm.get_parameter(Name=f"/{self.prefix}/{suffix}")["Parameter"][
            "Value"
        ]
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ToolError("invalid serving configuration")
        return value

    def write(self, suffix: str, value: dict) -> None:
        self.ssm.put_parameter(
            Name=f"/{self.prefix}/{suffix}",
            Type="String",
            Value=json.dumps(value),
            Overwrite=True,
        )

    def selection_document(self) -> dict:
        from serving_selection import document

        try:
            raw = self.read("serving/SELECTION")
        except self.ssm.exceptions.ParameterNotFound:
            raw = {"f2": None, "general": None}
        return document(raw)

    def selection(self) -> dict:
        value = self.selection_document()
        return {name: value[name] for name in WORKLOADS}

    def managed_pods(self) -> list[dict]:
        try:
            return [
                pod
                for pod in self.runpod().pods()
                if pod.get("name") in POD_NAME.values()
            ]
        except ClientError as error:
            if (
                error.response.get("Error", {}).get("Code")
                == "ResourceNotFoundException"
            ):
                return []  # AWS-only installations need no RunPod operator Secret.
            raise

    def require_app_stopped(self) -> None:
        instance = self.app_id()
        if not instance:
            return
        self.command(
            instance,
            "test -f /opt/brokerage/serving-maintenance && "
            'test -z "$(docker ps -q --filter label=com.docker.compose.project=brokerage-dev --filter label=com.docker.compose.service=api)" && '
            'test -z "$(docker ps -q --filter label=com.docker.compose.project=brokerage-dev --filter label=com.docker.compose.service=worker)"',
        )

    def secret(self, suffix: str) -> dict:
        return json.loads(
            self.secrets.get_secret_value(SecretId=f"/{self.prefix}/{suffix}")[
                "SecretString"
            ]
        )

    def runpod(self) -> f2.RunpodApi:
        key = self.secrets.get_secret_value(
            SecretId=f"/{self.prefix}/runpod/operator-api-key"
        )["SecretString"]
        return f2.RunpodApi(key)

    def instances(self, workload: str) -> list[dict]:
        response = self.ec2.describe_instances(
            Filters=[
                {"Name": "tag:Project", "Values": [self.settings.project]},
                {"Name": "tag:Environment", "Values": ["dev"]},
                {"Name": "tag:ManagedBy", "Values": ["Terraform"]},
                {"Name": "tag:Name", "Values": [f"{self.prefix}-{workload}-gpu"]},
                {"Name": "tag:ServingWorkload", "Values": [workload]},
                {
                    "Name": "instance-state-name",
                    "Values": ["pending", "running", "stopping", "stopped"],
                },
            ]
        )
        return [
            instance
            for reservation in response["Reservations"]
            for instance in reservation["Instances"]
        ]

    def app_id(self) -> str | None:
        group = self.power.describe_asg()
        ids = [
            item["InstanceId"]
            for item in group.get("Instances", [])
            if item["LifecycleState"] == "InService"
        ]
        if len(ids) > 1:
            raise ToolError("expected at most one dev app instance")
        return ids[0] if ids else None

    def command(self, instance: str, command: str, *, timeout: int = 300) -> str:
        response = self.ssm.send_command(
            InstanceIds=[instance],
            DocumentName="AWS-RunShellScript",
            Parameters={"commands": [command], "executionTimeout": [str(timeout)]},
            TimeoutSeconds=timeout,
            Comment="Reviewed serving operation; no credential values in command",
        )
        command_id = response["Command"]["CommandId"]
        deadline = time.monotonic() + timeout + 30
        while time.monotonic() < deadline:
            try:
                invocation = self.ssm.get_command_invocation(
                    CommandId=command_id, InstanceId=instance
                )
                status = invocation["Status"]
            except self.ssm.exceptions.InvocationDoesNotExist:
                time.sleep(2)
                continue
            if status == "Success":
                return invocation.get("StandardOutputContent", "")
            if status in {"Failed", "Cancelled", "TimedOut", "Cancelling"}:
                raise ToolError(
                    f"SSM operation failed ({status}); command ID {command_id}"
                )
            time.sleep(3)
        raise ToolError(f"SSM operation timed out; inspect command ID {command_id}")

    def app(self, action: str) -> None:
        instance = self.app_id()
        if instance:
            self.command(
                instance,
                f"/opt/brokerage/revision/scripts/serving_maintenance.sh {action}",
                timeout=360,
            )
        elif action == "start":
            raise ToolError("dev app is unavailable; run dev-start")

    def no_deployment(self) -> None:
        client = self.session.client("codedeploy")
        active = client.list_deployments(
            applicationName=f"{self.prefix}-backend",
            deploymentGroupName=f"{self.prefix}-backend",
            includeOnlyStatuses=["Created", "Queued", "InProgress", "Ready", "Baking"],
        )
        if active.get("deployments"):
            raise ToolError("wait for the active application deployment")
        pipelines = self.session.client("codepipeline")
        for page in pipelines.get_paginator("list_pipelines").paginate():
            for pipeline in page["pipelines"]:
                if pipeline["name"].startswith(self.prefix):
                    executions = pipelines.list_pipeline_executions(
                        pipelineName=pipeline["name"], maxResults=1
                    )
                    if any(
                        item["status"] in {"InProgress", "Stopping"}
                        for item in executions.get("pipelineExecutionSummaries", [])
                    ):
                        raise ToolError("wait for the active application pipeline")

    def endpoint(self, workload: str) -> dict:
        suffix = (
            "AI_VLLM_ENDPOINT_SET" if workload == "f2" else "AI_GENERAL_ENDPOINT_SET"
        )
        return self.read(f"ai/{suffix}")

    def activate(self, workload: str, spec: dict, deployment: dict | None) -> None:
        if workload == "f2":
            self.write(
                "ai/AI_VLLM_ENDPOINT_SET",
                f2_record(self.endpoint(workload), deployment, spec.get("release_id")),
            )
        else:
            value = {"status": "offline"}
            if deployment:
                value = {
                    "status": "active",
                    **deployment,
                    **general_metadata(spec),
                    "base_url": endpoint_urls(
                        deployment["cloud"],
                        deployment["resource_id"],
                        workload,
                        deployment.get("private_ip"),
                    )[0],
                }
            self.write("ai/AI_GENERAL_ENDPOINT_SET", value)

    def release(self, spec: dict, *, presign: bool = True) -> tuple[dict, str, str]:
        # Existing publisher validation is reused with an assumed-role subprocess environment.
        credentials = self.session.get_credentials().get_frozen_credentials()
        env = {
            **os.environ,
            "AWS_ACCESS_KEY_ID": credentials.access_key,
            "AWS_SECRET_ACCESS_KEY": credentials.secret_key,
            "AWS_SESSION_TOKEN": credentials.token or "",
        }

        def execute(command):
            return subprocess.run(
                command,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

        client = artifact.AwsCli(executor=execute, region=self.settings.region)
        operations = f2.AwsOperations(
            client,
            bucket=spec["bucket"],
            parameter_name=f"/{self.prefix}/ai/AI_VLLM_ENDPOINT_SET",
            project=self.settings.project,
        )
        manifest, checksum = operations.release(spec["release_id"])
        if (manifest.get("release_stage", "verified") == "dev") != spec.get(
            "allow_dev_release", False
        ):
            raise ToolError(
                "release stage does not match the explicit dev-release choice"
            )
        catalog = json.loads((INFRA / "runpod/releases.json").read_text())["releases"]
        record = next(
            (r for r in catalog if r["release_id"] == spec["release_id"]), None
        )
        if record is None or record["bundle_sha256"] != checksum:
            raise ToolError("S3 release checksum differs from the Git release catalog")
        return (
            manifest,
            checksum,
            operations.presign(spec["release_id"]) if presign else "",
        )

    def validate_release(self, spec: dict) -> None:
        self.release(spec, presign=False)

    def prepare(self, workload: str, spec: dict) -> dict:
        # This is only an in-process cleanup receipt, never durable lifecycle state.
        self.started_candidate = None
        try:
            return self._prepare(workload, spec)
        except (
            ToolError,
            f2.ToolError,
            control.ToolError,
            artifact.ToolError,
            BotoCoreError,
            ClientError,
            OSError,
            ValueError,
            KeyError,
        ):
            candidate = self.started_candidate
            if candidate:
                try:
                    if candidate["cloud"] == "aws":
                        self.ec2.stop_instances(InstanceIds=[candidate["resource_id"]])
                    else:
                        self.runpod().delete(candidate["resource_id"])
                    self.started_candidate = None
                except (BotoCoreError, ClientError, f2.ToolError):
                    emit(
                        "candidate-cleanup-incomplete",
                        resource_id=candidate["resource_id"],
                        action="inspect dev-status; retry dev-stop during maintenance",
                    )
            raise

    def _prepare(self, workload: str, spec: dict) -> dict:
        from selection_catalog import normalize_spec

        spec = normalize_spec(workload, spec)
        if spec["cloud"] == "aws":
            matches = self.instances(workload)
            if len(matches) != 1:
                raise ToolError(
                    "apply a reviewed GPU Terraform plan first; expected one managed instance"
                )
            instance = matches[0]
            iid = instance["InstanceId"]
            tags = {tag["Key"]: tag["Value"] for tag in instance.get("Tags", [])}
            from selection_catalog import load_catalog

            hardware = load_catalog()["profiles"][spec["hardware_profile"]]
            if (
                tags.get("ServingImage") != spec["image"]
                or instance["InstanceType"] != hardware["instance_type"]
            ):
                raise ToolError(
                    "AWS GPU image/type differs from selected catalog profile; review Terraform plan"
                )
            if workload == "f2":
                self.release(spec)
            state = instance["State"]["Name"]
            if state == "stopping":
                self.ec2.get_waiter("instance_stopped").wait(InstanceIds=[iid])
                state = "stopped"
            if state == "stopped":
                self.started_candidate = {"cloud": "aws", "resource_id": iid}
                self.ec2.start_instances(InstanceIds=[iid])
            self.ec2.get_waiter("instance_running").wait(InstanceIds=[iid])
            self.power.wait_for_ssm(iid, time.monotonic() + 600)
            self.command(iid, "cloud-init status --wait >/dev/null", timeout=600)
            payload = shlex.quote(json.dumps(spec))
            self.command(
                iid,
                f"set -eu; umask 077; printf '%s' {payload} > /opt/brokerage-gpu/candidate.json; touch /opt/brokerage-gpu/prepare-candidate; systemctl restart brokerage-gpu.service",
                timeout=2700,
            )
            instance = self.instances(workload)[0]
            deployment = {
                "cloud": "aws",
                "resource_id": iid,
                "private_ip": instance["PrivateIpAddress"],
            }
        else:
            client = self.runpod()
            suffix = "RUNPOD_CONTROL_SET" if workload == "f2" else "GENERAL_CONTROL_SET"
            registered = self.read(f"runpod/{suffix}")
            if (
                registered.get("status") != "ready"
                or registered.get("image") != spec["image"]
            ):
                raise ToolError("register the Console-managed RunPod Template first")
            source = json.loads(
                (
                    INFRA
                    / (
                        "runpod/template.json"
                        if workload == "f2"
                        else "serving/general-template.json"
                    )
                ).read_text()
            )
            control.validate_template(
                client.template(registered["template_id"]),
                control.template_payload(
                    source,
                    registered["image"],
                    registered["registry_auth_id"],
                    source["name"],
                ),
            )
            matches = [
                pod for pod in client.pods() if pod.get("name") == POD_NAME[workload]
            ]
            if len(matches) > 1:
                raise ToolError(
                    "multiple managed Pods found; inspect exact IDs before retrying"
                )
            environment = {"SERVING_IMAGE": spec["image"]}
            if getattr(self, "attempt_id", None):
                environment["SERVING_ATTEMPT_ID"] = self.attempt_id
            if workload == "f2":
                _, checksum, url = self.release(spec)
                environment.update(
                    {
                        "F2_SLLM_RELEASE_ID": spec["release_id"],
                        "F2_SLLM_BUNDLE_SHA256": checksum,
                        "F2_SLLM_BUNDLE_URL": url,
                    }
                )
            else:
                environment.update(
                    {
                        "GENERAL_MODEL_PROFILE": spec.get(
                            "model_profile", DEFAULT_GENERAL_PROFILE
                        ),
                        "VLLM_ENABLE_CUDA_COMPATIBILITY": "0",
                    }
                )
            if matches:
                details = client.pod(matches[0]["id"])
                if (
                    details.get("imageName") != registered["image"]
                    or details.get("templateId") != registered["template_id"]
                ):
                    raise ToolError(
                        "existing Pod does not match the registered deployment"
                    )
                if (
                    workload == "f2"
                    and details.get("env", {}).get("F2_SLLM_RELEASE_ID")
                    != spec["release_id"]
                ):
                    raise ToolError(
                        "existing F2 Pod uses a different release; delete it explicitly"
                    )
                if workload == "general" and details.get("env", {}).get(
                    "GENERAL_MODEL_PROFILE", DEFAULT_GENERAL_PROFILE
                ) != spec.get("model_profile", DEFAULT_GENERAL_PROFILE):
                    raise ToolError(
                        "existing general Pod uses a different model profile; delete it explicitly"
                    )
                if (
                    workload == "general"
                    and details.get("env", {}).get("VLLM_ENABLE_CUDA_COMPATIBILITY")
                    != "0"
                ):
                    raise ToolError(
                        "existing general Pod must explicitly disable CUDA compatibility; delete it explicitly"
                    )
                if f2.pod_status(details) != "RUNNING":
                    raise ToolError(
                        "delete the stopped managed Pod before recreating it"
                    )
            else:
                details = client.request(
                    "POST",
                    "/pods",
                    {
                        "name": POD_NAME[workload],
                        "cloudType": "SECURE",
                        "computeType": "GPU",
                        "gpuCount": 1,
                        "gpuTypeIds": [spec["gpu_id"]],
                        "gpuTypePriority": "availability",
                        "interruptible": False,
                        "supportPublicIp": True,
                        "templateId": registered["template_id"],
                        "volumeInGb": 0,
                        "env": environment,
                        **(
                            {"allowedCudaVersions": list(GENERAL_CUDA_VERSIONS)}
                            if workload == "general"
                            else {}
                        ),
                    },
                )
            deployment = {"cloud": "runpod", "resource_id": f2.resource_id(details)}
            if not matches:
                self.started_candidate = deployment
        deployment["image"] = spec["image"]
        deployment["hardware_profile"] = spec["hardware_profile"]
        if workload == "general":
            deployment.update(general_metadata(spec))
        deadline = time.monotonic() + 1800
        while time.monotonic() < deadline:
            try:
                self.probe(workload, deployment)
                return deployment
            except (ToolError, OSError, ValueError, KeyError):
                time.sleep(10)
        raise ToolError(
            f"{workload} model readiness/inference timed out; inspect and stop the candidate"
        )

    def probe(self, workload: str, deployment: dict) -> None:
        if deployment["cloud"] == "aws":
            self.command(
                deployment["resource_id"],
                "python3 /opt/brokerage-gpu/probe.py"
                + (
                    " --model " + shlex.quote(general_profile(deployment)["model"])
                    if workload == "general"
                    else ""
                ),
                timeout=300,
            )
        else:
            keys = self.secret("ai/provider-api-keys")
            urls = endpoint_urls("runpod", deployment["resource_id"], workload)
            if workload == "f2":
                probe(urls[0], keys["AI_VLLM_SLLM_API_KEY"], "sllm")
                probe(urls[1], keys["AI_VLLM_STT_API_KEY"], "stt", stt=True)
            else:
                probe(urls[0], keys[GENERAL_KEY], general_profile(deployment)["model"])

    def application_smoke(self, workload: str) -> None:
        instance = self.app_id()
        if not instance:
            raise ToolError("application smoke requires a running app")
        script = "smoke_f2.sh" if workload == "f2" else "smoke_general.sh"
        command = f"/opt/brokerage/revision/scripts/{script}"
        if workload == "general":
            command += " " + shlex.quote(
                general_profile(self.endpoint(workload))["model"]
            )
        self.command(instance, command, timeout=600)

    def stop_resources(self, workload: str, *, keep: dict | None = None) -> None:
        errors = []
        try:
            instances = self.instances(workload)
        except (BotoCoreError, ClientError):
            instances = []
            errors.append("AWS inventory unavailable")
        for instance in instances:
            iid = instance["InstanceId"]
            if keep and keep["cloud"] == "aws" and keep["resource_id"] == iid:
                continue
            try:
                if instance["State"]["Name"] not in {"stopped", "stopping"}:
                    self.ec2.stop_instances(InstanceIds=[iid])
                self.ec2.get_waiter("instance_stopped").wait(InstanceIds=[iid])
            except (BotoCoreError, ClientError):
                errors.append(iid)
        try:
            for pod in self.managed_pods():
                if pod.get("name") != POD_NAME[workload] or (
                    keep
                    and keep["cloud"] == "runpod"
                    and keep["resource_id"] == pod["id"]
                ):
                    continue
                try:
                    self.runpod().delete(pod["id"])
                except f2.ToolError:
                    errors.append(pod["id"])
        except (BotoCoreError, ClientError, f2.ToolError):
            errors.append("RunPod inventory unavailable")
        if errors:
            raise ToolError("GPU shutdown incomplete: " + ", ".join(errors))

    def switch(self, workload: str, cloud: str, *, apply: bool) -> None:
        from selection_catalog import default_hardware
        from serving_selection import save

        previous = self.selection()[workload]
        if not previous:
            raise ToolError("ai-select this workload first")
        spec = {
            **previous,
            "cloud": cloud,
            "hardware_profile": default_hardware(workload, cloud),
        }
        spec.pop("gpu_id", None)
        save(self, {workload: spec}, apply=apply)

    def start(self, **options) -> None:
        from serving_lifecycle import Lifecycle

        Lifecycle(self).run(**options)

    def prepare_deployment(self, **options) -> None:
        from serving_lifecycle import Lifecycle

        Lifecycle(self).run(prepare_only=True, **options)

    def capacity_config(self, candidate: str | None = None) -> None:
        selected = self.selection()
        workloads = {
            name for name, spec in selected.items() if spec and spec["cloud"] == "aws"
        }
        if candidate:
            # Keep every existing instance when preparing a switch; cleanup is explicit.
            workloads.update(name for name in WORKLOADS if self.instances(name))
            workloads.add(candidate)
        path = INFRA / "environments/dev/serving-capacity.auto.tfvars.json"
        path.write_text(
            json.dumps({"gpu_provisioned_workloads": sorted(workloads)}, indent=2)
            + "\n"
        )
        emit("gpu-capacity-input", workloads=sorted(workloads), applied=False)

    def stop(self) -> None:
        self.no_deployment()
        instance = self.app_id()
        if instance:
            self.command(instance, "touch /opt/brokerage/serving-maintenance")
        self.app("stop")
        errors = []
        for name in WORKLOADS:
            for operation in (
                lambda name=name: self.activate(name, {}, None),
                lambda name=name: self.stop_resources(name),
            ):
                try:
                    operation()
                except (ToolError, ClientError, BotoCoreError, f2.ToolError) as error:
                    detail = (
                        str(error)
                        if isinstance(error, (ToolError, f2.ToolError))
                        else type(error).__name__
                    )
                    errors.append(f"{name}: {detail}")
        try:
            self.power.stop()
        except (ToolError, ClientError, BotoCoreError) as error:
            errors.append(f"app/RDS: {type(error).__name__}")
        if errors:
            raise ToolError(
                "some GPU shutdown operations failed; inspect dev-status: "
                + ", ".join(errors)
            )
        emit(
            "dev-serving-stop-complete",
            aws_storage="retained and billable",
            runpod="deleted",
        )

    def status(self) -> None:
        self.power.status()
        selection = self.selection()
        from selection_catalog import validation_metadata

        desired = self.selection_document()
        try:
            applied = self.read("serving/APPLIED")
        except self.ssm.exceptions.ParameterNotFound:
            applied = {"status": "not-recorded"}
        emit(
            "serving-selection-status",
            desired=desired,
            last_apply=applied,
            validation={
                name: validation_metadata(name, spec)
                for name, spec in selection.items()
                if spec
            },
        )
        for name in WORKLOADS:
            instances = self.instances(name)
            ids = [
                block["Ebs"]["VolumeId"]
                for instance in instances
                for block in instance.get("BlockDeviceMappings", [])
                if "Ebs" in block
            ]
            volumes = self.ec2.describe_volumes(VolumeIds=ids)["Volumes"] if ids else []
            runtime = []
            for instance in instances:
                item = {
                    "id": instance["InstanceId"],
                    "state": instance["State"]["Name"],
                    "model_ready": False,
                    "disk_free_bytes": None,
                }
                if item["state"] == "running":
                    try:
                        observed = json.loads(
                            self.command(
                                item["id"],
                                "python3 /opt/brokerage-gpu/probe.py --status",
                                timeout=60,
                            )
                        )
                        item.update(
                            model_ready=observed["model_ready"] is True,
                            disk_free_bytes=observed.get("disk_free_bytes"),
                        )
                    except (
                        ToolError,
                        BotoCoreError,
                        ClientError,
                        ValueError,
                        KeyError,
                    ):
                        item["model_ready"] = "unavailable"
                runtime.append(item)
            try:
                endpoint_status = self.endpoint(name).get("status")
            except self.ssm.exceptions.ParameterNotFound:
                endpoint_status = "not configured"
            emit(
                "gpu-status",
                workload=name,
                selected_cloud=(selection[name] or {}).get("cloud"),
                aws_instances=runtime,
                ebs_allocated_gib=sum(item["Size"] for item in volumes),
                endpoint_status=endpoint_status,
                costs="running (even idle): GPU + EBS + public IPv4; stopped: EBS; deleted: no GPU/EBS",
            )
        pods = self.managed_pods()
        runtime = []
        for pod in pods:
            if pod.get("name") not in POD_NAME.values():
                continue
            name = next(
                name for name, expected in POD_NAME.items() if pod["name"] == expected
            )
            item = {
                "id": pod["id"],
                "workload": name,
                "state": f2.pod_status(pod),
                "model_ready": False,
                "disk_free_bytes": None,
                "volume_gb": pod.get("volumeInGb", 0),
                "network_volume": bool(pod.get("networkVolumeId")),
            }
            if item["state"] == "RUNNING":
                try:
                    keys = self.secret("ai/provider-api-keys")
                    urls = endpoint_urls("runpod", pod["id"], name)
                    item.update(
                        read_status(
                            urls[0],
                            keys[
                                GENERAL_KEY
                                if name == "general"
                                else "AI_VLLM_SLLM_API_KEY"
                            ],
                            general_profile(selection[name] or {})["model"]
                            if name == "general"
                            else "sllm",
                        )
                    )
                    if name == "f2":
                        item["model_ready"] = (
                            item["model_ready"]
                            and read_status(
                                urls[1], keys["AI_VLLM_STT_API_KEY"], "stt"
                            )["model_ready"]
                        )
                except (OSError, ValueError, KeyError, ClientError, BotoCoreError):
                    item["model_ready"] = "unavailable"
            runtime.append(item)
        emit(
            "runpod-status",
            pods=runtime,
            costs="running (even idle): GPU + container disk; stopped: retained volumes; deleted: separate Network Volumes still billable",
        )


def validate_selection(workload: str, spec: dict) -> None:
    from selection_catalog import normalize_spec

    try:
        normalize_spec(workload, spec)
    except ValueError as error:
        raise ToolError(str(error)) from None


def main() -> int:
    args = parser().parse_args()
    settings = power.Settings(
        args.account_id,
        args.profile,
        "ap-northeast-2",
        args.project,
        power.DEFAULT_OPERATOR_ROLE,
        power.DEFAULT_TIMEOUT_SECONDS,
    )
    try:
        if not re.fullmatch(r"[0-9]{12}", args.account_id) or not re.fullmatch(
            r"[a-z0-9-]{3,24}", args.project
        ):
            raise ToolError("explicit account ID and valid project name are required")
        session = power.assume_operator(power.base_session(settings), settings)
        controller = Serving(session, settings)
        if args.command in {"prepare-deployment", "start"}:
            rates = {}
            for value in args.hourly_usd:
                name, rate = value.split("=", 1)
                import math

                if (
                    name not in WORKLOADS
                    or not math.isfinite(float(rate))
                    or float(rate) <= 0
                ):
                    raise ToolError(
                        "hourly rate must be f2=POSITIVE_USD or general=POSITIVE_USD"
                    )
                rates[name] = float(rate)
            action = (
                controller.prepare_deployment
                if args.command == "prepare-deployment"
                else controller.start
            )
            action(apply=args.apply, hours=args.hours, rates=rates)
        elif args.command == "select":
            from serving_selection import select

            select(controller, args)
        elif args.command == "stop":
            power.require_apply(args.apply, args.command)
            power.require_stop_confirmation(args.workloads_stopped_confirmed)
            controller.stop()
        elif args.command == "capacity-config":
            controller.capacity_config(args.candidate)
        elif args.command == "activate-general":
            power.require_apply(args.apply, args.command)
            power.require_stop_confirmation(args.workloads_stopped_confirmed)
            if args.brokerage_id < 1:
                raise ToolError("positive brokerage ID required")
            controller.no_deployment()
            instance = controller.app_id()
            if not instance:
                raise ToolError(
                    "app instance unavailable; model selection requires an existing maintenance host"
                )
            # The remote command verifies workloads are already stopped and uses the
            # freshly rendered AI selection. Never restart or infer as a side effect.
            controller.command(
                instance,
                f"/opt/brokerage/revision/scripts/serving_maintenance.sh activate-general {args.brokerage_id} {shlex.quote(args.capability)}",
                timeout=360,
            )
            emit(
                "model-selection-complete",
                capability=args.capability,
                workloads="stopped",
            )
        elif args.command == "configure":
            selection = controller.selection()
            spec = {"cloud": args.cloud, "gpu_id": args.gpu_id}
            if args.workload == "f2":
                spec.update(
                    release_id=args.release_id,
                    bucket=args.bucket,
                    allow_dev_release=args.allow_dev_release,
                )
            else:
                spec["model_profile"] = args.model_profile or (
                    selection["general"] or {}
                ).get("model_profile", DEFAULT_GENERAL_PROFILE)
            if args.workload == "f2" and args.model_profile is not None:
                raise ToolError("model profile selection is only supported for general")
            from serving_selection import save

            save(controller, {args.workload: spec}, apply=args.apply)
        elif args.command == "switch":
            controller.switch(args.workload, args.cloud, apply=args.apply)
        elif args.command == "verify":
            from serving_verification import verify_running

            verify_running(controller, args.workload)
        elif args.command == "smoke":
            controller.application_smoke(args.workload)
        else:
            controller.status()
        return 0
    except (ToolError, f2.ToolError, artifact.ToolError, control.ToolError) as error:
        emit("error", message=str(error))
    except (ClientError, BotoCoreError, ValueError, KeyError, OSError):
        emit(
            "error",
            message="serving operation failed; inspect configuration and cloud status (sensitive details withheld)",
        )
    except KeyboardInterrupt:
        emit(
            "error",
            message="interrupted; run dev-status and clean up candidate GPU before retrying",
        )
    return 2


if __name__ == "__main__":
    sys.exit(main())
