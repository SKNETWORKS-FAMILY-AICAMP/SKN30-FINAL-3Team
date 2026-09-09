"""Fixed shared-dev synthetic seed files and safe subprocess verification."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from db_access_contracts import DB_OWNER_ROLE, DatabaseTarget, ToolError

REPO_ROOT = Path(__file__).resolve().parents[2]
F3_SEED_DIRECTORY = REPO_ROOT / "docs" / "db" / "seed"
F3_SEED_RESET = F3_SEED_DIRECTORY / "001_F3_SYNTHETIC_RESET.sql"
F3_SEED_DATA = F3_SEED_DIRECTORY / "002_F3_SYNTHETIC_SEED.sql"
F3_SEED_VERIFY = F3_SEED_DIRECTORY / "003_F3_SYNTHETIC_VERIFY.sql"
F3_MODEL_PROFILE_DIRECTORY = F3_SEED_DIRECTORY / "model-profiles"
F3_MODEL_PROFILE_FILES = {
    "local-openai": F3_MODEL_PROFILE_DIRECTORY / "local-openai.sql",
    "dev-bedrock-gpt56-luna": (
        F3_MODEL_PROFILE_DIRECTORY / "dev-bedrock-gpt56-luna.sql"
    ),
    "dev-qwen38-vllm-bnb": F3_MODEL_PROFILE_DIRECTORY / "dev-qwen38-vllm-bnb.sql",
    "dev-qwen38-llamacpp-gguf": (
        F3_MODEL_PROFILE_DIRECTORY / "dev-qwen38-llamacpp-gguf.sql"
    ),
}
F3_MODEL_PROFILES = tuple(F3_MODEL_PROFILE_FILES)
F3_SEED_VERIFY_CHECK_COUNT = 30
F3_SELECTED_PROFILE_QUERY = """
SELECT 'selected-profile|' || c.config_key
FROM ai_model_config c
JOIN brokerage b ON b.id = c.brokerage_id
WHERE b.name = 'F3_SYNTHETIC 합성중개사무소'
  AND c.is_active
  AND c.capability IN ('POSITION_CARD', 'BROKERAGE_JUDGMENT')
GROUP BY c.config_key
ORDER BY c.config_key
"""


def psql_environment(
    target: DatabaseTarget,
    local_port: int,
    ca_bundle: Path,
    username: str,
    token: str,
) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "PGHOST": target.endpoint,
            "PGHOSTADDR": "127.0.0.1",
            "PGPORT": str(local_port),
            "PGDATABASE": target.database,
            "PGUSER": username,
            "PGPASSWORD": token,
            "PGSSLMODE": "verify-full",
            "PGSSLROOTCERT": str(ca_bundle),
            "PGOPTIONS": f"-c role={DB_OWNER_ROLE}",
        }
    )
    return environment


def verify_f3_seed_output(output: str, model_profile: str) -> None:
    check_lines = [
        line for line in output.splitlines() if line.endswith(("|PASS", "|FAIL"))
    ]
    failed_lines = [line for line in check_lines if line.endswith("|FAIL")]
    if failed_lines:
        raise ToolError("F3 synthetic seed verification reported FAIL")
    if len(check_lines) != F3_SEED_VERIFY_CHECK_COUNT:
        raise ToolError(
            "F3 synthetic seed verification returned an unexpected check count"
        )
    selected_profiles = [
        line.removeprefix("selected-profile|")
        for line in output.splitlines()
        if line.startswith("selected-profile|")
    ]
    if selected_profiles != [model_profile]:
        raise ToolError("F3 synthetic seed selected model profile verification failed")


def verify_f3_result_output(output: str, model_profile: str) -> dict[str, object]:
    """Accept only the fixed, verified deterministic seed summary."""
    try:
        summary = json.loads(output)
    except (json.JSONDecodeError, TypeError) as error:
        raise ToolError("F3 synthetic result seed returned invalid JSON") from error
    required_counts = (
        "total_targets",
        "eligible_targets",
        "completed_results",
        "verification_checks",
        "brokerage_id",
        "user_id",
    )
    if not isinstance(summary, dict) or any(
        type(summary.get(key)) is not int or summary[key] <= 0
        for key in required_counts
    ):
        raise ToolError("F3 synthetic result seed returned invalid counts")
    if (
        summary.get("event") != "synthetic-match-seed-complete"
        or summary.get("model_inference") is not False
        or summary.get("login_id") != "f3_synthetic_dev"
        or summary.get("model_profile") != model_profile
        or summary["total_targets"] != 84
        or summary["eligible_targets"] != 81
        or summary["completed_results"] != summary["eligible_targets"]
    ):
        raise ToolError("F3 synthetic result seed verification failed")
    # Unknown subprocess output must never become credential-bearing log fields.
    return {
        key: summary[key]
        for key in (
            *required_counts,
            "event",
            "model_inference",
            "login_id",
            "model_profile",
        )
    }


def run_f3_result_seed(
    environment: dict[str, str], model_profile: str
) -> dict[str, object]:
    result = subprocess.run(
        [
            "uv",
            "run",
            "--locked",
            "--project",
            str(REPO_ROOT / "backend"),
            "python",
            str(REPO_ROOT / "backend" / "scripts" / "seed_match_results.py"),
            "--confirm-synthetic-seed",
            "--model-profile",
            model_profile,
        ],
        cwd=REPO_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # Driver errors may contain connection details; do not echo captured output.
        raise ToolError("F3 synthetic result seed failed; no completion was recorded")
    return verify_f3_result_output(result.stdout, model_profile)
