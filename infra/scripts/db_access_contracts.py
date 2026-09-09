"""Shared PostgreSQL role, credential and connection-format contracts.

No AWS calls or database connections occur during import.
"""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

import psycopg
from psycopg import sql

DB_MASTER_USER = "dbadmin"
DB_RUNTIME_USER = "app_runtime"
DB_MIGRATOR_USER = "app_migrator"
DB_OWNER_ROLE = "app_owner"
DB_RW_ROLE = "app_rw"


class ToolError(RuntimeError):
    """An expected error whose message is safe to print."""


@dataclass(frozen=True)
class Settings:
    account_id: str
    profile: str
    region: str
    project: str
    local_port: int
    operator_role: str

    @property
    def environment(self) -> str:
        return "dev"

    @property
    def name_prefix(self) -> str:
        return f"{self.project}-{self.environment}"

    @property
    def db_identifier(self) -> str:
        return f"{self.name_prefix}-postgres"

    @property
    def runtime_secret_name(self) -> str:
        return f"/{self.name_prefix}/backend/runtime-database-url"

    @property
    def operator_role_arn(self) -> str:
        return f"arn:aws:iam::{self.account_id}:role/{self.operator_role}"


@dataclass(frozen=True)
class DatabaseTarget:
    identifier: str
    resource_id: str
    endpoint: str
    port: int
    database: str
    master_secret_arn: str


def role_exists(cursor: psycopg.Cursor[Any], role_name: str) -> bool:
    cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role_name,))
    return cursor.fetchone() is not None


def ensure_role(
    cursor: psycopg.Cursor[Any],
    role_name: str,
    *,
    login: bool,
    password: str | None = None,
) -> None:
    if not role_exists(cursor, role_name):
        cursor.execute(
            sql.SQL("CREATE ROLE {} {}").format(
                sql.Identifier(role_name),
                sql.SQL("LOGIN" if login else "NOLOGIN"),
            )
        )
    cursor.execute(
        sql.SQL("ALTER ROLE {} {}").format(
            sql.Identifier(role_name),
            sql.SQL("LOGIN" if login else "NOLOGIN"),
        )
    )
    if password is not None:
        cursor.execute(
            sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                sql.Identifier(role_name),
                sql.Literal(password),
            )
        )


def grant_role(cursor: psycopg.Cursor[Any], granted: str, member: str) -> None:
    cursor.execute(
        sql.SQL("GRANT {} TO {}").format(
            sql.Identifier(granted),
            sql.Identifier(member),
        )
    )


def configure_fixed_roles(
    cursor: psycopg.Cursor[Any],
    target: DatabaseTarget,
    runtime_password: str,
) -> None:
    ensure_role(cursor, DB_OWNER_ROLE, login=False)
    ensure_role(cursor, DB_RW_ROLE, login=False)
    ensure_role(cursor, DB_RUNTIME_USER, login=True, password=runtime_password)
    ensure_role(cursor, DB_MIGRATOR_USER, login=True)
    cursor.execute(
        sql.SQL("ALTER ROLE {} PASSWORD NULL").format(sql.Identifier(DB_MIGRATOR_USER))
    )

    grant_role(cursor, DB_OWNER_ROLE, DB_MASTER_USER)
    grant_role(cursor, DB_RW_ROLE, DB_RUNTIME_USER)
    grant_role(cursor, "rds_iam", DB_MIGRATOR_USER)
    grant_role(cursor, DB_OWNER_ROLE, DB_MIGRATOR_USER)

    cursor.execute(sql.SQL("REVOKE CREATE ON SCHEMA public FROM PUBLIC"))
    cursor.execute(
        sql.SQL("GRANT USAGE, CREATE ON SCHEMA public TO {}").format(
            sql.Identifier(DB_OWNER_ROLE)
        )
    )
    cursor.execute(
        sql.SQL("GRANT CONNECT ON DATABASE {} TO {}, {}").format(
            sql.Identifier(target.database),
            sql.Identifier(DB_OWNER_ROLE),
            sql.Identifier(DB_RW_ROLE),
        )
    )
    cursor.execute(
        sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(DB_RW_ROLE))
    )
    cursor.execute(
        sql.SQL(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}"
        ).format(sql.Identifier(DB_RW_ROLE))
    )
    cursor.execute(
        sql.SQL(
            "GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO {}"
        ).format(sql.Identifier(DB_RW_ROLE))
    )
    cursor.execute(
        sql.SQL(
            "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public "
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}"
        ).format(sql.Identifier(DB_OWNER_ROLE), sql.Identifier(DB_RW_ROLE))
    )
    cursor.execute(
        sql.SQL(
            "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public "
            "GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO {}"
        ).format(sql.Identifier(DB_OWNER_ROLE), sql.Identifier(DB_RW_ROLE))
    )


def runtime_secret_payload(
    target: DatabaseTarget,
    password: str,
) -> dict[str, object]:
    return {
        "engine": "postgres",
        "host": target.endpoint,
        "port": target.port,
        "dbname": target.database,
        "username": DB_RUNTIME_USER,
        "password": password,
    }


def parse_runtime_secret(secret_string: str) -> dict[str, object]:
    try:
        value = json.loads(secret_string)
    except json.JSONDecodeError as error:
        raise ToolError("runtime secret is not valid JSON") from error
    if (
        not isinstance(value, dict)
        or value.get("username") != DB_RUNTIME_USER
        or not isinstance(value.get("password"), str)
        or not value["password"]
    ):
        raise ToolError("runtime secret has an unexpected structure")
    return value


def validate_runtime_secret_target(
    target: DatabaseTarget, secret: dict[str, object]
) -> None:
    expected = {
        "engine": "postgres",
        "host": target.endpoint,
        "port": target.port,
        "dbname": target.database,
        "username": DB_RUNTIME_USER,
    }
    actual = {name: secret.get(name) for name in expected}
    if actual != expected:
        raise ToolError("runtime secret database target metadata does not match RDS")


def verify_fixed_role_contract(cursor: psycopg.Cursor[Any]) -> None:
    required = {
        DB_OWNER_ROLE,
        DB_RW_ROLE,
        DB_RUNTIME_USER,
        DB_MIGRATOR_USER,
    }
    cursor.execute(
        "SELECT rolname, rolcanlogin FROM pg_roles WHERE rolname = ANY(%s)",
        (list(required),),
    )
    roles = {str(name): bool(can_login) for name, can_login in cursor.fetchall()}
    if set(roles) != required:
        raise ToolError("required database roles are missing")
    if roles[DB_OWNER_ROLE] or roles[DB_RW_ROLE]:
        raise ToolError("database capability roles must not allow login")
    if not roles[DB_RUNTIME_USER] or not roles[DB_MIGRATOR_USER]:
        raise ToolError("database application users must allow login")

    for member, granted in (
        (DB_RUNTIME_USER, DB_RW_ROLE),
        (DB_MIGRATOR_USER, "rds_iam"),
        (DB_MIGRATOR_USER, DB_OWNER_ROLE),
    ):
        cursor.execute("SELECT pg_has_role(%s, %s, 'member')", (member, granted))
        membership = cursor.fetchone()
        if membership is None or not membership[0]:
            raise ToolError(f"{member} is missing required database role {granted}")


def render_client_info(
    settings: Settings,
    target: DatabaseTarget,
    instance_id: str,
    username: str,
    token: str,
    ca_bundle: Path,
) -> str:
    tunnel_params = json.dumps(
        {
            "host": [target.endpoint],
            "portNumber": [str(target.port)],
            "localPortNumber": [str(settings.local_port)],
        },
        separators=(",", ":"),
    )
    psql_environment = {
        "PGHOST": target.endpoint,
        "PGHOSTADDR": "127.0.0.1",
        "PGPORT": str(settings.local_port),
        "PGDATABASE": target.database,
        "PGUSER": username,
        "PGSSLMODE": "verify-full",
        "PGSSLROOTCERT": str(ca_bundle),
    }
    psql_command = " ".join(
        [
            *(f"{key}={shlex.quote(value)}" for key, value in psql_environment.items()),
            "psql -W",
        ]
    )

    return "\n".join(
        [
            "================================================================================",
            "                      RDS 개발 DB 접속 정보 (IAM DB Auth)                      ",
            "================================================================================",
            f"• Database Name  : {target.database}",
            f"• IAM Username   : {username}",
            "• Local Host     : 127.0.0.1",
            f"• Local Port     : {settings.local_port}",
            f"• Remote RDS Host: {target.endpoint}:{target.port}",
            f"• App EC2 Target : {instance_id}",
            f"• CA Bundle Path : {ca_bundle}",
            "--------------------------------------------------------------------------------",
            "• IAM DB Token (비밀번호 / 15분 유효, 아래 프롬프트나 클라이언트에만 붙여넣기):",
            token,
            "  주의: 터미널 로그·화면 공유에 노출하지 말고 사용 후 클립보드를 비운다.",
            "--------------------------------------------------------------------------------",
            "1. SSM 포트 포워딩 터널 실행 (별도 터미널에서 실행):",
            (
                f"   aws ssm start-session --target {instance_id} "
                "--document-name AWS-StartPortForwardingSessionToRemoteHost "
                f"--parameters {shlex.quote(tunnel_params)} --region {settings.region}"
            ),
            "",
            "2. psql 접속 (터널 실행 후 명령을 실행하고 Password 프롬프트에 토큰 붙여넣기):",
            f"   {psql_command}",
            "",
            "3. DBeaver / DataGrip 설정:",
            "   - Host     : 127.0.0.1",
            f"   - Port     : {settings.local_port}",
            f"   - Database : {target.database}",
            f"   - Username : {username}",
            "   - Password : [위의 IAM DB Token 문자열]",
            "   - SSL Mode : verify-ca",
            f"   - Root CA  : {ca_bundle}",
            "   - localhost 터널에서는 RDS 호스트명 검증 대신 CA 체인을 검증한다.",
            "================================================================================",
        ]
    )


def migration_url(
    target: DatabaseTarget,
    local_port: int,
    ca_bundle: Path,
    username: str,
    token: str,
) -> str:
    query = urlencode(
        {
            "hostaddr": "127.0.0.1",
            "sslmode": "verify-full",
            "sslrootcert": str(ca_bundle),
        }
    )
    return (
        f"postgresql+psycopg://{quote(username, safe='')}:{quote(token, safe='')}"
        f"@{target.endpoint}:{local_port}/{target.database}?{query}"
    )
