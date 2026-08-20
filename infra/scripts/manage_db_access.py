# /// script
# requires-python = ">=3.13,<3.14"
# dependencies = [
#   "boto3>=1.40,<2",
#   "psycopg[binary]>=3.3,<4",
# ]
# ///
"""Manage development PostgreSQL roles without storing credentials in Terraform state."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shlex
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self
from urllib.parse import quote, urlencode

import boto3
import psycopg
from botocore.exceptions import ClientError
from psycopg import sql

AWS_REGION = "ap-northeast-2"
DEFAULT_PROFILE = "skn30-session"
DEFAULT_PROJECT = "skn30-final-3team"
DEFAULT_LOCAL_PORT = 15432
DB_NAME = "brokerage"
DB_MASTER_USER = "dbadmin"
DB_RUNTIME_USER = "app_runtime"
DB_MIGRATOR_USER = "app_migrator"
DB_OWNER_ROLE = "app_owner"
DB_RW_ROLE = "app_rw"
TEAM_GROUP = "team-db-tunnel"
MANAGED_ROLE_COMMENT = "Managed by infra manage_db_access from team-db-tunnel"
RDS_CA_URL = "https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem"
REPO_ROOT = Path(__file__).resolve().parents[2]


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


def emit(event: str, **fields: object) -> None:
    print(json.dumps({"event": event, **fields}, ensure_ascii=False, sort_keys=True))


def require_apply(enabled: bool, command: str) -> None:
    if not enabled:
        raise ToolError(
            f"{command} changes external state; rerun with --apply after review"
        )


def base_session(settings: Settings) -> boto3.Session:
    session = boto3.Session(profile_name=settings.profile, region_name=settings.region)
    identity = session.client("sts").get_caller_identity()
    if identity["Account"] != settings.account_id:
        raise ToolError("current AWS account does not match --account-id")
    if str(identity["Arn"]).endswith(":root"):
        raise ToolError("root credentials are not allowed")
    return session


def assume_operator(session: boto3.Session, settings: Settings) -> boto3.Session:
    response = session.client("sts").assume_role(
        RoleArn=settings.operator_role_arn,
        RoleSessionName="db-access-management",
        DurationSeconds=3600,
    )
    credentials = response["Credentials"]
    return boto3.Session(
        aws_access_key_id=credentials["AccessKeyId"],
        aws_secret_access_key=credentials["SecretAccessKey"],
        aws_session_token=credentials["SessionToken"],
        region_name=settings.region,
    )


def session_environment(session: boto3.Session) -> dict[str, str]:
    credentials = session.get_credentials()
    if credentials is None:
        raise ToolError("AWS credentials are unavailable")
    frozen = credentials.get_frozen_credentials()
    environment = os.environ.copy()
    environment.pop("AWS_PROFILE", None)
    environment.update(
        {
            "AWS_ACCESS_KEY_ID": frozen.access_key,
            "AWS_SECRET_ACCESS_KEY": frozen.secret_key,
            "AWS_REGION": session.region_name or AWS_REGION,
            "AWS_DEFAULT_REGION": session.region_name or AWS_REGION,
        }
    )
    if frozen.token:
        environment["AWS_SESSION_TOKEN"] = frozen.token
    return environment


def describe_database(session: boto3.Session, settings: Settings) -> DatabaseTarget:
    response = session.client("rds").describe_db_instances(
        DBInstanceIdentifier=settings.db_identifier
    )
    instances = response["DBInstances"]
    if len(instances) != 1:
        raise ToolError("expected exactly one development RDS instance")
    instance = instances[0]
    if not instance.get("IAMDatabaseAuthenticationEnabled"):
        raise ToolError("RDS IAM database authentication is not enabled")
    secret = instance.get("MasterUserSecret") or {}
    secret_arn = secret.get("SecretArn")
    if not secret_arn:
        raise ToolError("RDS master secret is unavailable")
    return DatabaseTarget(
        identifier=instance["DBInstanceIdentifier"],
        resource_id=instance["DbiResourceId"],
        endpoint=instance["Endpoint"]["Address"],
        port=int(instance["Endpoint"]["Port"]),
        database=instance.get("DBName") or DB_NAME,
        master_secret_arn=secret_arn,
    )


def find_app_instance(session: boto3.Session, settings: Settings) -> str:
    response = session.client("ec2").describe_instances(
        Filters=[
            {"Name": "instance-state-name", "Values": ["running"]},
            {"Name": "tag:Project", "Values": [settings.project]},
            {"Name": "tag:Environment", "Values": [settings.environment]},
            {"Name": "tag:ManagedBy", "Values": ["Terraform"]},
        ]
    )
    instance_ids = [
        instance["InstanceId"]
        for reservation in response["Reservations"]
        for instance in reservation["Instances"]
    ]
    if len(instance_ids) != 1:
        raise ToolError("expected exactly one running tagged development app instance")
    return instance_ids[0]


def ensure_ca_bundle() -> Path:
    cache_path = Path.home() / ".cache" / "skn30-final-3team" / "rds-global-bundle.pem"
    if cache_path.exists() and cache_path.stat().st_size > 1024:
        return cache_path
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache_path.with_suffix(".tmp")
    with urllib.request.urlopen(RDS_CA_URL, timeout=30) as response:
        content = response.read()
    if b"BEGIN CERTIFICATE" not in content:
        raise ToolError("downloaded RDS CA bundle is invalid")
    temporary.write_bytes(content)
    temporary.chmod(0o644)
    temporary.replace(cache_path)
    return cache_path


class PortForward:
    def __init__(
        self,
        session: boto3.Session,
        instance_id: str,
        target: DatabaseTarget,
        local_port: int,
    ) -> None:
        self.session = session
        self.instance_id = instance_id
        self.target = target
        self.local_port = local_port
        self.process: subprocess.Popen[bytes] | None = None

    def __enter__(self) -> Self:
        if (
            shutil.which("aws") is None
            or shutil.which("session-manager-plugin") is None
        ):
            raise ToolError("AWS CLI and session-manager-plugin are required")
        parameters = json.dumps(
            {
                "host": [self.target.endpoint],
                "portNumber": [str(self.target.port)],
                "localPortNumber": [str(self.local_port)],
            },
            separators=(",", ":"),
        )
        self.process = subprocess.Popen(
            [
                "aws",
                "ssm",
                "start-session",
                "--target",
                self.instance_id,
                "--document-name",
                "AWS-StartPortForwardingSessionToRemoteHost",
                "--parameters",
                parameters,
                "--region",
                self.session.region_name or AWS_REGION,
            ],
            env=session_environment(self.session),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise ToolError("SSM port-forwarding session failed to start")
            try:
                with socket.create_connection(
                    ("127.0.0.1", self.local_port), timeout=0.5
                ):
                    return self
            except OSError:
                time.sleep(0.25)
        raise ToolError("timed out waiting for the local SSM tunnel")

    def __exit__(self, *_: object) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)


def connection_parameters(
    target: DatabaseTarget,
    local_port: int,
    ca_bundle: Path,
    username: str,
    password: str,
) -> dict[str, object]:
    return {
        "host": target.endpoint,
        "hostaddr": "127.0.0.1",
        "port": local_port,
        "dbname": target.database,
        "user": username,
        "password": password,
        "sslmode": "verify-full",
        "sslrootcert": str(ca_bundle),
        "connect_timeout": 10,
    }


@contextmanager
def master_connection(
    session: boto3.Session,
    target: DatabaseTarget,
    local_port: int,
    ca_bundle: Path,
) -> Iterator[psycopg.Connection[Any]]:
    response = session.client("secretsmanager").get_secret_value(
        SecretId=target.master_secret_arn
    )
    secret_value = json.loads(response["SecretString"])
    username = secret_value.get("username")
    password = secret_value.get("password")
    if username != DB_MASTER_USER or not password:
        raise ToolError("RDS master secret has an unexpected structure")
    with psycopg.connect(
        **connection_parameters(target, local_port, ca_bundle, username, password)
    ) as connection:
        yield connection


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


def list_group_users(session: boto3.Session) -> set[str]:
    iam = session.client("iam")
    users: set[str] = set()
    marker: str | None = None
    while True:
        arguments: dict[str, object] = {"GroupName": TEAM_GROUP}
        if marker:
            arguments["Marker"] = marker
        response = iam.get_group(**arguments)
        users.update(user["UserName"] for user in response["Users"])
        if not response.get("IsTruncated"):
            return users
        marker = response.get("Marker")


def sync_personal_roles(
    cursor: psycopg.Cursor[Any],
    desired_users: set[str],
) -> tuple[list[str], list[str]]:
    cursor.execute(
        "SELECT rolname FROM pg_roles WHERE shobj_description(oid, 'pg_authid') = %s",
        (MANAGED_ROLE_COMMENT,),
    )
    existing_users = {row[0] for row in cursor.fetchall()}
    enabled: list[str] = []
    disabled: list[str] = []

    for username in sorted(desired_users):
        ensure_role(cursor, username, login=True)
        cursor.execute(
            sql.SQL("ALTER ROLE {} PASSWORD NULL").format(sql.Identifier(username))
        )
        grant_role(cursor, "rds_iam", username)
        grant_role(cursor, DB_OWNER_ROLE, username)
        cursor.execute(
            sql.SQL("COMMENT ON ROLE {} IS {}").format(
                sql.Identifier(username),
                sql.Literal(MANAGED_ROLE_COMMENT),
            )
        )
        enabled.append(username)

    for username in sorted(existing_users - desired_users):
        cursor.execute(
            sql.SQL("REVOKE {} FROM {}").format(
                sql.Identifier(DB_OWNER_ROLE),
                sql.Identifier(username),
            )
        )
        cursor.execute(
            sql.SQL("REVOKE {} FROM {}").format(
                sql.Identifier("rds_iam"),
                sql.Identifier(username),
            )
        )
        cursor.execute(
            sql.SQL("ALTER ROLE {} NOLOGIN").format(sql.Identifier(username))
        )
        cursor.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE usename = %s AND pid <> pg_backend_pid()",
            (username,),
        )
        disabled.append(username)

    return enabled, disabled


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


def get_runtime_secret(
    session: boto3.Session,
    settings: Settings,
) -> tuple[dict[str, object] | None, str | None]:
    try:
        response = session.client("secretsmanager").get_secret_value(
            SecretId=settings.runtime_secret_name,
            VersionStage="AWSCURRENT",
        )
    except ClientError as error:
        if error.response["Error"]["Code"] == "ResourceNotFoundException":
            return None, None
        raise
    return parse_runtime_secret(response["SecretString"]), response["VersionId"]


def new_password() -> str:
    return secrets.token_urlsafe(48)


def bootstrap(settings: Settings, apply: bool) -> None:
    direct = base_session(settings)
    operator = assume_operator(direct, settings)
    target = describe_database(operator, settings)
    instance_id = find_app_instance(operator, settings)
    team_users = list_group_users(operator)
    current_secret, _ = get_runtime_secret(operator, settings)

    emit(
        "bootstrap-plan",
        apply=apply,
        database=target.identifier,
        group=TEAM_GROUP,
        team_users=sorted(team_users),
        runtime_secret_initialized=current_secret is not None,
    )
    require_apply(apply, "bootstrap")

    password_value = (
        str(current_secret["password"])
        if current_secret and current_secret.get("password")
        else new_password()
    )
    ca_bundle = ensure_ca_bundle()
    with (
        PortForward(operator, instance_id, target, settings.local_port),
        master_connection(
            operator, target, settings.local_port, ca_bundle
        ) as connection,
        connection.cursor() as cursor,
    ):
        configure_fixed_roles(cursor, target, password_value)
        enabled, disabled = sync_personal_roles(cursor, team_users)

    if current_secret is None:
        operator.client("secretsmanager").put_secret_value(
            SecretId=settings.runtime_secret_name,
            SecretString=json.dumps(
                runtime_secret_payload(target, password_value),
                separators=(",", ":"),
            ),
        )
    emit(
        "bootstrap-complete",
        enabled_users=enabled,
        disabled_users=disabled,
        runtime_secret_created=current_secret is None,
    )


def sync_team(settings: Settings, apply: bool) -> None:
    direct = base_session(settings)
    operator = assume_operator(direct, settings)
    target = describe_database(operator, settings)
    instance_id = find_app_instance(operator, settings)
    team_users = list_group_users(operator)
    emit("sync-plan", apply=apply, desired_users=sorted(team_users))
    require_apply(apply, "sync-team")

    ca_bundle = ensure_ca_bundle()
    with (
        PortForward(operator, instance_id, target, settings.local_port),
        master_connection(
            operator, target, settings.local_port, ca_bundle
        ) as connection,
        connection.cursor() as cursor,
    ):
        enabled, disabled = sync_personal_roles(cursor, team_users)
    emit("sync-complete", enabled_users=enabled, disabled_users=disabled)


def validate_runtime_connection(
    target: DatabaseTarget,
    local_port: int,
    ca_bundle: Path,
    password: str,
) -> None:
    with (
        psycopg.connect(
            **connection_parameters(
                target,
                local_port,
                ca_bundle,
                DB_RUNTIME_USER,
                password,
            )
        ) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT current_user")
        if cursor.fetchone()[0] != DB_RUNTIME_USER:
            raise ToolError("runtime credential validation returned the wrong user")


def rotate_runtime(
    settings: Settings,
    apply: bool,
    maintenance_confirmed: bool,
) -> None:
    require_apply(apply, "rotate-runtime")
    if not maintenance_confirmed:
        raise ToolError("rotate-runtime requires --maintenance-window-confirmed")

    direct = base_session(settings)
    operator = assume_operator(direct, settings)
    target = describe_database(operator, settings)
    instance_id = find_app_instance(operator, settings)
    secrets_manager = operator.client("secretsmanager")
    current_secret, current_version = get_runtime_secret(operator, settings)
    if current_secret is None or current_version is None:
        raise ToolError("runtime secret is not initialized; run bootstrap first")

    try:
        pending = secrets_manager.get_secret_value(
            SecretId=settings.runtime_secret_name,
            VersionStage="AWSPENDING",
        )
        pending_value = parse_runtime_secret(pending["SecretString"])
        pending_version = pending["VersionId"]
        password_value = str(pending_value["password"])
    except ClientError as error:
        if error.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        password_value = new_password()
        pending_version = str(uuid.uuid4())
        secrets_manager.put_secret_value(
            SecretId=settings.runtime_secret_name,
            ClientRequestToken=pending_version,
            VersionStages=["AWSPENDING"],
            SecretString=json.dumps(
                runtime_secret_payload(target, password_value),
                separators=(",", ":"),
            ),
        )

    ca_bundle = ensure_ca_bundle()
    with PortForward(operator, instance_id, target, settings.local_port):
        with (
            master_connection(
                operator, target, settings.local_port, ca_bundle
            ) as connection,
            connection.cursor() as cursor,
        ):
            ensure_role(
                cursor,
                DB_RUNTIME_USER,
                login=True,
                password=password_value,
            )
        validate_runtime_connection(
            target,
            settings.local_port,
            ca_bundle,
            password_value,
        )

    secrets_manager.update_secret_version_stage(
        SecretId=settings.runtime_secret_name,
        VersionStage="AWSCURRENT",
        MoveToVersionId=pending_version,
        RemoveFromVersionId=current_version,
    )
    secrets_manager.update_secret_version_stage(
        SecretId=settings.runtime_secret_name,
        VersionStage="AWSPENDING",
        RemoveFromVersionId=pending_version,
    )
    emit("runtime-rotation-complete", restart_required=True)


def caller_username(identity_arn: str) -> str:
    marker = ":user/"
    if marker not in identity_arn:
        raise ToolError("direct IAM user credentials from aws login are required")
    return identity_arn.split(marker, 1)[1].rsplit("/", 1)[-1]


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


def client_info(settings: Settings) -> None:
    direct = base_session(settings)
    identity = direct.client("sts").get_caller_identity()
    username = caller_username(identity["Arn"])
    target = describe_database(direct, settings)
    instance_id = find_app_instance(direct, settings)
    token = direct.client("rds").generate_db_auth_token(
        DBHostname=target.endpoint,
        Port=target.port,
        DBUsername=username,
        Region=settings.region,
    )
    ca_bundle = ensure_ca_bundle()
    print(
        render_client_info(
            settings,
            target,
            instance_id,
            username,
            token,
            ca_bundle,
        )
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


def migrate(settings: Settings, apply: bool) -> None:
    require_apply(apply, "migrate")
    direct = base_session(settings)
    identity = direct.client("sts").get_caller_identity()
    username = caller_username(identity["Arn"])
    target = describe_database(direct, settings)
    instance_id = find_app_instance(direct, settings)
    token = direct.client("rds").generate_db_auth_token(
        DBHostname=target.endpoint,
        Port=target.port,
        DBUsername=username,
        Region=settings.region,
    )
    ca_bundle = ensure_ca_bundle()

    with PortForward(direct, instance_id, target, settings.local_port):
        environment = os.environ.copy()
        environment["DB_MIGRATION_URL"] = migration_url(
            target,
            settings.local_port,
            ca_bundle,
            username,
            token,
        )
        environment["PGOPTIONS"] = "-c role=app_owner"
        result = subprocess.run(
            ["uv", "run", "yoyo", "apply", "--batch"],
            cwd=REPO_ROOT / "backend",
            env=environment,
            check=False,
        )
        if result.returncode != 0:
            raise ToolError("Yoyo migration failed")
    emit("migration-complete", database=target.identifier, username=username)


def verify(settings: Settings) -> None:
    direct = base_session(settings)
    operator = assume_operator(direct, settings)
    target = describe_database(operator, settings)
    instance_id = find_app_instance(operator, settings)
    runtime_secret, _ = get_runtime_secret(operator, settings)
    if runtime_secret is None or not runtime_secret.get("password"):
        raise ToolError("runtime secret is not initialized")

    ca_bundle = ensure_ca_bundle()
    with PortForward(operator, instance_id, target, settings.local_port):
        validate_runtime_connection(
            target,
            settings.local_port,
            ca_bundle,
            str(runtime_secret["password"]),
        )
        with (
            master_connection(
                operator, target, settings.local_port, ca_bundle
            ) as connection,
            connection.cursor() as cursor,
        ):
            required = {
                DB_OWNER_ROLE,
                DB_RW_ROLE,
                DB_RUNTIME_USER,
                DB_MIGRATOR_USER,
            }
            cursor.execute(
                "SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)",
                (list(required),),
            )
            present = {row[0] for row in cursor.fetchall()}
            if present != required:
                raise ToolError("required database roles are missing")
    emit("verification-complete", database=target.identifier)


def parser() -> argparse.ArgumentParser:
    command_parser = argparse.ArgumentParser(
        description="Manage development RDS roles, runtime credentials, and IAM migrations"
    )
    command_parser.add_argument("--account-id", required=True)
    command_parser.add_argument("--profile", default=DEFAULT_PROFILE)
    command_parser.add_argument("--region", default=AWS_REGION)
    command_parser.add_argument("--project", default=DEFAULT_PROJECT)
    command_parser.add_argument("--local-port", type=int, default=DEFAULT_LOCAL_PORT)
    command_parser.add_argument("--operator-role", default="TerraformOperatorRole")

    commands = command_parser.add_subparsers(dest="command", required=True)
    for command in ("bootstrap", "sync-team", "migrate"):
        subcommand = commands.add_parser(command)
        subcommand.add_argument("--apply", action="store_true")

    rotate = commands.add_parser("rotate-runtime")
    rotate.add_argument("--apply", action="store_true")
    rotate.add_argument("--maintenance-window-confirmed", action="store_true")
    commands.add_parser("verify")
    commands.add_parser("client-info")
    return command_parser


def settings_from(arguments: argparse.Namespace) -> Settings:
    if not arguments.account_id.isdigit() or len(arguments.account_id) != 12:
        raise ToolError("--account-id must contain exactly 12 digits")
    if arguments.region != AWS_REGION:
        raise ToolError("only ap-northeast-2 is supported")
    if not 1024 <= arguments.local_port <= 65535:
        raise ToolError("--local-port must be between 1024 and 65535")
    return Settings(
        account_id=arguments.account_id,
        profile=arguments.profile,
        region=arguments.region,
        project=arguments.project,
        local_port=arguments.local_port,
        operator_role=arguments.operator_role,
    )


def main() -> None:
    arguments = parser().parse_args()
    settings = settings_from(arguments)
    if arguments.command == "bootstrap":
        bootstrap(settings, arguments.apply)
    elif arguments.command == "sync-team":
        sync_team(settings, arguments.apply)
    elif arguments.command == "rotate-runtime":
        rotate_runtime(
            settings,
            arguments.apply,
            arguments.maintenance_window_confirmed,
        )
    elif arguments.command == "migrate":
        migrate(settings, arguments.apply)
    elif arguments.command == "verify":
        verify(settings)
    elif arguments.command == "client-info":
        client_info(settings)


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
    except psycopg.Error as error:
        code = error.sqlstate or error.__class__.__name__
        print(f"ERROR: PostgreSQL request failed ({code})", file=sys.stderr)
        raise SystemExit(1) from None
