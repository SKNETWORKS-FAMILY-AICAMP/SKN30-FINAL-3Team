#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import urllib.parse
from pathlib import Path

PREFIX = "/skn30-final-3team-dev"
RUNTIME_SECRET = f"{PREFIX}/backend/runtime-database-url"
MIGRATION_USER = "app_migrator"


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


def quote(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def write_env(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for name, value in sorted(values.items()):
        if "\n" in value or "\r" in value:
            raise SystemExit(f"{name} contains a newline")
        lines.append(f"{name}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o600)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-output", required=True, type=Path)
    parser.add_argument("--migration-output", required=True, type=Path)
    args = parser.parse_args()

    region = os.environ.get("AWS_REGION", "ap-northeast-2")
    secret = json.loads(
        aws(
            "secretsmanager",
            "get-secret-value",
            "--secret-id",
            RUNTIME_SECRET,
            "--query",
            "SecretString",
            "--output",
            "text",
            "--region",
            region,
        )
    )
    host = str(secret["host"])
    port = str(secret.get("port", 5432))
    database = str(secret["dbname"])
    username = str(secret["username"])
    password = str(secret["password"])
    ca_path = os.environ.get("RDS_CA_CONTAINER_FILE", "").strip()
    if not ca_path.startswith("/"):
        raise SystemExit("RDS_CA_CONTAINER_FILE must be an absolute container path")

    parameter_payload = json.loads(
        aws(
            "ssm",
            "get-parameters-by-path",
            "--path",
            PREFIX,
            "--recursive",
            "--with-decryption",
            "--output",
            "json",
            "--region",
            region,
        )
    )
    parameters = {
        item["Name"].removeprefix(f"{PREFIX}/").split("/")[-1]: item["Value"]
        for item in parameter_payload["Parameters"]
    }
    parameters["DB_URL"] = (
        f"postgresql+psycopg://{quote(username)}:{quote(password)}@"
        f"{host}:{port}/{database}?sslmode=verify-full&sslrootcert={ca_path}"
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
    migration = dict(parameters)
    migration["DB_MIGRATION_URL"] = (
        f"postgresql+psycopg://{MIGRATION_USER}:{quote(token)}@"
        f"{host}:{port}/{database}?sslmode=verify-full&sslrootcert={ca_path}"
    )

    write_env(args.runtime_output, parameters)
    write_env(args.migration_output, migration)


if __name__ == "__main__":
    main()
