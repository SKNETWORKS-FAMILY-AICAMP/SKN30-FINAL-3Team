#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
import urllib.parse
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

MIGRATION_USER = "app_migrator"
ENVIRONMENT_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
PUBLIC_NAMESPACES = frozenset({"backend", "ai"})
IGNORED_OPERATIONAL_PARAMETER_PATHS = frozenset({"runpod/RUNPOD_CONTROL_SET"})
INJECTED_NAMES = frozenset({"DB_URL", "DB_MIGRATION_URL"})
SENSITIVE_SUFFIXES = ("_API_KEY", "_PASSWORD", "_PRIVATE_KEY", "_SECRET", "_TOKEN")
REQUIRED_AI_PROVIDER_KEYS = frozenset(
    {
        "AI_OPENAI_API_KEY",
        "AI_VLLM_SLLM_API_KEY",
        "AI_VLLM_STT_API_KEY",
    }
)
F2_API_KEY = re.compile(r"^[A-Za-z0-9_-]{43,128}$")
AI_VLLM_ENDPOINT_SET_NAME = "AI_VLLM_ENDPOINT_SET"
AI_VLLM_BASE_URL_NAMES = frozenset(
    {"AI_VLLM_SLLM_BASE_URL", "AI_VLLM_STT_BASE_URL", "AI_F2_PROVIDER_STATUS"}
)
AI_VLLM_ENDPOINT_SET_FIELDS = frozenset(
    {
        "revision",
        "status",
        "pod_id",
        "sllm_release_id",
        "sllm_base_url",
        "stt_base_url",
        "updated_at",
    }
)
RUNPOD_POD_ID = re.compile(r"^[a-z0-9]{5,64}$")
SLLM_RELEASE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
RFC3339_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)


def aws(*args: str) -> str:
    try:
        result = subprocess.run(
            ["aws", *args],
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as error:
        operation = " ".join(args[:2])
        raise SystemExit(
            f"AWS CLI operation failed: {operation} (exit status {error.returncode})"
        ) from None
    return result.stdout.strip()


def required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing deployment metadata: {name}")
    return value


def quote(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def json_object(raw: str, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        raise SystemExit(f"{label} must contain a JSON object") from None
    if not isinstance(value, dict):
        raise SystemExit(f"{label} must contain a JSON object")
    return value


def endpoint_set_json_object(raw: str) -> dict[str, Any]:
    duplicate_names: set[str] = set()

    def collect(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name, value in pairs:
            if name in result:
                duplicate_names.add(name)
            result[name] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=collect)
    except json.JSONDecodeError:
        raise SystemExit("AI vLLM endpoint set must contain a JSON object") from None
    if not isinstance(value, dict):
        raise SystemExit("AI vLLM endpoint set must contain a JSON object")
    if duplicate_names:
        raise SystemExit(
            "AI vLLM endpoint set contains duplicate fields: "
            + ", ".join(sorted(duplicate_names))
        )
    return value


def validate_runpod_base_url(value: Any, *, pod_id: str, port: int) -> str:
    if not isinstance(value, str):
        raise SystemExit("AI vLLM endpoint URLs must be strings")
    try:
        parsed = urllib.parse.urlsplit(value)
        parsed_port = parsed.port
    except ValueError:
        raise SystemExit("AI vLLM endpoint URL is malformed") from None
    expected_host = f"{pod_id}-{port}.proxy.runpod.net"
    if (
        parsed.scheme != "https"
        or parsed.netloc != expected_host
        or parsed.path != "/v1"
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
        or parsed_port is not None
    ):
        raise SystemExit(
            f"AI vLLM endpoint URL must be exactly https://{expected_host}/v1"
        )
    return value


def parse_ai_vllm_endpoint_set(raw: str) -> dict[str, str]:
    payload = endpoint_set_json_object(raw)
    fields = set(payload)
    if fields != AI_VLLM_ENDPOINT_SET_FIELDS:
        missing = AI_VLLM_ENDPOINT_SET_FIELDS - fields
        unexpected = fields - AI_VLLM_ENDPOINT_SET_FIELDS
        details = []
        if missing:
            details.append("missing " + ", ".join(sorted(missing)))
        if unexpected:
            details.append("unexpected " + ", ".join(sorted(unexpected)))
        raise SystemExit("Invalid AI vLLM endpoint set schema: " + "; ".join(details))

    revision = payload["revision"]
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise SystemExit("AI vLLM endpoint set revision must be a non-negative integer")

    status = payload["status"]
    if status not in {"active", "offline"}:
        raise SystemExit("AI vLLM endpoint set status must be active or offline")

    updated_at = payload["updated_at"]
    if not isinstance(updated_at, str) or not RFC3339_TIMESTAMP.fullmatch(updated_at):
        raise SystemExit("AI vLLM endpoint set updated_at must be RFC3339")
    try:
        parsed_time = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    except ValueError:
        raise SystemExit("AI vLLM endpoint set updated_at must be RFC3339") from None
    if parsed_time.utcoffset() is None:
        raise SystemExit("AI vLLM endpoint set updated_at must include an offset")

    pod_id = payload["pod_id"]
    release_id = payload["sllm_release_id"]
    if status == "offline":
        if any(
            value is not None
            for value in (
                pod_id,
                release_id,
                payload["sllm_base_url"],
                payload["stt_base_url"],
            )
        ):
            raise SystemExit(
                "offline AI vLLM endpoint set must have null Pod, release and URLs"
            )
        return {"AI_F2_PROVIDER_STATUS": "offline"}

    if (
        not isinstance(pod_id, str)
        or pod_id == "unconfigured"
        or not RUNPOD_POD_ID.fullmatch(pod_id)
    ):
        raise SystemExit("active AI vLLM endpoint set pod_id is invalid")
    if not isinstance(release_id, str) or not SLLM_RELEASE_ID.fullmatch(release_id):
        raise SystemExit("active AI vLLM endpoint set sllm_release_id is invalid")
    return {
        "AI_F2_PROVIDER_STATUS": "active",
        "AI_VLLM_SLLM_BASE_URL": validate_runpod_base_url(
            payload["sllm_base_url"], pod_id=pod_id, port=8001
        ),
        "AI_VLLM_STT_BASE_URL": validate_runpod_base_url(
            payload["stt_base_url"], pod_id=pod_id, port=8002
        ),
    }


def expand_ai_vllm_endpoint_set(
    public: Mapping[str, Mapping[str, str]],
) -> dict[str, dict[str, str]]:
    expanded = {namespace: dict(public[namespace]) for namespace in PUBLIC_NAMESPACES}
    ai = expanded["ai"]
    raw = ai.pop(AI_VLLM_ENDPOINT_SET_NAME, None)
    if raw is None:
        raise SystemExit("Missing public parameter: AI_VLLM_ENDPOINT_SET")
    collisions = AI_VLLM_BASE_URL_NAMES & ai.keys()
    if collisions:
        raise SystemExit(
            "AI vLLM endpoint set collides with legacy public parameters: "
            + ", ".join(sorted(collisions))
        )
    ai.update(parse_ai_vllm_endpoint_set(raw))
    return expanded


def validate_public_name(name: str) -> None:
    if not ENVIRONMENT_NAME.fullmatch(name):
        raise SystemExit(f"Invalid public environment variable name: {name}")
    if (
        name in INJECTED_NAMES
        or name.startswith("AWS_")
        or name.endswith(SENSITIVE_SUFFIXES)
    ):
        raise SystemExit(f"Reserved public environment variable name: {name}")


def parse_public_parameters(
    payload: Mapping[str, Any], prefix: str
) -> dict[str, dict[str, str]]:
    base = prefix.rstrip("/")
    if not base.startswith("/"):
        raise SystemExit("APP_PARAMETER_PREFIX must be an absolute SSM path")
    items = payload.get("Parameters")
    if not isinstance(items, list):
        raise SystemExit("SSM response must contain Parameters")

    result = {namespace: {} for namespace in PUBLIC_NAMESPACES}
    owners: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            raise SystemExit("SSM parameter entry must be an object")
        full_name = item.get("Name")
        value = item.get("Value")
        if not isinstance(full_name, str) or not isinstance(value, str):
            raise SystemExit("SSM parameter entry must contain string Name and Value")
        expected_prefix = f"{base}/"
        if not full_name.startswith(expected_prefix):
            raise SystemExit("SSM returned a parameter outside APP_PARAMETER_PREFIX")
        parts = full_name.removeprefix(expected_prefix).split("/")
        if "/".join(parts) in IGNORED_OPERATIONAL_PARAMETER_PATHS:
            continue
        if len(parts) != 2 or parts[0] not in PUBLIC_NAMESPACES:
            raise SystemExit(f"Unsupported public parameter path: {full_name}")
        namespace, name = parts
        validate_public_name(name)
        if name in owners:
            raise SystemExit(
                f"Duplicate public environment variable {name} in {owners[name]} and {namespace}"
            )
        owners[name] = namespace
        result[namespace][name] = value
    return result


def parse_ai_provider_keys(raw: str) -> dict[str, str]:
    payload = json_object(raw, label="AI provider secret")
    result: dict[str, str] = {}
    for name, value in payload.items():
        if (
            not isinstance(name, str)
            or not ENVIRONMENT_NAME.fullmatch(name)
            or not name.startswith("AI_")
            or not name.endswith("_API_KEY")
        ):
            raise SystemExit(
                "AI provider secret contains an invalid environment variable name"
            )
        if not isinstance(value, str) or not value.strip():
            raise SystemExit(f"AI provider secret value is empty: {name}")
        result[name] = value
    missing = REQUIRED_AI_PROVIDER_KEYS - result.keys()
    if missing:
        raise SystemExit(
            "AI provider secret is missing required keys: " + ", ".join(sorted(missing))
        )
    for name in ("AI_VLLM_SLLM_API_KEY", "AI_VLLM_STT_API_KEY"):
        if F2_API_KEY.fullmatch(result[name]) is None:
            raise SystemExit(
                f"{name} must be 43 to 128 URL-safe letters, digits, underscores, or hyphens"
            )
    if result["AI_VLLM_SLLM_API_KEY"] == result["AI_VLLM_STT_API_KEY"]:
        raise SystemExit("AI vLLM SLLM and STT API keys must be different")
    return result


def runtime_database_url(
    secret: Mapping[str, Any], ca_path: str
) -> tuple[str, str, str, str]:
    values: dict[str, str] = {}
    for name in ("host", "dbname", "username", "password"):
        value = secret.get(name)
        if not isinstance(value, str) or not value:
            raise SystemExit(f"Backend runtime database secret is missing {name}")
        values[name] = value

    raw_port = secret.get("port", 5432)
    try:
        port_number = int(raw_port)
    except (TypeError, ValueError):
        raise SystemExit(
            "Backend runtime database secret port must be an integer"
        ) from None
    if not 1 <= port_number <= 65535:
        raise SystemExit("Backend runtime database secret port is out of range")
    port = str(port_number)
    url = (
        f"postgresql+psycopg://{quote(values['username'])}:{quote(values['password'])}@"
        f"{values['host']}:{port}/{values['dbname']}"
        f"?sslmode=verify-full&sslrootcert={ca_path}"
    )
    return url, values["host"], port, values["dbname"]


def build_process_environments(
    *,
    public: Mapping[str, Mapping[str, str]],
    runtime_url: str,
    migration_url: str,
    ai_provider_keys: Mapping[str, str],
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    expanded_public = expand_ai_vllm_endpoint_set(public)
    backend = expanded_public["backend"]
    ai = expanded_public["ai"]
    collisions = (set(backend) | set(ai)) & set(ai_provider_keys)
    if collisions:
        raise SystemExit(
            "AI provider secret collides with public configuration: "
            + ", ".join(sorted(collisions))
        )

    api = {
        **backend,
        **ai,
        "AI_VLLM_SLLM_API_KEY": ai_provider_keys["AI_VLLM_SLLM_API_KEY"],
        "AI_VLLM_STT_API_KEY": ai_provider_keys["AI_VLLM_STT_API_KEY"],
        "DB_URL": runtime_url,
    }
    worker = {**backend, **ai, "DB_URL": runtime_url, **ai_provider_keys}
    migration = {"DB_MIGRATION_URL": migration_url}
    return api, worker, migration


def write_env(path: Path, values: Mapping[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            for name, value in sorted(values.items()):
                if not ENVIRONMENT_NAME.fullmatch(name):
                    raise SystemExit(f"Invalid environment variable name: {name}")
                if "\n" in value or "\r" in value:
                    raise SystemExit(f"{name} contains a newline")
                stream.write(f"{name}={value}\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-output", required=True, type=Path)
    parser.add_argument("--worker-output", required=True, type=Path)
    parser.add_argument("--migration-output", required=True, type=Path)
    args = parser.parse_args()

    region = required_environment("AWS_REGION")
    parameter_prefix = required_environment("APP_PARAMETER_PREFIX")
    runtime_secret_id = required_environment("BACKEND_RUNTIME_DATABASE_SECRET_ID")
    ai_secret_id = required_environment("AI_PROVIDER_SECRET_ID")
    ca_path = required_environment("RDS_CA_CONTAINER_FILE")
    if not ca_path.startswith("/"):
        raise SystemExit("RDS_CA_CONTAINER_FILE must be an absolute container path")

    runtime_secret = json_object(
        aws(
            "secretsmanager",
            "get-secret-value",
            "--secret-id",
            runtime_secret_id,
            "--query",
            "SecretString",
            "--output",
            "text",
            "--region",
            region,
        ),
        label="Backend runtime database secret",
    )
    runtime_url, host, port, database = runtime_database_url(runtime_secret, ca_path)

    public = parse_public_parameters(
        json_object(
            aws(
                "ssm",
                "get-parameters-by-path",
                "--path",
                parameter_prefix,
                "--recursive",
                "--output",
                "json",
                "--region",
                region,
            ),
            label="SSM response",
        ),
        parameter_prefix,
    )
    ai_provider_keys = parse_ai_provider_keys(
        aws(
            "secretsmanager",
            "get-secret-value",
            "--secret-id",
            ai_secret_id,
            "--query",
            "SecretString",
            "--output",
            "text",
            "--region",
            region,
        )
    )

    token = aws(
        "rds",
        "generate-db-auth-token",
        "--hostname",
        host,
        "--port",
        port,
        "--username",
        MIGRATION_USER,
        "--region",
        region,
    )
    migration_url = (
        f"postgresql+psycopg://{MIGRATION_USER}:{quote(token)}@"
        f"{host}:{port}/{database}?sslmode=verify-full&sslrootcert={ca_path}"
    )
    api, worker, migration = build_process_environments(
        public=public,
        runtime_url=runtime_url,
        migration_url=migration_url,
        ai_provider_keys=ai_provider_keys,
    )

    write_env(args.api_output, api)
    write_env(args.worker_output, worker)
    write_env(args.migration_output, migration)


if __name__ == "__main__":
    main()
