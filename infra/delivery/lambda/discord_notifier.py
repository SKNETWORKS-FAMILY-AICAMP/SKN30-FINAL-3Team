from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

import boto3

codepipeline = boto3.client("codepipeline")
codedeploy = boto3.client("codedeploy")
secretsmanager = boto3.client("secretsmanager")


def secret_url() -> str:
    value = secretsmanager.get_secret_value(
        SecretId=os.environ["DISCORD_SECRET_ARN"]
    )["SecretString"]
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return value
    return str(payload["webhook_url"])


def pipeline_message(detail: dict[str, Any]) -> str:
    pipeline = str(detail["pipeline"])
    execution_id = str(detail["execution-id"])
    state = str(detail["state"])
    execution = codepipeline.get_pipeline_execution(
        pipelineName=pipeline,
        pipelineExecutionId=execution_id,
    )["pipelineExecution"]
    revision = "unknown"
    revisions = execution.get("artifactRevisions", [])
    if revisions:
        revision = revisions[0].get("revisionId", revision)

    failed_stage = "-"
    if state == "FAILED":
        actions = codepipeline.list_action_executions(
            pipelineName=pipeline,
            filter={"pipelineExecutionId": execution_id},
        ).get("actionExecutionDetails", [])
        failed = [item for item in actions if item.get("status") == "Failed"]
        if failed:
            failed_stage = (
                f"{failed[0].get('stageName', '?')}/"
                f"{failed[0].get('actionName', '?')}"
            )

    region = os.environ["AWS_REGION"]
    console = (
        f"https://{region}.console.aws.amazon.com/codesuite/codepipeline/"
        f"pipelines/{pipeline}/executions/{execution_id}/timeline"
    )
    return (
        f"**{pipeline}** {state}\n"
        f"revision: `{revision}`\n"
        f"execution: `{execution_id}`\n"
        f"failed stage: `{failed_stage}`\n"
        f"<{console}>"
    )


def deployment_message(detail: dict[str, Any]) -> str:
    return (
        f"**CodeDeploy {detail.get('state', 'UNKNOWN')}**\n"
        f"application: `{detail.get('application', 'unknown')}`\n"
        f"deployment: `{detail.get('deployment-id', 'unknown')}`"
    )


def handler(event: dict[str, Any], _context: Any) -> None:
    for record in event.get("Records", []):
        message = json.loads(record["Sns"]["Message"])
        detail_type = message.get("detail-type")
        detail = message.get("detail", {})
        if detail_type == "CodePipeline Pipeline Execution State Change":
            content = pipeline_message(detail)
        elif detail_type == "CodeDeploy Deployment State-change Notification":
            content = deployment_message(detail)
        else:
            content = f"Runtime alert: `{detail_type or 'SNS'}`"
        request = urllib.request.Request(
            secret_url(),
            data=json.dumps({"content": content}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.status >= 300:
                raise RuntimeError(f"Discord returned HTTP {response.status}")
