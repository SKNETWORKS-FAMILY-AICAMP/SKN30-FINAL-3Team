# /// script
# requires-python = ">=3.13,<3.14"
# dependencies = [
#   "boto3>=1.40,<2",
# ]
# ///
"""Verify the dev Bedrock route from an application container without inference."""

from __future__ import annotations

import argparse
import json
import shlex
import sys
import time
from dataclasses import dataclass
from typing import Any

import boto3
from botocore.exceptions import ClientError

AWS_REGION = "ap-northeast-2"
DEFAULT_PROFILE = "skn30-session"
DEFAULT_PROJECT = "skn30-final-3team"
DEFAULT_OPERATOR_ROLE = "TerraformOperatorRole"
BEDROCK_PROFILE_ID = "global.openai.gpt-5.6-luna"
SUCCESS_MARKER = "BEDROCK_DOCTOR_OK"
POLL_SECONDS = 2
MAX_POLLS = 30


class ToolError(RuntimeError):
    """An expected error whose message is safe to print."""


@dataclass(frozen=True)
class Settings:
    account_id: str
    profile: str
    region: str
    project: str
    operator_role: str

    @property
    def environment(self) -> str:
        return "dev"

    @property
    def operator_role_arn(self) -> str:
        return f"arn:aws:iam::{self.account_id}:role/{self.operator_role}"


def emit(event: str, **fields: object) -> None:
    print(json.dumps({"event": event, **fields}, ensure_ascii=False, sort_keys=True))


def validate_identity(identity: dict[str, Any], account_id: str) -> None:
    if str(identity.get("Account")) != account_id:
        raise ToolError("current AWS account does not match --account-id")
    if str(identity.get("Arn", "")).endswith(":root"):
        raise ToolError("root credentials are not allowed")


def base_session(settings: Settings) -> boto3.Session:
    session = boto3.Session(profile_name=settings.profile, region_name=settings.region)
    validate_identity(session.client("sts").get_caller_identity(), settings.account_id)
    return session


def assume_operator(session: boto3.Session, settings: Settings) -> boto3.Session:
    response = session.client("sts").assume_role(
        RoleArn=settings.operator_role_arn,
        RoleSessionName="bedrock-doctor",
        DurationSeconds=900,
    )
    credentials = response["Credentials"]
    return boto3.Session(
        aws_access_key_id=credentials["AccessKeyId"],
        aws_secret_access_key=credentials["SecretAccessKey"],
        aws_session_token=credentials["SessionToken"],
        region_name=settings.region,
    )


def find_app_instance(session: boto3.Session, settings: Settings) -> str:
    response = session.client("ec2").describe_instances(
        Filters=[
            {"Name": "instance-state-name", "Values": ["running"]},
            {"Name": "tag:Project", "Values": [settings.project]},
            {"Name": "tag:Environment", "Values": [settings.environment]},
            {"Name": "tag:ManagedBy", "Values": ["Terraform"]},
            {
                "Name": "tag:aws:autoscaling:groupName",
                "Values": [f"{settings.project}-{settings.environment}-app"],
            },
        ]
    )
    instances = [
        instance
        for reservation in response.get("Reservations", [])
        for instance in reservation.get("Instances", [])
    ]
    if len(instances) != 1:
        raise ToolError("expected exactly one running tagged development app instance")
    instance = instances[0]
    metadata = instance.get("MetadataOptions") or {}
    if metadata.get("State") != "applied":
        raise ToolError("development app instance metadata options are not applied")
    if metadata.get("HttpTokens") != "required":
        raise ToolError("development app instance must require IMDSv2 tokens")
    if int(metadata.get("HttpPutResponseHopLimit", 0)) != 2:
        raise ToolError("development app instance must use IMDSv2 hop limit 2")
    return str(instance["InstanceId"])


def container_doctor_command(region: str) -> str:
    check = (
        "from botocore.session import get_session;"
        f"profile={BEDROCK_PROFILE_ID!r};"
        f"client=get_session().create_client('bedrock',region_name={region!r});"
        "response=client.get_inference_profile(inferenceProfileIdentifier=profile);"
        "assert response.get('inferenceProfileId') == profile;"
        f"print({SUCCESS_MARKER!r})"
    )
    inner = "\n".join(
        (
            "set -euo pipefail",
            "source /opt/brokerage/revision/scripts/common.sh",
            "require_backend_image",
            f"compose run --rm --no-deps worker python -c {shlex.quote(check)}",
        )
    )
    return f"bash -lc {shlex.quote(inner)}"


def wait_for_command(ssm: Any, command_id: str, instance_id: str) -> dict[str, Any]:
    for _ in range(MAX_POLLS):
        try:
            result = ssm.get_command_invocation(
                CommandId=command_id,
                InstanceId=instance_id,
            )
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") == "InvocationDoesNotExist":
                time.sleep(POLL_SECONDS)
                continue
            raise
        if result.get("Status") in {"Success", "Cancelled", "TimedOut", "Failed"}:
            return result
        time.sleep(POLL_SECONDS)
    raise ToolError("Bedrock doctor timed out waiting for the SSM command")


def doctor(session: boto3.Session, settings: Settings) -> None:
    instance_id = find_app_instance(session, settings)
    ssm = session.client("ssm")
    information = ssm.describe_instance_information(
        Filters=[{"Key": "InstanceIds", "Values": [instance_id]}]
    ).get("InstanceInformationList", [])
    if len(information) != 1 or information[0].get("PingStatus") != "Online":
        raise ToolError("development app instance is not SSM Online")

    response = ssm.send_command(
        InstanceIds=[instance_id],
        DocumentName="AWS-RunShellScript",
        Comment="Verify Bedrock Luna profile access from the dev Worker container",
        Parameters={"commands": [container_doctor_command(settings.region)]},
        TimeoutSeconds=90,
    )
    command_id = str(response["Command"]["CommandId"])
    result = wait_for_command(ssm, command_id, instance_id)
    if result.get("Status") != "Success" or SUCCESS_MARKER not in str(
        result.get("StandardOutputContent", "")
    ):
        raise ToolError("Bedrock doctor failed inside the development Worker container")
    emit(
        "bedrock-doctor-complete",
        authentication="ec2-instance-role-sigv4",
        inference=False,
        model_profile=BEDROCK_PROFILE_ID,
        region=settings.region,
    )


def parser() -> argparse.ArgumentParser:
    command_parser = argparse.ArgumentParser(description=__doc__)
    command_parser.add_argument("--account-id", required=True)
    command_parser.add_argument("--profile", default=DEFAULT_PROFILE)
    command_parser.add_argument("--region", default=AWS_REGION)
    command_parser.add_argument("--project", default=DEFAULT_PROJECT)
    command_parser.add_argument("--operator-role", default=DEFAULT_OPERATOR_ROLE)
    return command_parser


def settings_from(arguments: argparse.Namespace) -> Settings:
    if not arguments.account_id.isdigit() or len(arguments.account_id) != 12:
        raise ToolError("--account-id must contain exactly 12 digits")
    if arguments.region != AWS_REGION:
        raise ToolError("only ap-northeast-2 is supported")
    return Settings(
        account_id=arguments.account_id,
        profile=arguments.profile,
        region=arguments.region,
        project=arguments.project,
        operator_role=arguments.operator_role,
    )


def main() -> None:
    settings = settings_from(parser().parse_args())
    doctor(assume_operator(base_session(settings), settings), settings)


if __name__ == "__main__":
    try:
        main()
    except ToolError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from None
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code", "ClientError")
        print(f"ERROR: AWS request failed ({code})", file=sys.stderr)
        raise SystemExit(1) from None
