# /// script
# requires-python = ">=3.13,<3.14"
# dependencies = ["boto3>=1.40,<2"]
# ///
"""Explicit dev serving operations; no daemon, auto-failover, or shadow state store."""

from __future__ import annotations

import argparse
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
    return load_profile(spec.get("model_profile", DEFAULT_GENERAL_PROFILE))


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

    def selection(self) -> dict:
        try:
            result = self.read("serving/SELECTION")
        except self.ssm.exceptions.ParameterNotFound:
            return {"f2": None, "general": None}
        if set(result) != set(WORKLOADS):
            raise ToolError("serving selection must contain f2 and general")
        for name, spec in result.items():
            if spec is not None:
                validate_selection(name, spec)
        return result

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

    def release(self, spec: dict) -> tuple[dict, str, str]:
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
        return manifest, checksum, operations.presign(spec["release_id"])

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
                except (BotoCoreError, ClientError, f2.ToolError):
                    emit(
                        "candidate-cleanup-incomplete",
                        resource_id=candidate["resource_id"],
                        action="inspect dev-status; retry dev-stop during maintenance",
                    )
            raise

    def _prepare(self, workload: str, spec: dict) -> dict:
        validate_selection(workload, spec)
        if spec["cloud"] == "aws":
            matches = self.instances(workload)
            if len(matches) != 1:
                raise ToolError(
                    "apply a reviewed GPU Terraform plan first; expected one managed instance"
                )
            instance = matches[0]
            iid = instance["InstanceId"]
            suffix = "RUNPOD_CONTROL_SET" if workload == "f2" else "GENERAL_CONTROL_SET"
            registered = self.read(f"runpod/{suffix}")
            tags = {tag["Key"]: tag["Value"] for tag in instance.get("Tags", [])}
            if registered.get("status") != "ready" or tags.get(
                "ServingImage"
            ) != registered.get("image"):
                raise ToolError(
                    "AWS GPU image must match the registered immutable RunPod image; review the GPU Terraform plan"
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
            if registered.get("status") != "ready":
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
            environment = {}
            if workload == "f2":
                _, checksum, url = self.release(spec)
                environment = {
                    "F2_SLLM_RELEASE_ID": spec["release_id"],
                    "F2_SLLM_BUNDLE_SHA256": checksum,
                    "F2_SLLM_BUNDLE_URL": url,
                }
            else:
                environment = {
                    "GENERAL_MODEL_PROFILE": spec.get(
                        "model_profile", DEFAULT_GENERAL_PROFILE
                    ),
                    "VLLM_ENABLE_CUDA_COMPATIBILITY": "1",
                }
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
            client = self.runpod()
            for pod in client.pods():
                if pod.get("name") != POD_NAME[workload] or (
                    keep
                    and keep["cloud"] == "runpod"
                    and keep["resource_id"] == pod["id"]
                ):
                    continue
                try:
                    client.delete(pod["id"])
                except f2.ToolError:
                    errors.append(pod["id"])
        except (BotoCoreError, ClientError, f2.ToolError):
            errors.append("RunPod inventory unavailable")
        if errors:
            raise ToolError("GPU shutdown incomplete: " + ", ".join(errors))

    def switch(self, workload: str, cloud: str, *, apply: bool) -> None:
        selection = self.selection()
        previous = selection[workload]
        if not previous:
            raise ToolError("configure this workload before switching")
        spec = {**previous, "cloud": cloud}
        validate_selection(workload, spec)
        self.no_deployment()
        emit(
            "ai-switch-plan",
            workload=workload,
            source=previous["cloud"],
            target=cloud,
            downtime="whole application",
            aws_capacity="must be provisioned by reviewed Terraform plan",
            standby="AWS stopped/EBS retained; RunPod deleted",
            apply=apply,
            model=general_profile(spec)["model"]
            if workload == "general"
            else "existing F2 SLLM + Whisper",
            release=spec.get("release_id"),
            runpod_gpu=spec["gpu_id"],
            aws_type="g6.2xlarge" if workload == "f2" else "g6e.2xlarge",
            billing="target GPU while preparing; old AWS EBS after switch; delete RunPod; account budget and live rate must be reviewed",
        )
        if not apply:
            return
        # Candidate failure does not change routing or the selected provider.
        current = self.endpoint(workload)
        if (
            current.get("status") == "active"
            and previous["cloud"] == cloud
            and current.get("cloud", "runpod") == cloud
        ):
            self.application_smoke(workload)
            emit("ai-switch-complete", workload=workload, cloud=cloud, changed=False)
            return
        deployment = self.prepare(workload, spec)
        self.app("stop")
        try:
            self.activate(workload, spec, deployment)
            self.app("start")
            self.application_smoke(workload)
            selection[workload] = spec
            self.write("serving/SELECTION", selection)
        except (ToolError, BotoCoreError, ClientError, OSError, ValueError):
            self.app("stop")
            self.activate(workload, spec, None)
            raise ToolError(
                "cutover failed; service remains in maintenance; rerun ai-switch for explicit recovery"
            ) from None
        self.stop_resources(workload, keep=deployment)
        emit("ai-switch-complete", workload=workload, cloud=cloud)

    def start(self) -> None:
        selection = self.selection()
        self.no_deployment()
        deployments = {}
        if self.app_id():
            self.app("stop")
        # GPU endpoints are ready before an ASG replacement can start a worker.
        for name, spec in selection.items():
            if spec:
                deployments[name] = self.prepare(name, spec)
                self.activate(name, spec, deployments[name])
        try:
            self.power.start()
            self.restore_application()
            self.app("start")
            for name in deployments:
                self.application_smoke(name)
        except (ToolError, BotoCoreError, ClientError, OSError, ValueError):
            self.app("stop")
            raise ToolError(
                "dev-start failed; maintenance retained; inspect dev-status and retry dev-start"
            ) from None
        for name in WORKLOADS:
            self.stop_resources(name, keep=deployments.get(name))
        emit("dev-serving-start-complete", workloads=list(deployments))

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

    def restore_application(self) -> None:
        client = self.session.client("codedeploy")
        name = f"{self.prefix}-backend"
        group = client.get_deployment_group(
            applicationName=name, deploymentGroupName=name
        )["deploymentGroupInfo"]
        last = group.get("lastSuccessfulDeployment", {}).get("deploymentId")
        if not last:
            raise ToolError(
                "no successful Backend deployment exists; deploy the reviewed Backend revision first"
            )
        # ASG launch deployments can be in progress after capacity is healthy.
        for deployment_id in client.list_deployments(
            applicationName=name,
            deploymentGroupName=name,
            includeOnlyStatuses=["Created", "Queued", "InProgress", "Ready", "Baking"],
        ).get("deployments", []):
            client.get_waiter("deployment_successful").wait(deploymentId=deployment_id)
        instance = self.app_id()
        try:
            self.command(
                instance,
                "test -s /opt/brokerage/revision/backend-image.env && test -x /opt/brokerage/revision/scripts/serving_maintenance.sh",
            )
            return
        except ToolError:
            revision = client.get_deployment(deploymentId=last)["deploymentInfo"][
                "revision"
            ]
            result = client.create_deployment(
                applicationName=name,
                deploymentGroupName=name,
                revision=revision,
                description="Restore last successful app revision after dev-start",
            )
            client.get_waiter("deployment_successful").wait(
                deploymentId=result["deploymentId"]
            )

    def stop(self) -> None:
        self.no_deployment()
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
        pods = self.runpod().pods()
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
    if (
        workload not in WORKLOADS
        or not isinstance(spec, dict)
        or spec.get("cloud") not in {"aws", "runpod"}
    ):
        raise ToolError("invalid workload/cloud selection")
    allowed = {"cloud", "gpu_id", "release_id", "bucket", "allow_dev_release"}
    if workload == "general":
        allowed.add("model_profile")
        general_profile(spec)
    if set(spec) - allowed:
        raise ToolError("unsupported selection fields")
    if not isinstance(spec.get("gpu_id"), str) or not re.fullmatch(
        r"[A-Za-z0-9 ._-]{3,100}", spec["gpu_id"]
    ):
        raise ToolError("an explicit RunPod GPU ID is required for recovery")
    if workload == "f2" and (
        not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,63}", str(spec.get("release_id", "")))
        or not re.fullmatch(r"[a-z0-9.-]{3,63}", str(spec.get("bucket", "")))
    ):
        raise ToolError("F2 requires its published release ID and model bucket")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--account-id", default=os.environ.get("TARGET_ACCOUNT_ID", ""))
    result.add_argument("--profile", default="skn30-session")
    result.add_argument("--project", default="skn30-final-3team")
    commands = result.add_subparsers(dest="command", required=True)
    for action in ("start", "stop", "status"):
        p = commands.add_parser(action)
        if action != "status":
            p.add_argument("--apply", action="store_true")
            p.add_argument("--workloads-stopped-confirmed", action="store_true")
    activation = commands.add_parser("activate-general")
    activation.add_argument("brokerage_id", type=int)
    activation.add_argument("--model-profile")
    activation.add_argument("--apply", action="store_true")
    activation.add_argument("--workloads-stopped-confirmed", action="store_true")
    capacity = commands.add_parser("capacity-config")
    capacity.add_argument("--candidate", choices=WORKLOADS)
    for action in ("switch", "configure", "smoke"):
        p = commands.add_parser(action)
        p.add_argument("workload", choices=WORKLOADS)
        if action != "smoke":
            p.add_argument("cloud", choices=("aws", "runpod"))
            p.add_argument("--apply", action="store_true")
        if action == "configure":
            p.add_argument("--gpu-id", required=True)
            p.add_argument("--model-profile")
            p.add_argument("--release-id")
            p.add_argument("--bucket")
            p.add_argument("--allow-dev-release", action="store_true")
    return result


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
        if args.command in {"start", "stop"}:
            power.require_apply(args.apply, args.command)
            if args.command == "stop":
                power.require_stop_confirmation(args.workloads_stopped_confirmed)
            getattr(controller, args.command)()
        elif args.command == "capacity-config":
            controller.capacity_config(args.candidate)
        elif args.command == "activate-general":
            power.require_apply(args.apply, args.command)
            power.require_stop_confirmation(args.workloads_stopped_confirmed)
            if args.brokerage_id < 1:
                raise ToolError("positive brokerage ID required")
            endpoint = controller.endpoint("general")
            if endpoint.get("status") != "active":
                raise ToolError("activate-general requires an active general endpoint")
            selected_profile = args.model_profile or endpoint.get(
                "model_profile", DEFAULT_GENERAL_PROFILE
            )
            model = general_profile({"model_profile": selected_profile})["model"]
            if model != general_profile(endpoint)["model"]:
                raise ToolError(
                    "activation model must match the active general endpoint"
                )
            controller.no_deployment()
            controller.app("stop")
            instance = controller.app_id()
            if not instance:
                raise ToolError("app instance unavailable")
            controller.command(
                instance,
                f"/opt/brokerage/revision/scripts/serving_maintenance.sh activate-general {args.brokerage_id} {shlex.quote(model)}",
                timeout=360,
            )
            try:
                controller.app("start")
                controller.application_smoke("general")
            except (ToolError, ClientError, BotoCoreError):
                controller.app("stop")
                raise ToolError(
                    "model activation verification failed; maintenance retained; repair GPU and rerun ai-switch"
                ) from None
        elif args.command == "configure":
            selection = controller.selection()
            if controller.endpoint(args.workload).get("status") != "offline":
                raise ToolError(
                    "configure requires an offline workload; use ai-switch for active deployments"
                )
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
            validate_selection(args.workload, spec)
            selection[args.workload] = spec
            if args.apply:
                controller.write("serving/SELECTION", selection)
            emit(
                "serving-configure",
                workload=args.workload,
                cloud=args.cloud,
                apply=args.apply,
            )
        elif args.command == "switch":
            controller.switch(args.workload, args.cloud, apply=args.apply)
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
