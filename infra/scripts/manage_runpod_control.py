# /// script
# requires-python = ">=3.13,<3.14"
# dependencies = [
#   "boto3>=1.40,<2",
# ]
# ///
"""Register Console-managed RunPod resources and update AWS runtime secrets."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import boto3
from botocore.exceptions import BotoCoreError, ClientError

DEFAULT_PROFILE = "skn30-session"
DEFAULT_REGION = "ap-northeast-2"
DEFAULT_PROJECT = "skn30-final-3team"
DEFAULT_TEMPLATE = Path(__file__).resolve().parents[1] / "runpod" / "template.json"
RUNPOD_REST_URL = "https://rest.runpod.io/v1"
SHARED_POD_NAME = "skn30-f2-serving-dev"
F2_SECRET_NAMES = (
    "AI_VLLM_SLLM_API_KEY",
    "AI_VLLM_STT_API_KEY",
)
IMAGE_PATTERN = re.compile(r"ghcr\.io/[a-z0-9._/-]+@sha256:[0-9a-f]{64}\Z")
F2_KEY_PATTERN = re.compile(r"[A-Za-z0-9_-]{43,128}\Z")
DISCORD_PATTERN = re.compile(
    r"https://(?:discord\.com|discordapp\.com)/api/webhooks/[^\s]+\Z"
)


class ToolError(RuntimeError):
    """An expected operator-safe failure with no credential or response body."""


def emit(event: str, **fields: object) -> None:
    print(json.dumps({"event": event, **fields}, ensure_ascii=False, sort_keys=True))


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def prompt_secret(label: str, validator: Callable[[str], bool]) -> str:
    if not sys.stdin.isatty():
        raise ToolError(f"{label} requires an interactive TTY")
    first = getpass.getpass(f"{label}: ")
    second = getpass.getpass(f"{label} (repeat): ")
    if first != second:
        raise ToolError(f"{label} entries did not match")
    if not validator(first):
        raise ToolError(f"{label} failed validation")
    return first


def nonblank(value: str) -> bool:
    return (
        bool(value)
        and value.strip() == value
        and not any(char.isspace() for char in value)
    )


def as_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ToolError(f"{label} returned an unexpected object")
    return dict(value)


def as_list(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(
        isinstance(item, Mapping) for item in value
    ):
        raise ToolError(f"{label} returned an unexpected collection")
    return [dict(item) for item in value]


@dataclass(frozen=True)
class Settings:
    account_id: str = ""
    profile: str = DEFAULT_PROFILE
    region: str = DEFAULT_REGION
    project: str = DEFAULT_PROJECT
    workload: str = "f2"

    @property
    def prefix(self) -> str:
        return f"{self.project}-dev"

    @property
    def secrets(self) -> dict[str, str]:
        return {
            "ai": f"/{self.prefix}/ai/provider-api-keys",
            "delivery_discord": f"/{self.prefix}/delivery/discord-webhook",
            "alarm_discord": f"/{self.prefix}/observability/alarm-discord-webhook",
            "operator": f"/{self.prefix}/runpod/operator-api-key",
        }

    @property
    def endpoint_parameter(self) -> str:
        return f"/{self.prefix}/ai/" + (
            "AI_VLLM_ENDPOINT_SET"
            if self.workload == "f2"
            else "AI_GENERAL_ENDPOINT_SET"
        )

    @property
    def control_parameter(self) -> str:
        suffix = (
            "RUNPOD_CONTROL_SET" if self.workload == "f2" else "GENERAL_CONTROL_SET"
        )
        return f"/{self.prefix}/runpod/{suffix}"


class AwsStore:
    def __init__(self, settings: Settings, session: Any | None = None):
        self.settings = settings
        session = session or boto3.Session(
            profile_name=settings.profile, region_name=settings.region
        )
        self.sts = session.client("sts")
        self.secrets = session.client("secretsmanager")
        self.ssm = session.client("ssm")
        self.ec2 = session.client("ec2")

    def verify_identity(self) -> str:
        if not re.fullmatch(r"[0-9]{12}", self.settings.account_id):
            raise ToolError("TARGET_ACCOUNT_ID must be an explicit 12-digit account ID")
        identity = self.sts.get_caller_identity()
        account = identity.get("Account")
        if not isinstance(account, str) or not re.fullmatch(r"[0-9]{12}", account):
            raise ToolError("AWS identity did not return a valid account ID")
        if account != self.settings.account_id:
            raise ToolError("the active AWS identity does not match TARGET_ACCOUNT_ID")
        if self.settings.region != DEFAULT_REGION:
            raise ToolError(f"AWS region must be {DEFAULT_REGION}")
        return account

    def describe_secret(self, name: str) -> dict[str, Any] | None:
        try:
            return dict(self.secrets.describe_secret(SecretId=name))
        except ClientError as error:
            if (
                error.response.get("Error", {}).get("Code")
                == "ResourceNotFoundException"
            ):
                return None
            raise

    def secret_value(self, name: str) -> tuple[str, str]:
        try:
            result = self.secrets.get_secret_value(SecretId=name)
        except ClientError as error:
            if (
                error.response.get("Error", {}).get("Code")
                == "ResourceNotFoundException"
            ):
                raise ToolError(
                    f"secret container or AWSCURRENT value is missing: {name}"
                ) from None
            raise
        value = result.get("SecretString")
        version = result.get("VersionId")
        if not isinstance(value, str) or not isinstance(version, str):
            raise ToolError(f"secret has no string AWSCURRENT value: {name}")
        return value, version

    def put_secret(self, name: str, value: str) -> str:
        result = self.secrets.put_secret_value(SecretId=name, SecretString=value)
        version = result.get("VersionId")
        if not isinstance(version, str):
            raise ToolError(f"Secrets Manager did not return a version ID for {name}")
        return version

    def has_current(self, name: str) -> bool:
        description = self.describe_secret(name)
        if description is None:
            raise ToolError(f"Terraform-managed secret container is missing: {name}")
        versions = description.get("VersionIdsToStages", {})
        return any(
            isinstance(stages, list) and "AWSCURRENT" in stages
            for stages in versions.values()
        )

    def control(self) -> dict[str, Any]:
        result = self.ssm.get_parameter(Name=self.settings.control_parameter)
        raw = result.get("Parameter", {}).get("Value")
        try:
            value = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as error:
            raise ToolError("RunPod control parameter is not valid JSON") from error
        return as_object(value, "RunPod control parameter")

    def put_control(self, value: Mapping[str, Any]) -> None:
        self.ssm.put_parameter(
            Name=self.settings.control_parameter,
            Type="String",
            Value=json.dumps(value, separators=(",", ":"), sort_keys=True),
            Overwrite=True,
        )

    def endpoint(self) -> dict[str, Any]:
        result = self.ssm.get_parameter(Name=self.settings.endpoint_parameter)
        raw = result.get("Parameter", {}).get("Value")
        try:
            return as_object(json.loads(raw), "endpoint parameter")
        except (TypeError, json.JSONDecodeError) as error:
            raise ToolError("endpoint parameter is not valid JSON") from error

    def refresh_endpoints(self) -> None:
        filters = [
            {"Name": "tag:Project", "Values": [self.settings.project]},
            {"Name": "tag:Environment", "Values": ["dev"]},
            {"Name": "tag:Name", "Values": [f"{self.settings.prefix}-app"]},
            {"Name": "instance-state-name", "Values": ["running"]},
        ]
        result = self.ec2.describe_instances(Filters=filters)
        instance_ids = [
            instance["InstanceId"]
            for reservation in result.get("Reservations", [])
            for instance in reservation.get("Instances", [])
            if isinstance(instance.get("InstanceId"), str)
        ]
        if len(instance_ids) != 1:
            raise ToolError("expected exactly one running dev application instance")
        command = self.ssm.send_command(
            InstanceIds=instance_ids,
            DocumentName="AWS-RunShellScript",
            Parameters={
                "commands": [
                    "sudo /opt/brokerage/revision/scripts/refresh_ai_endpoints.sh --all"
                ]
            },
            Comment="Refresh AI endpoints after reviewed secret rotation",
        )

        command_id = command["Command"]["CommandId"]
        self.ssm.get_waiter("command_executed").wait(
            CommandId=command_id,
            InstanceId=instance_ids[0],
            WaiterConfig={"Delay": 5, "MaxAttempts": 72},
        )

    def invoke_discord_fixture(self, target: str) -> None:
        function_name = f"{self.settings.prefix}-{'discord-notifier' if target == 'delivery-discord' else 'cloudwatch-alarm-notifier'}"
        lambda_client = boto3.Session(
            profile_name=self.settings.profile, region_name=self.settings.region
        ).client("lambda")
        payload = {
            "fixture": "secret-rotation",
            "target": target,
            "message": "RunPod secret rotation notifier fixture",
        }
        result = lambda_client.invoke(
            FunctionName=function_name,
            InvocationType="RequestResponse",
            Payload=json.dumps(payload).encode(),
        )
        if result.get("FunctionError"):
            raise ToolError(f"{target} notifier fixture failed")


class Requester(Protocol):
    def __call__(self, request: urllib.request.Request, timeout: float) -> bytes: ...


def urlopen_request(request: urllib.request.Request, timeout: float) -> bytes:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


class RunpodClient:
    def __init__(
        self,
        api_key: str,
        requester: Requester = urlopen_request,
        timeout: float = 20,
    ):
        if not nonblank(api_key):
            raise ToolError("RunPod API key is empty or invalid")
        self._api_key = api_key
        self._requester = requester
        self._timeout = timeout

    def _request(
        self, method: str, path: str, payload: Mapping[str, Any] | None = None
    ) -> Any:
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(
            f"{RUNPOD_REST_URL}{path}",
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "skn30-infra/1.0",
            },
        )
        try:
            raw = self._requester(request, self._timeout)
            return json.loads(raw or b"null")
        except urllib.error.HTTPError as error:
            raise ToolError(
                f"RunPod API {method} {path} failed with HTTP {error.code}"
            ) from None
        except (urllib.error.URLError, TimeoutError):
            raise ToolError(f"RunPod API {method} {path} was unreachable") from None
        except json.JSONDecodeError:
            raise ToolError(
                f"RunPod API {method} {path} returned invalid JSON"
            ) from None

    def pods(self) -> list[dict[str, Any]]:
        return as_list(self._request("GET", "/pods"), "RunPod pods")

    def registry(self, registry_id: str) -> dict[str, Any]:
        return as_object(
            self._request("GET", f"/containerregistryauth/{registry_id}"),
            "RunPod registry",
        )

    def template(self, template_id: str) -> dict[str, Any]:
        return as_object(
            self._request("GET", f"/templates/{template_id}"), "RunPod template"
        )


def secret_status(aws: AwsStore) -> dict[str, bool]:
    status = {
        purpose: aws.has_current(name) for purpose, name in aws.settings.secrets.items()
    }
    emit("secret-status", secrets=status, all_ready=all(status.values()))
    return status


def load_ai_secret(aws: AwsStore) -> tuple[dict[str, str], str]:
    raw, version = aws.secret_value(aws.settings.secrets["ai"])
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ToolError("AI provider secret is not valid JSON") from error
    value = as_object(value, "AI provider secret")
    required_names = (
        F2_SECRET_NAMES if aws.settings.workload == "f2" else ("AI_GENERAL_API_KEY",)
    )
    required = {name: value.get(name) for name in required_names}
    if not all(isinstance(item, str) and nonblank(item) for item in required.values()):
        raise ToolError("AI provider secret is missing a required F2 API key")
    if not all(
        F2_KEY_PATTERN.fullmatch(str(required[name])) for name in required_names
    ):
        raise ToolError("AI provider F2 keys failed validation")
    if (
        aws.settings.workload == "f2"
        and required[F2_SECRET_NAMES[0]] == required[F2_SECRET_NAMES[1]]
    ):
        raise ToolError("AI provider F2 keys must differ")
    return {str(key): str(item) for key, item in value.items()}, version


def template_payload(
    path: Path | Mapping[str, Any], image: str, registry_id: str, name: str
) -> dict[str, Any]:
    try:
        source = (
            json.loads(path.read_text(encoding="utf-8"))
            if isinstance(path, Path)
            else dict(path)
        )
    except (OSError, json.JSONDecodeError) as error:
        raise ToolError("RunPod template source is unreadable or invalid") from error
    source = as_object(source, "RunPod template source")
    env = as_object(source.get("env"), "RunPod template env")
    ports = source.get("ports")
    general = str(source.get("name", "")).startswith("skn30-general-serving-")
    expected_ports = {"8000/http"} if general else {"8001/http", "8002/http"}
    if set(ports or []) != expected_ports or any(
        str(port).startswith("22/") for port in ports or []
    ):
        raise ToolError("RunPod template must expose only the two HTTP proxy ports")
    if any(key in source for key in ("volume_in_gb", "network_volume_id")):
        raise ToolError("RunPod template must not attach persistent storage")
    required_refs = {
        name: f"{{{{ RUNPOD_SECRET_{name} }}}}"
        for name in (("AI_GENERAL_API_KEY",) if general else F2_SECRET_NAMES)
    }
    if any(env.get(key) != value for key, value in required_refs.items()):
        raise ToolError(
            "RunPod template F2 Secret references do not match the contract"
        )
    if {
        "HF_TOKEN",
        "HUGGING_FACE_HUB_TOKEN",
        "HUGGINGFACE_HUB_TOKEN",
        "HUGGINGFACE_TOKEN",
        "HUGGING_FACE_TOKEN",
        "HF_ACCESS_TOKEN",
        "HF_API_TOKEN",
    } & env.keys():
        raise ToolError("public-model Template must not inject a Hugging Face token")
    command = source.get("docker_start_cmd", "")
    docker_start = [item for item in str(command).split(",") if item]
    return {
        "imageName": image,
        "name": name,
        "category": "NVIDIA",
        "containerDiskInGb": int(source.get("container_disk_gb", 30)),
        "containerRegistryAuthId": registry_id,
        "dockerEntrypoint": [],
        "dockerStartCmd": docker_start,
        "env": env,
        "isPublic": False,
        "isServerless": False,
        "ports": list(ports),
        "readme": "Private ephemeral F2 SLLM/STT runtime; no SSH or persistent volume",
        "volumeInGb": 0,
        "volumeMountPath": "/workspace",
    }


def resource_id(value: Mapping[str, Any], label: str) -> str:
    identifier = value.get("id")
    if not isinstance(identifier, str) or not identifier:
        raise ToolError(f"{label} has no ID")
    return identifier


def validate_template(actual: Mapping[str, Any], expected: Mapping[str, Any]) -> None:
    normalized = dict(actual)
    for field, default in (
        ("dockerEntrypoint", []),
        ("isPublic", False),
        ("isServerless", False),
        ("volumeInGb", 0),
    ):
        if normalized.get(field) is None:
            normalized[field] = default
    if isinstance(normalized.get("ports"), list):
        normalized["ports"] = sorted(normalized["ports"])
    expected = {**expected, "ports": sorted(expected["ports"])}
    fields = (
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
    )
    mismatches = [
        field for field in fields if normalized.get(field) != expected.get(field)
    ]
    if mismatches:
        raise ToolError(
            "existing RunPod template differs in: " + ", ".join(sorted(mismatches))
        )
    if normalized["volumeInGb"] != 0 or any(
        str(port).startswith("22/") for port in normalized.get("ports", [])
    ):
        raise ToolError("existing RunPod template has a volume or SSH port")


class Registrar:
    """Validate existing Console resources, then write one complete SSM record."""

    def __init__(self, aws: AwsStore, template: Path = DEFAULT_TEMPLATE):
        self.aws = aws
        self.template = template

    def register(
        self, image: str, template_id: str, registry_id: str, *, apply: bool = False
    ) -> dict[str, Any]:
        if not IMAGE_PATTERN.fullmatch(image):
            raise ToolError(
                "image must be a lowercase GHCR reference pinned by sha256 digest"
            )
        for identifier in (template_id, registry_id):
            if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", identifier) is None:
                raise ToolError(
                    "Template and registry IDs must be explicit identifiers"
                )
        try:
            source = as_object(json.loads(self.template.read_text()), "Template source")
        except (OSError, json.JSONDecodeError) as error:
            raise ToolError(
                "RunPod template source is unreadable or invalid"
            ) from error
        if image.split("@", 1)[0] != str(source.get("image", "")).split("@", 1)[0]:
            raise ToolError("image must come from the workflow-owned GHCR repository")
        self.aws.verify_identity()
        # Read the Terraform-managed container before attempting any write.
        previous = self.aws.control()
        load_ai_secret(self.aws)
        operator, _ = self.aws.secret_value(self.aws.settings.secrets["operator"])
        client = RunpodClient(operator)
        ensure_offline_without_pod(self.aws, client)
        if resource_id(client.registry(registry_id), "RunPod registry") != registry_id:
            raise ToolError("RunPod registry ID does not match the requested ID")
        expected = template_payload(source, image, registry_id, str(source["name"]))
        actual = client.template(template_id)
        if resource_id(actual, "RunPod template") != template_id:
            raise ToolError("RunPod Template ID does not match the requested ID")
        validate_template(actual, expected)
        record = {
            "schema_version": 2,
            "status": "ready",
            "image": image,
            "template_id": template_id,
            "registry_auth_id": registry_id,
        }
        changed = any(
            previous.get(key) != value for key, value in record.items()
        ) or bool(set(previous) - set(record) - {"updated_at"})
        if apply and changed:
            self.aws.put_control({**record, "updated_at": now()})
        emit(
            "runpod-register-complete" if apply else "runpod-register-plan",
            **record,
            changed=changed,
            mutates=apply and changed,
        )
        return record


def ensure_offline_without_pod(aws: AwsStore, client: RunpodClient) -> None:
    if aws.endpoint().get("status") != "offline":
        raise ToolError("operation requires the endpoint to be offline")
    pods = [
        pod
        for pod in client.pods()
        if pod.get("name")
        == (
            SHARED_POD_NAME
            if aws.settings.workload == "f2"
            else "skn30-general-serving-dev"
        )
    ]
    if pods:
        raise ToolError("operation requires no shared RunPod Pod")


def rotate_secret(aws: AwsStore, target: str) -> None:
    """Also accepts first-time values; external resources stay Console-owned."""
    names = aws.settings.secrets
    if target == "f2":
        operator, _ = aws.secret_value(names["operator"])
        ensure_offline_without_pod(aws, RunpodClient(operator))
        ai = {}
        if aws.has_current(names["ai"]):
            raw, _ = aws.secret_value(names["ai"])
            try:
                ai = as_object(json.loads(raw), "AI provider secret")
            except json.JSONDecodeError as error:
                raise ToolError("AI provider secret is not valid JSON") from error
        keys = [
            prompt_secret(
                f"{name} (same value as RunPod Console)",
                lambda value: bool(F2_KEY_PATTERN.fullmatch(value)),
            )
            for name in F2_SECRET_NAMES
        ]
        if keys[0] == keys[1]:
            raise ToolError("AI provider F2 keys must differ")
        ai.update(zip(F2_SECRET_NAMES, keys, strict=True))
        version = aws.put_secret(names["ai"], json.dumps(ai, separators=(",", ":")))
    elif target == "general":
        if aws.settings.workload != "general":
            raise ToolError("general rotation requires --workload general")
        operator, _ = aws.secret_value(names["operator"])
        ensure_offline_without_pod(aws, RunpodClient(operator))
        raw, _ = aws.secret_value(names["ai"])
        ai = as_object(json.loads(raw), "AI provider secret")
        ai["AI_GENERAL_API_KEY"] = prompt_secret(
            "AI_GENERAL_API_KEY (same as RunPod Console)",
            lambda value: bool(F2_KEY_PATTERN.fullmatch(value)),
        )
        version = aws.put_secret(names["ai"], json.dumps(ai))
    elif target == "ghcr":
        value = {
            "username": prompt_secret("GHCR username", nonblank),
            "token": prompt_secret("GHCR read:packages token", nonblank),
        }
        version = aws.put_secret(
            f"/{aws.settings.prefix}/runpod/ghcr-registry", json.dumps(value)
        )
    elif target == "openai":
        ai = {}
        if aws.has_current(names["ai"]):
            raw, _ = aws.secret_value(names["ai"])
            try:
                ai = as_object(json.loads(raw), "AI provider secret")
            except json.JSONDecodeError as error:
                raise ToolError("AI provider secret is not valid JSON") from error
        ai["AI_OPENAI_API_KEY"] = prompt_secret("OpenAI API key", nonblank)
        version = aws.put_secret(names["ai"], json.dumps(ai, separators=(",", ":")))
        aws.refresh_endpoints()
    elif target in {"delivery-discord", "alarm-discord"}:
        purpose = (
            "delivery_discord" if target == "delivery-discord" else "alarm_discord"
        )
        value = prompt_secret(
            target, lambda item: bool(DISCORD_PATTERN.fullmatch(item))
        )
        version = aws.put_secret(names[purpose], value)
        aws.invoke_discord_fixture(target)
    elif target == "runpod-operator":
        purpose = "operator"
        value = prompt_secret(target, nonblank)
        RunpodClient(value).pods()
        version = aws.put_secret(names[purpose], value)
    else:
        raise ToolError(f"unsupported rotation target: {target}")
    emit("secret-rotate-complete", target=target, version_id=version)


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--account-id", default=os.environ.get("TARGET_ACCOUNT_ID", ""))
    cli.add_argument("--profile", default=DEFAULT_PROFILE)
    cli.add_argument("--region", default=DEFAULT_REGION)
    cli.add_argument("--project", default=DEFAULT_PROJECT)
    cli.add_argument("--workload", choices=("f2", "general"), default="f2")
    cli.add_argument("--template", type=Path)
    commands = cli.add_subparsers(dest="command", required=True)
    for command in ("register-plan", "register"):
        register = commands.add_parser(command)
        register.add_argument("image")
        register.add_argument("template_id")
        register.add_argument("registry_id")
    commands.add_parser("secret-status")
    rotate = commands.add_parser("secret-rotate")
    rotate.add_argument(
        "target",
        choices=(
            "openai",
            "f2",
            "general",
            "ghcr",
            "delivery-discord",
            "alarm-discord",
            "runpod-operator",
        ),
    )
    return cli


def main() -> int:
    args = parser().parse_args()
    settings = Settings(
        account_id=args.account_id,
        profile=args.profile,
        region=args.region,
        project=args.project,
        workload=args.workload,
    )
    try:
        aws = AwsStore(settings)
        if args.command in {"register-plan", "register"}:
            Registrar(
                aws,
                args.template
                or (
                    DEFAULT_TEMPLATE
                    if args.workload == "f2"
                    else DEFAULT_TEMPLATE.parent.parent
                    / "serving"
                    / "general-template.json"
                ),
            ).register(
                args.image,
                args.template_id,
                args.registry_id,
                apply=args.command == "register",
            )
        elif args.command == "secret-status":
            aws.verify_identity()
            secret_status(aws)
        else:
            aws.verify_identity()
            rotate_secret(aws, args.target)
        return 0
    except (ToolError, BotoCoreError, ClientError) as error:
        if isinstance(error, ToolError):
            message = str(error)
        else:
            message = (
                "AWS operation failed; inspect the local AWS session and permissions"
            )
        emit("error", message=message[:1000])
        return 2
    except KeyboardInterrupt:
        emit(
            "error",
            message="interrupted; inspect secret-status and control status before retrying",
        )
        return 130


if __name__ == "__main__":
    sys.exit(main())
