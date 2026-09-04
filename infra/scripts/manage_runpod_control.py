# /// script
# requires-python = ">=3.13,<3.14"
# dependencies = [
#   "boto3>=1.40,<2",
# ]
# ///
"""Bootstrap and rotate RunPod operational resources without persisting secrets."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
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
RUNPOD_GRAPHQL_URL = "https://api.runpod.io/graphql"
RUNPOD_GRAPHQL_USER_AGENT = "Mozilla/5.0 (compatible; SKN30-RunPod-Bootstrap/1.0)"
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


def generated_f2_key() -> str:
    value = secrets.token_urlsafe(32)
    if not F2_KEY_PATTERN.fullmatch(value):  # pragma: no cover - defensive
        raise ToolError("generated F2 key failed its local format check")
    return value


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
    return bool(value) and value.strip() == value and not any(char.isspace() for char in value)


def as_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ToolError(f"{label} returned an unexpected object")
    return dict(value)


def as_list(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        raise ToolError(f"{label} returned an unexpected collection")
    return [dict(item) for item in value]


@dataclass(frozen=True)
class Settings:
    account_id: str = ""
    profile: str = DEFAULT_PROFILE
    region: str = DEFAULT_REGION
    project: str = DEFAULT_PROJECT

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
            "monitor": f"/{self.prefix}/runpod/monitor-api-key",
            "ghcr": f"/{self.prefix}/runpod/ghcr-registry",
        }

    @property
    def endpoint_parameter(self) -> str:
        return f"/{self.prefix}/ai/AI_VLLM_ENDPOINT_SET"

    @property
    def control_parameter(self) -> str:
        return f"/{self.prefix}/runpod/RUNPOD_CONTROL_SET"


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
            if error.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
                return None
            raise

    def secret_value(self, name: str) -> tuple[str, str]:
        try:
            result = self.secrets.get_secret_value(SecretId=name)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
                raise ToolError(f"secret container or AWSCURRENT value is missing: {name}") from None
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
        self.ssm.send_command(
            InstanceIds=instance_ids,
            DocumentName="AWS-RunShellScript",
            Parameters={
                "commands": [
                    "sudo /opt/brokerage/revision/scripts/refresh_ai_endpoints.sh"
                ]
            },
            Comment="Refresh AI endpoints after reviewed secret rotation",
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
            },
        )
        try:
            raw = self._requester(request, self._timeout)
            return json.loads(raw or b"null")
        except urllib.error.HTTPError as error:
            raise ToolError(f"RunPod API {method} {path} failed with HTTP {error.code}") from None
        except (urllib.error.URLError, TimeoutError):
            raise ToolError(f"RunPod API {method} {path} was unreachable") from None
        except json.JSONDecodeError:
            raise ToolError(f"RunPod API {method} {path} returned invalid JSON") from None

    def graphql(self, query: str, variables: Mapping[str, Any] | None = None) -> Any:
        request = urllib.request.Request(
            f"{RUNPOD_GRAPHQL_URL}?{urllib.parse.urlencode({'api_key': self._api_key})}",
            data=json.dumps({"query": query, "variables": variables or {}}).encode(),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": RUNPOD_GRAPHQL_USER_AGENT,
            },
        )
        try:
            raw = self._requester(request, self._timeout)
            result = json.loads(raw)
        except urllib.error.HTTPError as error:
            raise ToolError(f"RunPod GraphQL failed with HTTP {error.code}") from None
        except (urllib.error.URLError, TimeoutError):
            raise ToolError("RunPod GraphQL was unreachable") from None
        except json.JSONDecodeError:
            raise ToolError("RunPod GraphQL returned invalid JSON") from None
        if not isinstance(result, Mapping) or result.get("errors"):
            raise ToolError("RunPod GraphQL rejected the operation")
        return result.get("data")

    def pods(self) -> list[dict[str, Any]]:
        return as_list(self._request("GET", "/pods"), "RunPod pods")

    def registries(self) -> list[dict[str, Any]]:
        return as_list(
            self._request("GET", "/containerregistryauth"), "RunPod registries"
        )

    def create_registry(self, name: str, username: str, password: str) -> dict[str, Any]:
        return as_object(
            self._request(
                "POST",
                "/containerregistryauth",
                {"name": name, "username": username, "password": password},
            ),
            "RunPod registry",
        )

    def templates(self) -> list[dict[str, Any]]:
        return as_list(self._request("GET", "/templates"), "RunPod templates")

    def create_template(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return as_object(
            self._request("POST", "/templates", payload), "RunPod template"
        )

    def secrets(self) -> dict[str, str]:
        query = "query ManagedSecrets { myself { secrets { id name } } }"
        data = as_object(self.graphql(query), "RunPod GraphQL data")
        myself = as_object(data.get("myself"), "RunPod identity")
        items = as_list(myself.get("secrets", []), "RunPod secrets")
        records: dict[str, str] = {}
        for item in items:
            name, secret_id = item.get("name"), item.get("id")
            if not isinstance(name, str) or not isinstance(secret_id, str):
                raise ToolError("RunPod secret metadata is incomplete")
            if name in records:
                raise ToolError(f"RunPod has duplicate Secret name: {name}")
            records[name] = secret_id
        return records

    def secret_names(self) -> set[str]:
        return set(self.secrets())

    def create_secret(self, name: str, value: str) -> None:
        # RunPod does not publish the GraphQL input type name. JSON string
        # escaping is compatible with GraphQL string literals, and the query
        # is sent only in the HTTPS request body (never argv or logs).
        mutation = (
            "mutation CreateSecret { secretCreate(input: {"
            f"name: {json.dumps(name)}, value: {json.dumps(value)}"
            "}) { id name } }"
        )
        data = as_object(self.graphql(mutation), "RunPod GraphQL data")
        created = as_object(data.get("secretCreate"), "RunPod created Secret")
        if created.get("name") != name:
            raise ToolError("RunPod created Secret name does not match the request")
        resource_id(created, "RunPod Secret")

    def delete_secret(self, name: str) -> None:
        secret_id = self.secrets().get(name)
        if secret_id is None:
            return
        mutation = (
            "mutation DeleteSecret { "
            f"secretDelete(id: {json.dumps(secret_id)})"
            " }"
        )
        self.graphql(mutation)


def secret_status(aws: AwsStore) -> dict[str, bool]:
    status = {purpose: aws.has_current(name) for purpose, name in aws.settings.secrets.items()}
    emit("secret-status", secrets=status, all_ready=all(status.values()))
    return status


def initialise_missing_secrets(aws: AwsStore) -> None:
    names = aws.settings.secrets
    missing = [purpose for purpose, name in names.items() if not aws.has_current(name)]
    if not missing:
        return
    if "ai" in missing:
        openai = prompt_secret("OpenAI API key", nonblank)
        payload = {
            "AI_OPENAI_API_KEY": openai,
            "AI_VLLM_SLLM_API_KEY": generated_f2_key(),
            "AI_VLLM_STT_API_KEY": generated_f2_key(),
        }
        aws.put_secret(names["ai"], json.dumps(payload, separators=(",", ":")))
    for purpose, label in (
        ("delivery_discord", "Delivery Discord webhook"),
        ("alarm_discord", "Alarm Discord webhook"),
        ("operator", "RunPod read-write API key"),
        ("monitor", "RunPod read-only API key"),
    ):
        if purpose in missing:
            validator = (
                (lambda value: bool(DISCORD_PATTERN.fullmatch(value)))
                if "discord" in purpose
                else nonblank
            )
            aws.put_secret(names[purpose], prompt_secret(label, validator))
    if "ghcr" in missing:
        username = prompt_secret("GHCR username", nonblank)
        password = prompt_secret("GHCR read-only PAT", nonblank)
        aws.put_secret(
            names["ghcr"],
            json.dumps({"username": username, "password": password}, separators=(",", ":")),
        )


def load_ai_secret(aws: AwsStore) -> tuple[dict[str, str], str]:
    raw, version = aws.secret_value(aws.settings.secrets["ai"])
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ToolError("AI provider secret is not valid JSON") from error
    value = as_object(value, "AI provider secret")
    required = {name: value.get(name) for name in ("AI_OPENAI_API_KEY", *F2_SECRET_NAMES)}
    if not all(isinstance(item, str) and nonblank(item) for item in required.values()):
        raise ToolError("AI provider secret is missing a required flat AI_*_API_KEY")
    if not all(F2_KEY_PATTERN.fullmatch(str(required[name])) for name in F2_SECRET_NAMES):
        raise ToolError("AI provider F2 keys failed validation")
    if required[F2_SECRET_NAMES[0]] == required[F2_SECRET_NAMES[1]]:
        raise ToolError("AI provider F2 keys must differ")
    return {str(key): str(item) for key, item in value.items()}, version


def load_ghcr_secret(aws: AwsStore) -> tuple[str, str]:
    raw, _ = aws.secret_value(aws.settings.secrets["ghcr"])
    try:
        value = as_object(json.loads(raw), "GHCR secret")
    except json.JSONDecodeError as error:
        raise ToolError("GHCR secret is not valid JSON") from error
    username, password = value.get("username"), value.get("password")
    if not isinstance(username, str) or not isinstance(password, str):
        raise ToolError("GHCR secret requires username and password fields")
    if not nonblank(username) or not nonblank(password):
        raise ToolError("GHCR credential fields cannot be blank")
    return username, password


def template_payload(
    path: Path, image: str, registry_id: str, name: str
) -> dict[str, Any]:
    try:
        source = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ToolError("RunPod template source is unreadable or invalid") from error
    source = as_object(source, "RunPod template source")
    env = as_object(source.get("env"), "RunPod template env")
    ports = source.get("ports")
    if set(ports or []) != {"8001/http", "8002/http"} or any(
        str(port).startswith("22/") for port in ports or []
    ):
        raise ToolError("RunPod template must expose only the two HTTP proxy ports")
    if any(key in source for key in ("volume_in_gb", "network_volume_id")):
        raise ToolError("RunPod template must not attach persistent storage")
    required_refs = {
        name: f"{{{{ RUNPOD_SECRET_{name} }}}}" for name in F2_SECRET_NAMES
    }
    if any(env.get(key) != value for key, value in required_refs.items()):
        raise ToolError("RunPod template F2 Secret references do not match the contract")
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
        "ports": ports,
        "readme": "Private ephemeral F2 SLLM/STT runtime; no SSH or persistent volume",
        "volumeInGb": 0,
        "volumeMountPath": "/workspace",
    }


def resource_id(value: Mapping[str, Any], label: str) -> str:
    identifier = value.get("id")
    if not isinstance(identifier, str) or not identifier:
        raise ToolError(f"{label} has no ID")
    return identifier


def validate_registry(actual: Mapping[str, Any], expected_name: str) -> str:
    if actual.get("name") != expected_name:
        raise ToolError("RunPod registry name does not match the requested name")
    return resource_id(actual, "RunPod registry")


def one_named(items: Sequence[Mapping[str, Any]], name: str, label: str) -> dict[str, Any] | None:
    matches = [dict(item) for item in items if item.get("name") == name]
    if len(matches) > 1:
        raise ToolError(f"duplicate RunPod {label} name: {name}")
    return matches[0] if matches else None


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
    mismatches = [field for field in fields if normalized.get(field) != expected.get(field)]
    if mismatches:
        raise ToolError(
            "existing RunPod template differs in: " + ", ".join(sorted(mismatches))
        )
    if normalized["volumeInGb"] != 0 or any(
        str(port).startswith("22/") for port in normalized.get("ports", [])
    ):
        raise ToolError("existing RunPod template has a volume or SSH port")


def is_resumable_template(
    control: Mapping[str, Any], image: str, template: Mapping[str, Any]
) -> bool:
    return (
        control.get("status") == "provisioning"
        and control.get("image") == image
        and control.get("template_id") is None
        and isinstance(template.get("id"), str)
    )


class Bootstrapper:
    def __init__(self, aws: AwsStore, template: Path = DEFAULT_TEMPLATE):
        self.aws = aws
        self.template = template

    def _validate_image(self, image: str) -> None:
        if not IMAGE_PATTERN.fullmatch(image):
            raise ToolError("image must be a lowercase GHCR reference pinned by sha256 digest")
        try:
            source = as_object(
                json.loads(self.template.read_text(encoding="utf-8")),
                "RunPod template source",
            )
        except (OSError, json.JSONDecodeError) as error:
            raise ToolError("RunPod template source is unreadable or invalid") from error
        configured = source.get("image")
        if not isinstance(configured, str) or "@sha256:" not in configured:
            raise ToolError("RunPod template source has no GHCR image repository")
        expected_repository = configured.split("@", 1)[0]
        if image.split("@", 1)[0] != expected_repository:
            raise ToolError("image must come from the workflow-owned GHCR repository")

    def plan(self, image: str) -> dict[str, Any]:
        self._validate_image(image)
        account = self.aws.verify_identity()
        status = {
            purpose: self.aws.has_current(name)
            for purpose, name in self.aws.settings.secrets.items()
        }
        control = self.aws.control()
        actions = [
            f"populate:{purpose}" for purpose, ready in status.items() if not ready
        ]
        if all(status.values()):
            operator, _ = self.aws.secret_value(self.aws.settings.secrets["operator"])
            client = RunpodClient(operator)
            client.pods()
            if not (
                control.get("status") in {"ready", "provisioning"}
                and control.get("image") == image
            ):
                ensure_offline_without_pod(self.aws, client)
            generation = self._generation(control, image)
            registry_name = f"{self.aws.settings.prefix}-ghcr-g{generation}"
            template_name = f"{self.aws.settings.prefix}-f2-template-g{generation}"
            registry = one_named(client.registries(), registry_name, "registry")
            if registry is not None and control.get("registry_auth_id") != registry.get(
                "id"
            ):
                raise ToolError(
                    "existing registry name is not owned by the control document"
                )
            if registry is None:
                actions.append(f"create-registry:{registry_name}")
            template = one_named(client.templates(), template_name, "template")
            if template is None:
                actions.append(f"create-template:{template_name}")
            elif registry is not None:
                expected = template_payload(
                    self.template,
                    image,
                    resource_id(registry, "RunPod registry"),
                    template_name,
                )
                recorded_template = control.get("template_id")
                if recorded_template != template.get("id") and not is_resumable_template(
                    control, image, template
                ):
                    raise ToolError(
                        "existing template name is not owned by the control document"
                    )
                validate_template(template, expected)
            runpod_names = client.secret_names()
            actions.extend(
                f"create-runpod-secret:{name}"
                for name in F2_SECRET_NAMES
                if name not in runpod_names
            )
        actions.append("write-control:ready")
        result = {
            "account_id": account,
            "region": self.aws.settings.region,
            "image": image,
            "current_status": control.get("status", "unknown"),
            "actions": actions,
            "mutates": False,
        }
        emit("runpod-bootstrap-plan", **result)
        return result

    @staticmethod
    def _generation(control: Mapping[str, Any], image: str) -> int:
        generation = int(control.get("generation", 0) or 0)
        if control.get("status") == "provisioning" and control.get("image") == image:
            return max(1, generation)
        if control.get("status") == "ready" and control.get("image") == image:
            return max(1, generation)
        return max(1, generation + 1)

    def apply(self, image: str) -> dict[str, Any]:
        self._validate_image(image)
        self.aws.verify_identity()
        initialise_missing_secrets(self.aws)
        ai, ai_version = load_ai_secret(self.aws)
        operator, _ = self.aws.secret_value(self.aws.settings.secrets["operator"])
        monitor, _ = self.aws.secret_value(self.aws.settings.secrets["monitor"])
        username, password = load_ghcr_secret(self.aws)
        client = RunpodClient(operator)
        client.pods()
        RunpodClient(monitor).pods()
        control = self.aws.control()
        if not (
            control.get("status") in {"ready", "provisioning"}
            and control.get("image") == image
        ):
            ensure_offline_without_pod(self.aws, client)
        generation = self._generation(control, image)
        registry_name = f"{self.aws.settings.prefix}-ghcr-g{generation}"
        template_name = f"{self.aws.settings.prefix}-f2-template-g{generation}"
        provisioning = {
            **control,
            "schema_version": 1,
            "status": "provisioning",
            "generation": generation,
            "image": image,
            "updated_at": now(),
        }
        self.aws.put_control(provisioning)

        runpod_names = client.secret_names()
        synced = control.get("ai_provider_secret_version_id") == ai_version
        existing = set(F2_SECRET_NAMES) & runpod_names
        if existing and not synced:
            raise ToolError(
                "RunPod F2 Secret exists but the AWS version is not recorded as synchronized"
            )
        provisioning["ai_provider_secret_version_id"] = ai_version
        self.aws.put_control(provisioning)
        for name in F2_SECRET_NAMES:
            if name not in runpod_names:
                client.create_secret(name, ai[name])
        if not set(F2_SECRET_NAMES).issubset(client.secret_names()):
            raise ToolError("RunPod F2 Secrets were not visible after creation")

        registry = one_named(client.registries(), registry_name, "registry")
        recorded_registry = control.get("registry_auth_id")
        if registry is not None and recorded_registry != registry.get("id"):
            raise ToolError("existing registry name is not owned by the control document")
        if registry is None:
            registry = client.create_registry(registry_name, username, password)
        registry_id = validate_registry(registry, registry_name)
        provisioning["registry_auth_id"] = registry_id
        self.aws.put_control(provisioning)

        expected = template_payload(self.template, image, registry_id, template_name)
        template = one_named(client.templates(), template_name, "template")
        recorded_template = control.get("template_id")
        if template is None:
            template = client.create_template(expected)
        elif recorded_template != template.get("id") and not is_resumable_template(
            control, image, template
        ):
            raise ToolError("existing template name is not owned by the control document")
        validate_template(template, expected)
        template_id = resource_id(template, "RunPod template")
        ready = {
            **provisioning,
            "status": "ready",
            "registry_auth_id": registry_id,
            "template_id": template_id,
            "ai_provider_secret_version_id": ai_version,
            "updated_at": now(),
        }
        self.aws.put_control(ready)
        result = {
            "status": "ready",
            "generation": generation,
            "image": image,
            "registry_auth_id": registry_id,
            "template_id": template_id,
            "ai_provider_secret_version_id": ai_version,
        }
        emit("runpod-bootstrap-complete", **result)
        return result


def ensure_offline_without_pod(aws: AwsStore, client: RunpodClient) -> None:
    if aws.endpoint().get("status") != "offline":
        raise ToolError("operation requires the endpoint to be offline")
    pods = [pod for pod in client.pods() if pod.get("name") == SHARED_POD_NAME]
    if pods:
        raise ToolError("operation requires no shared RunPod Pod")


def rotate_secret(aws: AwsStore, target: str, template: Path) -> None:
    names = aws.settings.secrets
    control = aws.control()
    operator, _ = aws.secret_value(names["operator"])
    client = RunpodClient(operator)
    if target == "f2":
        ensure_offline_without_pod(aws, client)
        if control.get("status") == "provisioning" and control.get("operation") == "rotate-f2":
            ai, version = load_ai_secret(aws)
            pending = dict(control)
        else:
            ai, _ = load_ai_secret(aws)
            ai[F2_SECRET_NAMES[0]] = generated_f2_key()
            ai[F2_SECRET_NAMES[1]] = generated_f2_key()
            version = aws.put_secret(
                names["ai"], json.dumps(ai, separators=(",", ":"))
            )
            pending = {
                **control,
                "status": "provisioning",
                "operation": "rotate-f2",
                "ai_provider_secret_version_id": version,
                "updated_at": now(),
            }
            aws.put_control(pending)
        existing = client.secret_names()
        for name in F2_SECRET_NAMES:
            if name in existing:
                client.delete_secret(name)
            client.create_secret(name, ai[name])
        aws.put_control({**pending, "status": "ready", "operation": None, "updated_at": now()})
        emit("secret-rotate-complete", target=target, version_id=version)
        return
    if target == "ghcr":
        ensure_offline_without_pod(aws, client)
        username = prompt_secret("GHCR username", nonblank)
        password = prompt_secret("GHCR read-only PAT", nonblank)
        version = aws.put_secret(
            names["ghcr"],
            json.dumps({"username": username, "password": password}, separators=(",", ":")),
        )
        image = control.get("image")
        if not isinstance(image, str) or not IMAGE_PATTERN.fullmatch(image):
            raise ToolError("ready control document has no immutable image")
        generation = int(control.get("generation", 0)) + 1
        registry_name = f"{aws.settings.prefix}-ghcr-g{generation}"
        template_name = f"{aws.settings.prefix}-f2-template-g{generation}"
        pending = {
            **control,
            "status": "provisioning",
            "operation": "rotate-ghcr",
            "generation": generation,
            "updated_at": now(),
        }
        aws.put_control(pending)
        registry = client.create_registry(registry_name, username, password)
        registry_id = validate_registry(registry, registry_name)
        expected = template_payload(template, image, registry_id, template_name)
        created = client.create_template(expected)
        validate_template(created, expected)
        ready = {
            **pending,
            "status": "ready",
            "operation": None,
            "registry_auth_id": registry_id,
            "template_id": resource_id(created, "RunPod template"),
            "updated_at": now(),
        }
        aws.put_control(ready)
        emit("secret-rotate-complete", target=target, version_id=version, generation=generation)
        return
    if target == "openai":
        ai, _ = load_ai_secret(aws)
        ai["AI_OPENAI_API_KEY"] = prompt_secret("OpenAI API key", nonblank)
        version = aws.put_secret(names["ai"], json.dumps(ai, separators=(",", ":")))
        aws.refresh_endpoints()
    elif target in {"delivery-discord", "alarm-discord"}:
        purpose = "delivery_discord" if target == "delivery-discord" else "alarm_discord"
        value = prompt_secret(target, lambda item: bool(DISCORD_PATTERN.fullmatch(item)))
        version = aws.put_secret(names[purpose], value)
        aws.invoke_discord_fixture(target)
    elif target in {"runpod-operator", "runpod-monitor"}:
        purpose = "operator" if target == "runpod-operator" else "monitor"
        value = prompt_secret(target, nonblank)
        RunpodClient(value).pods()
        version = aws.put_secret(names[purpose], value)
        follow_up = (
            "wait for the next successful monitor, then disable the previous key in RunPod Console"
        )
        emit("secret-rotate-complete", target=target, version_id=version, follow_up=follow_up)
        return
    else:  # pragma: no cover - argparse prevents this
        raise ToolError(f"unsupported rotation target: {target}")
    emit("secret-rotate-complete", target=target, version_id=version)


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--account-id", default=os.environ.get("TARGET_ACCOUNT_ID", ""))
    cli.add_argument("--profile", default=DEFAULT_PROFILE)
    cli.add_argument("--region", default=DEFAULT_REGION)
    cli.add_argument("--project", default=DEFAULT_PROJECT)
    cli.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    commands = cli.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("bootstrap-plan")
    plan.add_argument("image")
    apply = commands.add_parser("bootstrap")
    apply.add_argument("image")
    commands.add_parser("secret-status")
    rotate = commands.add_parser("secret-rotate")
    rotate.add_argument(
        "target",
        choices=(
            "openai",
            "f2",
            "ghcr",
            "delivery-discord",
            "alarm-discord",
            "runpod-operator",
            "runpod-monitor",
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
    )
    try:
        aws = AwsStore(settings)
        if args.command == "bootstrap-plan":
            Bootstrapper(aws, args.template).plan(args.image)
        elif args.command == "bootstrap":
            Bootstrapper(aws, args.template).apply(args.image)
        elif args.command == "secret-status":
            aws.verify_identity()
            secret_status(aws)
        else:
            aws.verify_identity()
            rotate_secret(aws, args.target, args.template)
        return 0
    except (ToolError, BotoCoreError, ClientError) as error:
        if isinstance(error, ToolError):
            message = str(error)
        else:
            message = "AWS operation failed; inspect the local AWS session and permissions"
        emit("error", message=message[:1000])
        return 2
    except KeyboardInterrupt:
        emit("error", message="interrupted; inspect secret-status and control status before retrying")
        return 130


if __name__ == "__main__":
    sys.exit(main())
