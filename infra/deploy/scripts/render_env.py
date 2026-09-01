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
from pathlib import Path
from typing import Any

MIGRATION_USER = "app_migrator"
ENVIRONMENT_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
PUBLIC_NAMESPACES = frozenset({"backend", "ai"})
INJECTED_NAMES = frozenset({"DB_URL", "DB_MIGRATION_URL"})
SENSITIVE_SUFFIXES = ("_API_KEY", "_PASSWORD", "_PRIVATE_KEY", "_SECRET", "_TOKEN")
API_AI_PROVIDER_KEY_NAMES = frozenset(
    {
        "AI_VLLM_LLM_API_KEY",
        "AI_VLLM_STT_API_KEY",
    }
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
    if "AI_OPENAI_API_KEY" not in result:
        raise SystemExit("AI provider secret must contain AI_OPENAI_API_KEY")
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
    backend = dict(public["backend"])
    ai = dict(public["ai"])
    collisions = (set(backend) | set(ai)) & set(ai_provider_keys)
    if collisions:
        raise SystemExit(
            "AI provider secret collides with public configuration: "
            + ", ".join(sorted(collisions))
        )

    api_provider_keys = {
        name: value
        for name, value in ai_provider_keys.items()
        if name in API_AI_PROVIDER_KEY_NAMES
    }
    api = {**backend, **ai, "DB_URL": runtime_url, **api_provider_keys}
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
