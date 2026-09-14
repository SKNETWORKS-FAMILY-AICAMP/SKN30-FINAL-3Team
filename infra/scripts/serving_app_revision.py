"""Restore only an application revision previously attested by dev-start smoke.

This creates a CodeDeploy deployment of the exact saved S3 revision. It does not
start CodePipeline or choose the latest unverified application build.
"""

from __future__ import annotations

import hashlib
import json
import re
import time

from botocore.exceptions import BotoCoreError, ClientError
from manage_dev_power import ToolError, emit
from serving_deployment import require_maintenance_deployment

DEPLOYMENT_ID = re.compile(r"d-[A-Za-z0-9]{1,128}\Z")


def _identity(serving) -> None:
    identity = serving.session.client("sts").get_caller_identity()
    if (
        identity.get("Account") != serving.settings.account_id
        or serving.settings.region != "ap-northeast-2"
    ):
        raise ToolError("application revision operation account/region mismatch")


def _revision(serving, client, identifier: str) -> dict:
    if not isinstance(identifier, str) or not DEPLOYMENT_ID.fullmatch(identifier):
        raise ToolError("a valid attested CodeDeploy deployment ID is required")
    info = client.get_deployment(deploymentId=identifier)["deploymentInfo"]
    name = f"{serving.settings.name_prefix}-backend"
    if (
        info.get("applicationName") != name
        or info.get("deploymentGroupName") != name
        or info.get("status") != "Succeeded"
    ):
        raise ToolError(
            "attested deployment must be successful in this dev application/group"
        )
    revision = info.get("revision", {})
    location = revision.get("s3Location", {})
    if (
        revision.get("revisionType") != "S3"
        or not location.get("bucket")
        or not location.get("key")
        or not (location.get("version") or location.get("eTag"))
    ):
        raise ToolError("application revision must have an S3 object version or eTag")
    return revision


def _digest(revision: dict) -> str:
    return hashlib.sha256(
        json.dumps(revision, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def capture(serving) -> dict:
    """Caller must have verified CLI support and both application smoke tests."""
    _identity(serving)
    serving.no_deployment()
    client = serving.session.client("codedeploy")
    name = f"{serving.settings.name_prefix}-backend"
    group = client.get_deployment_group(applicationName=name, deploymentGroupName=name)[
        "deploymentGroupInfo"
    ]
    identifier = group.get("lastSuccessfulDeployment", {}).get("deploymentId")
    revision = _revision(serving, client, identifier)
    instance = serving.app_id()
    if not instance:
        raise ToolError("application revision attestation requires the tested app host")
    summary = client.get_deployment_instance(
        deploymentId=identifier, instanceId=instance
    )["instanceSummary"]
    if summary.get("status") != "Succeeded":
        raise ToolError(
            "latest successful deployment was not installed on the tested app host"
        )
    return {"deployment_id": identifier, "revision_sha256": _digest(revision)}


def restore(serving, attestation: dict | None) -> bool:
    """Return false only when there is no attestation; invalid evidence fails closed."""
    if attestation is None:
        return False
    if (
        not isinstance(attestation, dict)
        or set(attestation) != {"deployment_id", "revision_sha256"}
        or not isinstance(attestation.get("revision_sha256"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", attestation["revision_sha256"])
    ):
        raise ToolError(
            "invalid application revision attestation; use explicit app-deploy"
        )
    _identity(serving)
    serving.no_deployment()
    client = serving.session.client("codedeploy")
    revision = _revision(serving, client, attestation["deployment_id"])
    if _digest(revision) != attestation["revision_sha256"]:
        raise ToolError(
            "attested application revision changed; explicit app-deploy required"
        )
    require_maintenance_deployment(serving.session, serving.settings)
    instance = serving.app_id()
    if not instance:
        raise ToolError("application restore requires a maintenance host")
    # SSM online precedes cloud-init and CodeDeploy readiness on a fresh ASG host.
    serving.command(
        instance,
        "set -eu; cloud-init status --wait >/dev/null; systemctl is-active --quiet codedeploy-agent; test -f /opt/brokerage/serving-maintenance",
        timeout=600,
    )
    serving.no_deployment()
    name = f"{serving.settings.name_prefix}-backend"
    result = client.create_deployment(
        applicationName=name,
        deploymentGroupName=name,
        revision=revision,
        description="Restore previously smoke-attested dev application in maintenance",
        autoRollbackConfiguration={"enabled": False},
    )
    identifier = result.get("deploymentId")
    if not isinstance(identifier, str) or not DEPLOYMENT_ID.fullmatch(identifier):
        raise ToolError("CodeDeploy restore did not return a valid deployment ID")
    emit(
        "application-revision-restore",
        source_deployment_id=attestation["deployment_id"],
        deployment_id=identifier,
    )
    deadline = time.monotonic() + serving.settings.timeout_seconds
    while time.monotonic() < deadline:
        status = client.get_deployment(deploymentId=identifier)["deploymentInfo"].get(
            "status"
        )
        if status == "Succeeded":
            return True
        if status in {"Failed", "Stopped"}:
            raise ToolError(
                "attested application restoration failed; maintenance retained"
            )
        time.sleep(5)
    try:
        client.stop_deployment(deploymentId=identifier, autoRollbackEnabled=False)
    except (BotoCoreError, ClientError):
        emit("application-restore-stop-unconfirmed", deployment_id=identifier)
    raise ToolError(
        "attested application restoration timed out; inspect CodeDeploy before retry"
    )
