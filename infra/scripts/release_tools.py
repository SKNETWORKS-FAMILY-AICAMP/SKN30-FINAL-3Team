#!/usr/bin/env python3
"""Named F2 release selection and explicit image publication, without GPU startup."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

from env_doctor import private_write

from operations import INFRA, PROJECT, Aws, QueryError

CATALOG = INFRA / "runpod/releases.json"


def select_f2(args) -> int:
    catalog = json.loads(CATALOG.read_text())
    release = next(
        (r for r in catalog["releases"] if r["release_id"] == args.release_id), None
    )
    if release is None:
        raise ValueError("알 수 없는 release ID입니다. just f2-releases로 확인하세요.")
    aws = Aws(args.account_id, args.profile)
    bucket = f"{PROJECT}-dev-data-model-apse2-{args.account_id}"
    prefix = "releases/sllm/" + release["release_id"]
    bundle = aws.call(
        "s3api", "head-object", "--bucket", bucket, "--key", prefix + "/bundle.tar.gz"
    )["Metadata"]
    manifest = aws.call(
        "s3api", "head-object", "--bucket", bucket, "--key", prefix + "/release.json"
    )["Metadata"]
    if (
        bundle.get("sha256") != release["bundle_sha256"]
        or manifest.get("bundle-sha256") != release["bundle_sha256"]
        or bundle.get("release-manifest-sha256") != manifest.get("sha256")
    ):
        raise ValueError(
            "S3 bundle/manifest checksum이 catalog와 다릅니다. 선택을 저장하지 않습니다."
        )
    command = [
        "uv",
        "run",
        "--script",
        str(INFRA / "scripts/manage_serving.py"),
        "--account-id",
        args.account_id,
        "--profile",
        args.profile,
        "configure",
        "f2",
        args.cloud,
        "--gpu-id",
        args.gpu_id,
        "--release-id",
        release["release_id"],
        "--bucket",
        bucket,
        "--apply",
    ]
    if release["release_stage"] == "dev":
        command.append("--allow-dev-release")
    # Existing configure checks offline state and writes only the selection document.
    return subprocess.run(command, check=False).returncode


def adopt_gpu_profiles(source: Path) -> None:
    destination = INFRA / "environments/dev/gpu-profiles.auto.tfvars.json"
    if source.is_symlink() or not source.is_file() or source.stat().st_size > 65536:
        raise ValueError("작은 일반 JSON 프로필 파일이 필요합니다.")
    data = json.loads(source.read_text())
    if set(data) != {"gpu_profiles"} or not isinstance(data["gpu_profiles"], dict):
        raise ValueError(
            "gpu_profiles만 포함한 JSON을 사용하세요. capacity·비밀값은 허용하지 않습니다."
        )
    for name, profile in data["gpu_profiles"].items():
        if (
            name not in {"f2", "general"}
            or not isinstance(profile, dict)
            or set(profile) - {"ami_id", "image", "root_volume_gb"}
        ):
            raise ValueError("GPU 프로필 필드가 올바르지 않습니다.")
        if not re.fullmatch(
            r"ami-[0-9a-f]+", profile.get("ami_id", "")
        ) or not re.fullmatch(
            r"ghcr.io/[a-z0-9._/-]+@sha256:[0-9a-f]{64}", profile.get("image", "")
        ):
            raise ValueError("검토한 AMI와 완성 이미지 digest를 사용하세요.")
        size = profile.get("root_volume_gb", 160)
        if isinstance(size, bool) or not isinstance(size, int) or size < 80:
            raise ValueError("GPU root volume은 80GiB 이상이어야 합니다.")
    if destination.exists() and json.loads(destination.read_text()) != data:
        raise ValueError("기존 gpu-profiles와 다릅니다. 덮어쓰지 않고 중단합니다.")
    private_write(destination, json.dumps(data, indent=2) + "\n")
    print(
        "gpu-profiles.auto.tfvars.json 준비됨. GPU 생성·기동 없음. 기존 validation.auto 파일은 비교 후 자동 로딩 경로에서 제거하세요."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list-f2")
    publish = commands.add_parser("publish-image")
    publish.add_argument("workload", choices=("f2", "general"))
    publish.add_argument("ref")
    adopt = commands.add_parser("adopt-gpu-profiles")
    adopt.add_argument("source", type=Path)
    select = commands.add_parser("select-f2")
    select.add_argument("release_id")
    select.add_argument("cloud", choices=("aws", "runpod"))
    select.add_argument("gpu_id")
    select.add_argument("--account-id", required=True)
    select.add_argument("--profile", default="skn30-session")
    args = parser.parse_args()
    try:
        if args.command == "list-f2":
            for release in json.loads(CATALOG.read_text())["releases"]:
                print(
                    f"{release['release_id']} | {release['label']} | bundle={release['release_stage']} | serving={release['serving_validation']}"
                )
            print(
                "선택 예: just f2-select consultation-v3 (선택만 저장; 기동·품질 승격 없음)"
            )
        elif args.command == "publish-image":
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", args.ref):
                raise ValueError("유효한 원격 Git ref를 지정하세요.")
            workflow = (
                "runpod-image.yml" if args.workload == "f2" else "general-image.yml"
            )
            subprocess.run(
                ["gh", "workflow", "run", workflow, "--ref", args.ref],
                cwd=INFRA,
                check=True,
            )
            print(
                "게시 요청됨. gh run list → gh run watch <run-id> → gh run download <run-id>로 완료 artifact를 확인하세요. 기동 검증은 미실행입니다."
            )
        elif args.command == "adopt-gpu-profiles":
            adopt_gpu_profiles(args.source)
        else:
            return select_f2(args)
        return 0
    except (
        QueryError,
        ValueError,
        OSError,
        KeyError,
        TypeError,
        AttributeError,
        subprocess.CalledProcessError,
    ) as error:
        print(
            str(error)
            if isinstance(error, (QueryError, ValueError))
            else "작업 실패. 파일·설정·인증을 확인하세요. 원문은 숨겼습니다."
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
