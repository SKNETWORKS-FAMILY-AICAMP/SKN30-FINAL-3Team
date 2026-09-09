#!/usr/bin/env python3
"""Bind saved plans to local inputs; reject stale or modified artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path

from env_doctor import private_write

INFRA = Path(__file__).resolve().parents[1]
MAX_AGE = 24 * 60 * 60
SUFFIXES = {
    ".tf",
    ".tfvars",
    ".json",
    ".hcl",
    ".py",
    ".sh",
    ".tftpl",
    ".yml",
    ".yaml",
    ".Dockerfile",
}


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def inputs(infra: Path, root: Path) -> dict[str, str]:
    paths = list(root.iterdir())
    if root.name == "dev":
        for name in ("scripts", "serving", "deploy", "runpod", "delivery"):
            paths.extend((infra / name).rglob("*"))
    return {
        str(p.relative_to(infra)): digest(p)
        for p in sorted(set(paths))
        if p.is_file()
        and not p.is_symlink()
        and p.suffix in SUFFIXES
        and not any(
            (x.startswith(".") and x != ".terraform.lock.hcl")
            or x in {"__pycache__", "tests", "dist"}
            for x in p.relative_to(infra).parts
        )
        and not p.name.endswith(".plan-meta.json")
    }


def seal(infra: Path, plan: Path) -> None:
    if not plan.is_file() or plan.is_symlink():
        raise ValueError("정상 saved plan 파일이 필요합니다.")
    data = {
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
            0 <= age <= MAX_AGE
            and data["plan_sha256"] == digest(plan)
            and data["inputs"] == inputs(infra, plan.parent)
        )
    except (OSError, ValueError, KeyError, TypeError):
        valid = False
    if not valid:
        raise ValueError(
            "plan이 없거나 오래됐거나 입력이 바뀌었습니다. 해당 *-plan → *-show를 다시 실행하세요."
        )


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
