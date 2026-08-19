# /// script
# requires-python = ">=3.13,<3.14"
# dependencies = [
#   "boto3>=1.40,<2",
# ]
# ///
"""Start, stop, and inspect the shared development compute safely."""

from __future__ import annotations

import argparse
import json
import re
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
ROLE_SESSION_SECONDS = 3600
MAX_TIMEOUT_SECONDS = ROLE_SESSION_SECONDS - 300
DEFAULT_TIMEOUT_SECONDS = MAX_TIMEOUT_SECONDS
POLL_SECONDS = 15


class ToolError(RuntimeError):
    """An expected error whose message is safe to print."""


@dataclass(frozen=True)
class Settings:
    account_id: str
    profile: str
    region: str
    project: str
    operator_role: str
    timeout_seconds: int

    @property
    def environment(self) -> str:
        return "dev"

    @property
    def name_prefix(self) -> str:
        return f"{self.project}-{self.environment}"

    @property
    def asg_name(self) -> str:
        return f"{self.name_prefix}-app"

    @property
    def database_identifier(self) -> str:
        return f"{self.name_prefix}-postgres"

    @property
    def operator_role_arn(self) -> str:
        return f"arn:aws:iam::{self.account_id}:role/{self.operator_role}"


def emit(event: str, **fields: object) -> None:
    print(json.dumps({"event": event, **fields}, ensure_ascii=False, sort_keys=True))


def require_apply(enabled: bool, command: str) -> None:
    if not enabled:
        raise ToolError(f"{command} changes AWS state; rerun with --apply after review")


def require_stop_confirmation(confirmed: bool) -> None:
    if not confirmed:
        raise ToolError(
            "stop requires --workloads-stopped-confirmed after checking deployments, "
            "migrations, API requests, and worker jobs"
        )


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
        RoleSessionName="dev-power-management",
        DurationSeconds=ROLE_SESSION_SECONDS,
    )
    credentials = response["Credentials"]
    return boto3.Session(
        aws_access_key_id=credentials["AccessKeyId"],
        aws_secret_access_key=credentials["SecretAccessKey"],
        aws_session_token=credentials["SessionToken"],
        region_name=settings.region,
    )


def expected_tags(settings: Settings) -> dict[str, str]:
    return {
        "Project": settings.project,
        "Environment": settings.environment,
        "ManagedBy": "Terraform",
    }


def validate_tags(
    tags: list[dict[str, Any]],
    settings: Settings,
    resource_name: str,
) -> None:
    actual = {str(tag["Key"]): str(tag["Value"]) for tag in tags}
    missing = {
        key: value
        for key, value in expected_tags(settings).items()
        if actual.get(key) != value
    }
    if missing:
        raise ToolError(
            f"{resource_name} does not have the expected project/environment tags"
        )


def validate_asg_power_config(group: dict[str, Any]) -> None:
    if int(group["MinSize"]) != 0 or int(group["MaxSize"]) != 1:
        raise ToolError(
            "the application ASG must be applied with min_size=0 and max_size=1"
        )
    if int(group["DesiredCapacity"]) not in {0, 1}:
        raise ToolError("the application ASG desired capacity must be zero or one")


def rds_start_action(status: str) -> str:
    actions = {
        "available": "ready",
        "stopped": "start",
        "stopping": "wait-stopped",
        "starting": "wait-available",
    }
    if status not in actions:
        raise ToolError(f"RDS cannot be started safely from status {status!r}")
    return actions[status]


def rds_stop_action(status: str) -> str:
    actions = {
        "available": "stop",
        "stopped": "ready",
        "stopping": "wait-stopped",
        "starting": "wait-available",
    }
    if status not in actions:
        raise ToolError(f"RDS cannot be stopped safely from status {status!r}")
    return actions[status]


class PowerController:
    def __init__(self, session: boto3.Session, settings: Settings) -> None:
        self.settings = settings
        self.autoscaling = session.client("autoscaling")
        self.rds = session.client("rds")
        self.ssm = session.client("ssm")
        self.elbv2 = session.client("elbv2")

    def describe_asg(self) -> dict[str, Any]:
        response = self.autoscaling.describe_auto_scaling_groups(
            AutoScalingGroupNames=[self.settings.asg_name]
        )
        groups = response["AutoScalingGroups"]
        if len(groups) != 1:
            raise ToolError("expected exactly one application Auto Scaling group")
        return groups[0]

    def describe_database(self) -> dict[str, Any]:
        response = self.rds.describe_db_instances(
            DBInstanceIdentifier=self.settings.database_identifier
        )
        instances = response["DBInstances"]
        if len(instances) != 1:
            raise ToolError("expected exactly one development RDS instance")
        return instances[0]

    def validate_resources(self) -> tuple[dict[str, Any], dict[str, Any]]:
        group = self.describe_asg()
        database = self.describe_database()
        validate_tags(group.get("Tags", []), self.settings, self.settings.asg_name)
        database_tags = self.rds.list_tags_for_resource(
            ResourceName=database["DBInstanceArn"]
        )["TagList"]
        validate_tags(
            database_tags,
            self.settings,
            self.settings.database_identifier,
        )
        return group, database

    def wait_for_database(self, expected_status: str, deadline: float) -> dict[str, Any]:
        last_status = ""
        while True:
            database = self.describe_database()
            status = str(database["DBInstanceStatus"])
            if status != last_status:
                emit(
                    "wait",
                    resource="rds",
                    identifier=self.settings.database_identifier,
                    status=status,
                )
                last_status = status
            if status == expected_status:
                return database
            if time.monotonic() >= deadline:
                raise ToolError(
                    f"timed out waiting for RDS status {expected_status!r}"
                )
            time.sleep(POLL_SECONDS)

    def wait_for_asg_capacity(
        self,
        desired_capacity: int,
        deadline: float,
    ) -> dict[str, Any]:
        last_state: tuple[int, int] | None = None
        while True:
            group = self.describe_asg()
            instances = group.get("Instances", [])
            in_service = [
                instance
                for instance in instances
                if instance["LifecycleState"] == "InService"
                and instance["HealthStatus"] == "Healthy"
            ]
            state = (int(group["DesiredCapacity"]), len(in_service))
            if state != last_state:
                emit(
                    "wait",
                    resource="asg",
                    name=self.settings.asg_name,
                    desired_capacity=state[0],
                    in_service_instances=state[1],
                    total_instances=len(instances),
                )
                last_state = state
            if desired_capacity == 0:
                complete = state[0] == 0 and not instances
            else:
                complete = state[0] == 1 and len(in_service) == 1
            if complete:
                return group
            if time.monotonic() >= deadline:
                raise ToolError(
                    f"timed out waiting for ASG capacity {desired_capacity}"
                )
            time.sleep(POLL_SECONDS)

    def online_ssm_instance_ids(self, instance_ids: list[str]) -> list[str]:
        if not instance_ids:
            return []
        response = self.ssm.describe_instance_information(
            Filters=[{"Key": "InstanceIds", "Values": instance_ids}]
        )
        return sorted(
            str(item["InstanceId"])
            for item in response["InstanceInformationList"]
            if item.get("PingStatus") == "Online"
        )

    def wait_for_ssm(self, instance_id: str, deadline: float) -> None:
        while True:
            if instance_id in self.online_ssm_instance_ids([instance_id]):
                emit("wait", resource="ssm", instance_id=instance_id, status="Online")
                return
            if time.monotonic() >= deadline:
                raise ToolError("timed out waiting for the application instance in SSM")
            time.sleep(POLL_SECONDS)

    def target_states(self, group: dict[str, Any]) -> list[dict[str, str]]:
        states: list[dict[str, str]] = []
        for target_group_arn in group.get("TargetGroupARNs", []):
            response = self.elbv2.describe_target_health(
                TargetGroupArn=target_group_arn
            )
            for description in response["TargetHealthDescriptions"]:
                health = description["TargetHealth"]
                states.append(
                    {
                        "instance_id": str(description["Target"]["Id"]),
                        "state": str(health["State"]),
                        "reason": str(health.get("Reason", "")),
                    }
                )
        return states

    def status(self) -> None:
        group, database = self.validate_resources()
        instances = [
            {
                "instance_id": str(instance["InstanceId"]),
                "lifecycle_state": str(instance["LifecycleState"]),
                "health_status": str(instance["HealthStatus"]),
            }
            for instance in group.get("Instances", [])
        ]
        instance_ids = [item["instance_id"] for item in instances]
        emit(
            "dev-power-status",
            asg_name=self.settings.asg_name,
            asg_min=int(group["MinSize"]),
            asg_desired=int(group["DesiredCapacity"]),
            asg_max=int(group["MaxSize"]),
            asg_instances=instances,
            rds_identifier=self.settings.database_identifier,
            rds_status=str(database["DBInstanceStatus"]),
            ssm_online_instance_ids=self.online_ssm_instance_ids(instance_ids),
            target_states=self.target_states(group),
        )

    def start(self) -> None:
        group, database = self.validate_resources()
        validate_asg_power_config(group)
        deadline = time.monotonic() + self.settings.timeout_seconds

        action = rds_start_action(str(database["DBInstanceStatus"]))
        if action == "wait-stopped":
            self.wait_for_database("stopped", deadline)
            action = "start"
        if action == "start":
            emit("action", resource="rds", operation="start")
            self.rds.start_db_instance(
                DBInstanceIdentifier=self.settings.database_identifier
            )
        if action in {"start", "wait-available"}:
            self.wait_for_database("available", deadline)

        group = self.describe_asg()
        if int(group["DesiredCapacity"]) != 1:
            emit("action", resource="asg", operation="set-desired-capacity", value=1)
            self.autoscaling.set_desired_capacity(
                AutoScalingGroupName=self.settings.asg_name,
                DesiredCapacity=1,
                HonorCooldown=False,
            )
        group = self.wait_for_asg_capacity(1, deadline)
        in_service_ids = [
            str(instance["InstanceId"])
            for instance in group["Instances"]
            if instance["LifecycleState"] == "InService"
            and instance["HealthStatus"] == "Healthy"
        ]
        self.wait_for_ssm(in_service_ids[0], deadline)
        emit(
            "dev-start-complete",
            asg_desired=1,
            rds_status="available",
            ssm_status="Online",
            target_states=self.target_states(group),
        )

    def stop(self) -> None:
        group, database = self.validate_resources()
        validate_asg_power_config(group)
        deadline = time.monotonic() + self.settings.timeout_seconds

        if int(group["DesiredCapacity"]) != 0 or group.get("Instances"):
            emit("action", resource="asg", operation="set-desired-capacity", value=0)
            self.autoscaling.set_desired_capacity(
                AutoScalingGroupName=self.settings.asg_name,
                DesiredCapacity=0,
                HonorCooldown=False,
            )
        self.wait_for_asg_capacity(0, deadline)

        database = self.describe_database()
        action = rds_stop_action(str(database["DBInstanceStatus"]))
        if action == "wait-available":
            self.wait_for_database("available", deadline)
            action = "stop"
        if action == "stop":
            emit("action", resource="rds", operation="stop")
            self.rds.stop_db_instance(
                DBInstanceIdentifier=self.settings.database_identifier
            )
        if action in {"stop", "wait-stopped"}:
            self.wait_for_database("stopped", deadline)

        emit("dev-stop-complete", asg_desired=0, rds_status="stopped")


def parser() -> argparse.ArgumentParser:
    command_parser = argparse.ArgumentParser(
        description="Start, stop, or inspect the shared development ASG and RDS",
    )
    command_parser.add_argument("--account-id", required=True)
    command_parser.add_argument("--profile", default=DEFAULT_PROFILE)
    command_parser.add_argument("--region", default=AWS_REGION)
    command_parser.add_argument("--project", default=DEFAULT_PROJECT)
    command_parser.add_argument("--operator-role", default=DEFAULT_OPERATOR_ROLE)
    command_parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
    )

    subcommands = command_parser.add_subparsers(dest="command", required=True)
    start = subcommands.add_parser("start")
    start.add_argument("--apply", action="store_true")

    stop = subcommands.add_parser("stop")
    stop.add_argument("--apply", action="store_true")
    stop.add_argument("--workloads-stopped-confirmed", action="store_true")

    subcommands.add_parser("status")
    return command_parser


def settings_from(arguments: argparse.Namespace) -> Settings:
    if not re.fullmatch(r"[0-9]{12}", arguments.account_id):
        raise ToolError("--account-id must be a 12-digit AWS account ID")
    if arguments.region != AWS_REGION:
        raise ToolError(f"--region must be {AWS_REGION}")
    if not re.fullmatch(r"[a-z0-9-]{3,24}", arguments.project):
        raise ToolError("--project must contain 3-24 lowercase letters, digits, or hyphens")
    if not re.fullmatch(r"[A-Za-z0-9+=,.@_-]{1,64}", arguments.operator_role):
        raise ToolError("--operator-role is invalid")
    if not 60 <= arguments.timeout_seconds <= MAX_TIMEOUT_SECONDS:
        raise ToolError(
            f"--timeout-seconds must be between 60 and {MAX_TIMEOUT_SECONDS}"
        )
    return Settings(
        account_id=arguments.account_id,
        profile=arguments.profile,
        region=arguments.region,
        project=arguments.project,
        operator_role=arguments.operator_role,
        timeout_seconds=arguments.timeout_seconds,
    )


def main() -> int:
    arguments = parser().parse_args()
    try:
        settings = settings_from(arguments)
        if arguments.command in {"start", "stop"}:
            require_apply(arguments.apply, arguments.command)
        if arguments.command == "stop":
            require_stop_confirmation(arguments.workloads_stopped_confirmed)

        session = assume_operator(base_session(settings), settings)
        controller = PowerController(session, settings)
        if arguments.command == "start":
            controller.start()
        elif arguments.command == "stop":
            controller.stop()
        else:
            controller.status()
        return 0
    except ToolError as error:
        emit("error", message=str(error))
        return 2
    except ClientError as error:
        details = error.response.get("Error", {})
        emit(
            "error",
            aws_error_code=str(details.get("Code", "Unknown")),
            message=str(details.get("Message", "AWS request failed")),
        )
        return 1
    except KeyboardInterrupt:
        emit("error", message="interrupted; run status before retrying")
        return 130


if __name__ == "__main__":
    sys.exit(main())
