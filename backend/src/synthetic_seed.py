from __future__ import annotations

import ipaddress
import urllib.parse
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg

from core.config import AppEnvironment, Config

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
F3_SEED_DIRECTORY = REPOSITORY_ROOT / "docs" / "db" / "seed"
F3_SEED_RESET = F3_SEED_DIRECTORY / "001_F3_SYNTHETIC_RESET.sql"
F3_SEED_DATA = F3_SEED_DIRECTORY / "002_F3_SYNTHETIC_SEED.sql"
F3_SEED_VERIFY = F3_SEED_DIRECTORY / "003_F3_SYNTHETIC_VERIFY.sql"
F3_MODEL_PROFILE_DIRECTORY = F3_SEED_DIRECTORY / "model-profiles"
F3_MODEL_PROFILE_FILES = {
    "local-openai": F3_MODEL_PROFILE_DIRECTORY / "local-openai.sql",
    "dev-bedrock-gpt56-luna": F3_MODEL_PROFILE_DIRECTORY / "dev-bedrock-gpt56-luna.sql",
    "dev-qwen38-vllm-bnb": F3_MODEL_PROFILE_DIRECTORY / "dev-qwen38-vllm-bnb.sql",
    "dev-qwen38-llamacpp-gguf": (F3_MODEL_PROFILE_DIRECTORY / "dev-qwen38-llamacpp-gguf.sql"),
}
F3_MODEL_PROFILES = tuple(F3_MODEL_PROFILE_FILES)
F3_SYNTHETIC_BROKERAGE_NAME = "F3_SYNTHETIC 합성중개사무소"
EXPECTED_VERIFICATION_CHECKS = 30
SUPPORTED_PSQL_COMMAND = r"\set ON_ERROR_STOP on"

IDENTITY_QUERY = """
SELECT b.id, u.id, u.login_id
FROM brokerage b
JOIN app_user u ON u.brokerage_id = b.id
WHERE b.name = %s AND u.login_id = 'f3_synthetic_dev'
"""

SELECTED_PROFILE_QUERY = """
SELECT DISTINCT c.config_key
FROM ai_model_config c
JOIN brokerage b ON b.id = c.brokerage_id
WHERE b.name = %s
  AND c.is_active
  AND c.capability IN ('POSITION_CARD', 'BROKERAGE_JUDGMENT')
ORDER BY c.config_key
"""


class SyntheticSeedError(RuntimeError):
    """합성 seed를 안전하게 적용할 수 없을 때 반환하는 공개 가능한 오류."""


@dataclass(frozen=True)
class SyntheticSeedResult:
    brokerage_id: int
    user_id: int
    login_id: str
    verification_checks: int


def _psycopg_url(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _is_loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def require_local_seed_target(config: Config) -> None:
    if config.app.environment is not AppEnvironment.LOCAL:
        raise SyntheticSeedError("F3 synthetic seed requires APP_ENV=local")

    url = config.db.url.get_secret_value()
    try:
        host = urllib.parse.urlsplit(url).hostname
    except ValueError as error:
        raise SyntheticSeedError("F3 synthetic seed requires a valid local DB_URL") from error
    if host is None or not _is_loopback_host(host):
        raise SyntheticSeedError("F3 synthetic seed requires a loopback DB_URL host")


def read_psql_script(path: Path) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    except (OSError, UnicodeError) as error:
        raise SyntheticSeedError(f"cannot read F3 synthetic seed script: {path.name}") from error

    sql: list[str] = []
    for line in lines:
        command = line.strip()
        if command == SUPPORTED_PSQL_COMMAND:
            continue
        if command.startswith("\\"):
            raise SyntheticSeedError(
                f"unsupported psql command in F3 synthetic seed script: {path.name}"
            )
        sql.append(line)
    if not sql:
        raise SyntheticSeedError(f"F3 synthetic seed script is empty: {path.name}")
    return "".join(sql)


def model_profile_path(model_profile: str) -> Path:
    try:
        return F3_MODEL_PROFILE_FILES[model_profile]
    except KeyError as error:
        raise SyntheticSeedError(
            f"unsupported F3 synthetic model profile: {model_profile}"
        ) from error


def validate_verification_rows(rows: Sequence[Sequence[object]]) -> None:
    if len(rows) != EXPECTED_VERIFICATION_CHECKS:
        raise SyntheticSeedError(
            "F3 synthetic seed verification "
            f"expected {EXPECTED_VERIFICATION_CHECKS} checks but received {len(rows)}"
        )

    failures: list[str] = []
    for row in rows:
        if len(row) != 4:
            failures.append("malformed verification row")
        elif row[3] != "PASS":
            failures.append(str(row[0]))
    if failures:
        raise SyntheticSeedError("F3 synthetic seed verification failed: " + ", ".join(failures))


def validate_selected_profile(rows: Sequence[Sequence[object]], model_profile: str) -> None:
    """공통 allowlist 검증과 별개로 CLI에서 고른 프로필이 실제 활성인지 확인한다."""
    if len(rows) != 1 or len(rows[0]) != 1 or rows[0][0] != model_profile:
        raise SyntheticSeedError("F3 synthetic seed selected model profile verification failed")


def seed_f3_synthetic(
    config: Config,
    *,
    confirm_reset: bool,
    model_profile: str,
    connector: Callable[..., Any] = psycopg.connect,
    script_paths: tuple[Path, Path, Path, Path] | None = None,
) -> SyntheticSeedResult:
    if not confirm_reset:
        raise SyntheticSeedError("F3 synthetic seed reset requires --confirm-reset")
    require_local_seed_target(config)

    profile_path = model_profile_path(model_profile)
    reset_path, seed_path, selected_profile_path, verify_path = script_paths or (
        F3_SEED_RESET,
        F3_SEED_DATA,
        profile_path,
        F3_SEED_VERIFY,
    )
    reset_sql = read_psql_script(reset_path)
    seed_sql = read_psql_script(seed_path)
    profile_sql = read_psql_script(selected_profile_path)
    verify_sql = read_psql_script(verify_path)

    try:
        with connector(
            _psycopg_url(config.db.url.get_secret_value()), autocommit=True
        ) as connection:
            connection.execute(reset_sql, prepare=False)
            connection.execute(seed_sql, prepare=False)
            connection.execute(profile_sql, prepare=False)
            rows = connection.execute(verify_sql, prepare=False).fetchall()
            validate_verification_rows(rows)
            selected_profile_rows = connection.execute(
                SELECTED_PROFILE_QUERY,
                (F3_SYNTHETIC_BROKERAGE_NAME,),
                prepare=False,
            ).fetchall()
            validate_selected_profile(selected_profile_rows, model_profile)
            identity = connection.execute(
                IDENTITY_QUERY,
                (F3_SYNTHETIC_BROKERAGE_NAME,),
                prepare=False,
            ).fetchone()
    except SyntheticSeedError:
        raise
    except psycopg.Error as error:
        raise SyntheticSeedError("F3 synthetic seed database execution failed") from error

    if identity is None or len(identity) != 3:
        raise SyntheticSeedError("F3 synthetic seed identity was not created")
    return SyntheticSeedResult(
        brokerage_id=int(identity[0]),
        user_id=int(identity[1]),
        login_id=str(identity[2]),
        verification_checks=len(rows),
    )
