#!/usr/bin/env python3
"""Bind saved plans to local inputs; reject stale or modified artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

from env_doctor import private_write

INFRA = Path(__file__).resolve().parents[1]
MAX_AGE = 24 * 60 * 60
SCHEMA_VERSION = 2
FIRST_DEPLOY_PLAN = "dev-first-deploy.tfplan"
SOURCE_NAMES = {"Dockerfile", ".dockerignore", "justfile", ".terraform.lock.hcl"}
EXCLUDED_DIRS = {"__pycache__", "tests", "dist", "node_modules"}
SUFFIXES = {
    ".tf",
    ".tfvars",
    ".json",
    ".hcl",
    ".py",
    ".sh",
    ".tftpl",
    ".tpl",
    ".policy",
    ".yml",
    ".yaml",
    ".Dockerfile",
    ".toml",
    ".txt",
    ".sql",
}


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def source_files(directory: Path):
    """Walk declared source scopes recursively, pruning caches before traversal."""
    if directory.is_symlink():
        raise ValueError("plan 입력 범위의 symlink 디렉터리는 지원하지 않습니다.")
    for base, directories, files in os.walk(directory, followlinks=False):
        directories[:] = sorted(
            name
            for name in directories
            if not name.startswith(".") and name not in EXCLUDED_DIRS
        )
        for name in directories:
            if (Path(base) / name).is_symlink():
                raise ValueError(
                    "plan 입력 범위의 symlink 디렉터리는 지원하지 않습니다."
                )
        for name in sorted(files):
            path = Path(base) / name
            if name.startswith(".") and name not in SOURCE_NAMES:
                continue
            if name.endswith(".plan-meta.json"):
                continue
            if (
                path.suffix not in SUFFIXES
                and name not in SOURCE_NAMES
                and not name.startswith("Dockerfile.")
            ):
                continue
            if path.is_symlink():
                raise ValueError("plan 입력 파일의 symlink는 지원하지 않습니다.")
            if path.is_file():
                yield path


def inputs(infra: Path, root: Path) -> dict[str, str]:
    scopes = [root, infra / "scripts"]
    if root == infra / "environments/dev":
        scopes.extend(
            infra / name for name in ("serving", "deploy", "runpod", "delivery")
        )
    paths = {path for scope in scopes for path in source_files(scope)}
    justfile = infra / "justfile"
    if justfile.is_symlink():
        raise ValueError("plan 입력 파일의 symlink는 지원하지 않습니다.")
    if justfile.exists():
        paths.add(justfile)
    return {str(path.relative_to(infra)): digest(path) for path in sorted(paths)}


def validate_first_deploy(payload: dict) -> None:
    """Check actual saved-plan choices, never the CLI recipe or sidecar alone."""
    variables = payload.get("variables", {})
    # Terraform show preserves CLI -var boolean tokens as strings in variables.
    enabled = [
        variables.get(name, {}).get("value")
        for name in ("dev_edge_enabled", "dev_gpu_enabled")
    ]
    if variables.get("app_deployment_mode", {}).get("value") != "maintenance" or any(
        value is not True and value != "true" for value in enabled
    ):
        raise ValueError(
            "최초 배포 plan은 maintenance·edge=true·gpu=true 입력이어야 합니다."
        )
    project = variables.get("project_name", {}).get("value")
    resources = (
        payload.get("planned_values", {}).get("root_module", {}).get("resources", [])
    )
    groups = [
        resource.get("values", {})
        for resource in resources
        if resource.get("address") == "aws_codedeploy_deployment_group.backend"
    ]
    if (
        not isinstance(project, str)
        or len(groups) != 1
        or groups[0].get("autoscaling_groups") != []
    ):
        raise ValueError(
            "최초 배포 plan에서 CodeDeploy ASG 자동 연결이 해제되어야 합니다."
        )
    tags = groups[0].get("ec2_tag_set", [])
    if len(tags) != 3 or any(
        len(group.get("ec2_tag_filter", [])) != 1 for group in tags
    ):
        raise ValueError(
            "최초 배포 plan은 정확한 앱 태그 3개를 AND 조건으로 지정해야 합니다."
        )
    actual = {
        (item.get("key"), item.get("value"), item.get("type"))
        for group in tags
        for item in group["ec2_tag_filter"]
    }
    expected = {
        ("Project", project, "KEY_AND_VALUE"),
        ("Environment", "dev", "KEY_AND_VALUE"),
        ("Name", f"{project}-dev-app-asg", "KEY_AND_VALUE"),
    }
    if actual != expected or groups[0].get("ec2_tag_filter"):
        raise ValueError(
            "최초 배포 plan의 CodeDeploy 대상이 정확한 앱 태그와 다릅니다."
        )


def check_plan_intent(plan: Path) -> None:
    if plan.name != FIRST_DEPLOY_PLAN:
        return
    try:
        result = subprocess.run(
            ["terraform", f"-chdir={plan.parent}", "show", "-json", plan.name],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            raise ValueError(
                "최초 배포 saved plan을 읽지 못했습니다. plan을 재생성하세요."
            )
        # Terraform JSON can include secrets: inspect in memory, never print or save it.
        validate_first_deploy(json.loads(result.stdout))
    except (
        OSError,
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
        TypeError,
        KeyError,
        AttributeError,
    ):
        raise ValueError(
            "최초 배포 saved plan 검증 실패. plan을 재생성하세요."
        ) from None


def seal(infra: Path, plan: Path) -> None:
    if not plan.is_file() or plan.is_symlink():
        raise ValueError("정상 saved plan 파일이 필요합니다.")
    check_plan_intent(plan)
    data = {
        "schema_version": SCHEMA_VERSION,
        "created_at": time.time(),
        "plan_sha256": digest(plan),
        "inputs": inputs(infra, plan.parent),
    }
    plan.chmod(0o600)
    private_write(
        plan.with_suffix(".plan-meta.json"), json.dumps(data, indent=2) + "\n"
    )


def check(infra: Path, plan: Path, *, now: float | None = None) -> None:
    if plan.is_symlink():
        raise ValueError("symlink plan은 사용하지 않습니다.")
    try:
        data = json.loads(plan.with_suffix(".plan-meta.json").read_text())
        age = (time.time() if now is None else now) - data["created_at"]
        valid = (
            data.get("schema_version") == SCHEMA_VERSION
            and 0 <= age <= MAX_AGE
            and data["plan_sha256"] == digest(plan)
            and data["inputs"] == inputs(infra, plan.parent)
        )
    except (OSError, ValueError, KeyError, TypeError):
        valid = False
    if not valid:
        raise ValueError(
            "plan이 없거나 오래됐거나 입력·검증 규칙이 바뀌었습니다. 해당 *-plan → *-show를 다시 실행하세요."
        )
    check_plan_intent(plan)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("seal", "check"))
    parser.add_argument("plan", type=Path)
    args = parser.parse_args()
    try:
        plan = args.plan.absolute()
        if (
            plan.parent not in (INFRA / "bootstrap", INFRA / "environments/dev")
            or plan.suffix != ".tfplan"
        ):
            raise ValueError("bootstrap 또는 dev root의 .tfplan만 허용합니다.")
        if args.command == "seal":
            seal(INFRA, plan)
        else:
            check(INFRA, plan)
        print("saved plan 입력·무결성 확인 (유효기간 24시간). apply 승인은 별도입니다.")
        return 0
    except (OSError, ValueError) as error:
        print(str(error) if isinstance(error, ValueError) else "plan 파일 접근 실패")
        return 1


if __name__ == "__main__":
    os.umask(0o077)
    raise SystemExit(main())
