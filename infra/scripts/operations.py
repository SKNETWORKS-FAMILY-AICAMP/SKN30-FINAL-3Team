#!/usr/bin/env python3
"""On-demand, read-only cloud inventory and explicit post-start smoke checks."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

INFRA = Path(__file__).resolve().parents[1]
PROJECT = "skn30-final-3team"
PREFIX = f"/{PROJECT}-dev/"
CONTROL = {"f2": "RUNPOD_CONTROL_SET", "general": "GENERAL_CONTROL_SET"}
ENDPOINT = {"f2": "AI_VLLM_ENDPOINT_SET", "general": "AI_GENERAL_ENDPOINT_SET"}
BROKEN_IMAGES = {
    "03c275889e7372a0367e5ceff961d219414235751807c25a2dc28732523d1567",
    "ec4531f35b46a300e2bcc223e9591b98c6c1aba8d1ef80fee453286d844129af",
}
SECRET_FIELDS = {
    "ai/provider-api-keys": (
        "AI_VLLM_SLLM_API_KEY",
        "AI_VLLM_STT_API_KEY",
        "AI_GENERAL_API_KEY",
    ),
    "backend/runtime-database-url": ("host", "port", "dbname", "username", "password"),
    "runpod/ghcr-registry": ("username", "token"),
    "runpod/operator-api-key": (),
    "delivery/discord-webhook": (),
    "observability/alarm-discord-webhook": (),
}


class QueryError(RuntimeError):
    """Never include provider response bodies or credential-bearing arguments."""


class Aws:
    def __init__(self, account: str, profile: str):
        if not re.fullmatch(r"[0-9]{12}", account):
            raise QueryError("infra/.env의 TARGET_ACCOUNT_ID를 설정하세요.")
        self.profile = profile
        self.env = os.environ.copy()
        if self.env.get("AWS_ACCESS_KEY_ID") or self.env.get("AWS_SECRET_ACCESS_KEY"):
            raise QueryError(
                "정적 AWS 환경 키를 제거하고 aws login profile을 사용하세요."
            )
        identity = self.call("sts", "get-caller-identity")
        if identity["Account"] != account or identity["Arn"].endswith(":root"):
            raise QueryError("계정이 다르거나 root 자격 증명입니다.")
        credentials = self.call(
            "sts",
            "assume-role",
            "--role-arn",
            f"arn:aws:iam::{account}:role/TerraformOperatorRole",
            "--role-session-name",
            "infra-operations-doctor",
        )["Credentials"]
        self.env.update(
            AWS_ACCESS_KEY_ID=credentials["AccessKeyId"],
            AWS_SECRET_ACCESS_KEY=credentials["SecretAccessKey"],
            AWS_SESSION_TOKEN=credentials["SessionToken"],
        )
        self.profile = None

    def call(self, *args: str):
        command = [
            "aws",
            "--region",
            "ap-northeast-2",
            "--output",
            "json",
            "--no-cli-pager",
        ]
        if self.profile:
            command.extend(["--profile", self.profile])
        try:
            result = subprocess.run(
                command + list(args),
                env=self.env,
                text=True,
                capture_output=True,
                timeout=45,
                check=False,
            )
            if result.returncode:
                raise QueryError(
                    f"{args[0]} {args[1]} 조회 실패. 로그인·권한을 확인하세요."
                )
            return json.loads(result.stdout)
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
            raise QueryError(
                f"{args[0]} {args[1]} 조회 불가. 원문 응답은 숨겼습니다."
            ) from None

    def parameter(self, suffix: str) -> dict:
        return json.loads(
            self.call("ssm", "get-parameter", "--name", PREFIX + suffix)["Parameter"][
                "Value"
            ]
        )

    def secret(self, suffix: str) -> str:
        return self.call(
            "secretsmanager", "get-secret-value", "--secret-id", PREFIX + suffix
        )["SecretString"]


def runpod_get(key: str, path: str):
    request = urllib.request.Request(
        "https://rest.runpod.io/v1/" + path,
        headers={
            "Authorization": "Bearer " + key,
            "User-Agent": "skn30-infra/1.0",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        raise QueryError(
            "RunPod 조회 실패. 운영 API 키·권한·연결을 확인하세요."
        ) from None


def add(
    checks: list, status: str, target: str, message: str, next_step: str = ""
) -> None:
    checks.append(
        {"status": status, "target": target, "message": message, "next": next_step}
    )


def image_check(
    image: str, workload: str, profile: str | None, catalog: dict
) -> tuple[str, str]:
    if not re.fullmatch(r"ghcr.io/[a-z0-9._/-]+@sha256:[0-9a-f]{64}", image):
        return (
            "fail",
            "완성 이미지 digest가 없습니다. base image나 mutable tag를 등록하지 마세요.",
        )
    if image.rsplit(":", 1)[1] in BROKEN_IMAGES:
        return (
            "fail",
            "기동 실패가 기록된 과거 이미지입니다. 수정 이미지를 게시·등록하세요.",
        )
    if workload == "f2":
        return "warn", "digest 등록됨. 게시 workflow 통과와 기동 검증은 별도입니다."
    if not profile:
        return "fail", "범용 model_profile을 명시적으로 선택하세요."
    record = next((x for x in catalog["images"] if x["image"] == image), None)
    if record is None:
        return (
            "warn",
            "게시 catalog에 없는 이미지입니다. workflow provenance와 선택 프로필을 검토하세요.",
        )
    state = record.get("profiles", {}).get(profile, {}).get("status", "not_in_image")
    if state in {"failed", "not_in_image"}:
        return "fail", "선택 모델이 이 이미지에 없거나 해당 조합의 기동이 실패했습니다."
    return (
        "warn",
        f"catalog 검증 범위: {state}. 평가 실행 완료는 품질 승인·공유 배포 완료를 뜻하지 않습니다.",
    )


def inspect_cloud(
    aws: Aws, *, ready: bool = False, get_runpod=runpod_get
) -> list[dict]:
    checks = []
    catalog = json.loads((INFRA / "serving/published-images.json").read_text())
    try:
        groups = aws.call(
            "autoscaling",
            "describe-auto-scaling-groups",
            "--auto-scaling-group-names",
            PROJECT + "-dev-app",
        )["AutoScalingGroups"]
        group = groups[0] if groups else {}
        add(
            checks,
            "info",
            "AWS 앱",
            f"desired={group.get('DesiredCapacity', '없음')}, 인스턴스={len(group.get('Instances', []))}",
        )
        database = aws.call(
            "rds",
            "describe-db-instances",
            "--db-instance-identifier",
            PROJECT + "-dev-postgres",
        )["DBInstances"][0]
        add(
            checks,
            "info",
            "RDS",
            f"상태={database['DBInstanceStatus']}, 저장공간={database['AllocatedStorage']}GiB; 정지 중 저장 비용 유지",
        )
        if database.get("AutomaticRestartTime"):
            add(
                checks,
                "warn",
                "RDS 자동 재시작",
                str(database["AutomaticRestartTime"]),
                "장기 정지 중에도 운영자가 재시작 시각을 확인하세요.",
            )
    except QueryError as error:
        add(checks, "fail", "AWS 상태", str(error))

    try:
        volumes = aws.call(
            "ec2", "describe-volumes", "--filters", f"Name=tag:Project,Values={PROJECT}"
        )["Volumes"]
        add(
            checks,
            "warn" if volumes else "ok",
            "AWS EBS",
            f"{len(volumes)}개 / {sum(v['Size'] for v in volumes)}GiB; stopped·available도 저장 비용 유지",
        )
        distributions = (
            aws.call("cloudfront", "list-distributions")
            .get("DistributionList", {})
            .get("Items", [])
        )
        owned = [
            d
            for d in distributions
            if any(
                PROJECT in o.get("Id", "")
                for o in d.get("Origins", {}).get("Items", [])
            )
        ]
        add(
            checks,
            "info",
            "CloudFront",
            f"{len(owned)}개, 활성={sum(d['Enabled'] for d in owned)}",
        )
    except QueryError as error:
        add(checks, "fail", "잔여 자원", str(error))

    for suffix, fields in SECRET_FIELDS.items():
        try:
            description = aws.call(
                "secretsmanager", "describe-secret", "--secret-id", PREFIX + suffix
            )
            stages = description.get("VersionIdsToStages", {})
            if not any("AWSCURRENT" in values for values in stages.values()):
                add(
                    checks,
                    "fail",
                    suffix,
                    "AWSCURRENT 없음",
                    "configuration.md의 소유 명령으로 TTY 입력",
                )
                continue
            raw = aws.secret(suffix)
            values = json.loads(raw) if fields else {}
            missing = [name for name in fields if not values.get(name)]
            if suffix == "ai/provider-api-keys" and not missing:
                keys = [values[name] for name in fields]
                if (
                    any(
                        not isinstance(k, str)
                        or not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", k)
                        for k in keys
                    )
                    or keys[0] == keys[1]
                ):
                    add(
                        checks,
                        "fail",
                        suffix,
                        "F2/general 키 형식 또는 F2 키 분리 조건 불충족",
                    )
                    continue
            add(
                checks,
                "fail" if missing or not raw.strip() else "ok",
                suffix,
                "누락 필드: " + ", ".join(missing)
                if missing
                else "AWSCURRENT·필수 구조 확인; 인증·배포 반영은 미검증",
            )
        except (QueryError, ValueError, TypeError, AttributeError):
            add(
                checks,
                "fail",
                suffix,
                "조회 또는 구조 검증 실패. 값·응답 원문은 숨겼습니다.",
            )

    try:
        selection = aws.parameter("serving/SELECTION")
        key = aws.secret("runpod/operator-api-key")
        pods = get_runpod(key, "pods")
        add(
            checks,
            "info",
            "RunPod 조회 범위",
            f"AWS에 저장된 운영 API 키로 조회한 Pod {len(pods)}개. 개인 CLI 키의 조회 범위와 다를 수 있습니다.",
        )
        for pod in pods:
            volume = pod.get("volumeInGb", 0)
            add(
                checks,
                "warn" if volume else "info",
                "RunPod " + pod["id"],
                f"{pod.get('name')}: {pod.get('desiredStatus')}; volume={volume}GB",
                "개인·학습 Pod는 담당자에게 보존 기한 확인; 자동 삭제하지 않음"
                if volume
                else "",
            )
        for workload in ("f2", "general"):
            selected = selection.get(workload)
            endpoint = aws.parameter("ai/" + ENDPOINT[workload])
            registration = aws.parameter("runpod/" + CONTROL[workload])
            add(
                checks,
                "fail" if ready and not selected else "info",
                workload,
                f"선택={(selected or {}).get('cloud', '없음')}, endpoint={endpoint.get('status')}",
                f"just ai-configure {workload} ..." if not selected else "",
            )
            state, message = image_check(
                registration.get("image", ""),
                workload,
                (selected or {}).get("model_profile"),
                catalog,
            )
            add(
                checks,
                state,
                workload + " 이미지",
                message,
                "just image-publish <f2|general> <ref>; 게시 artifact로 Console 수정 후 register",
            )
            identifier = registration.get("template_id", "")
            if not isinstance(identifier, str) or not re.fullmatch(
                r"[a-z0-9]+", identifier
            ):
                add(checks, "fail", workload + " Template", "Template ID 등록 필요")
                continue
            template = get_runpod(key, "templates/" + identifier)
            problems = []
            if template.get("imageName") != registration.get("image"):
                problems.append("SSM과 이미지 불일치")
            if template.get("containerRegistryAuthId") != registration.get(
                "registry_auth_id"
            ):
                problems.append("SSM과 registry 불일치")
            expected_keys = (
                SECRET_FIELDS["ai/provider-api-keys"][:2]
                if workload == "f2"
                else ("AI_GENERAL_API_KEY",)
            )
            if any(
                (template.get("env") or {}).get(k) != "{{ RUNPOD_SECRET_" + k + " }}"
                for k in expected_keys
            ):
                problems.append("Secret 참조 불일치")
            if (
                template.get("isPublic")
                or template.get("volumeInGb")
                or template.get("networkVolumeId")
            ):
                problems.append("공개/Volume 설정 불일치")
            expected_ports = (
                {"8001/http", "8002/http"} if workload == "f2" else {"8000/http"}
            )
            if set(template.get("ports") or []) != expected_ports:
                problems.append("HTTP 포트/SSH 설정 불일치")
            add(
                checks,
                "fail" if problems else "ok",
                workload + " 등록",
                "; ".join(problems)
                or "SSM·Template 이미지/registry/Secret 참조 일치; 실제 키 일치는 기동 후 검증",
            )
    except (QueryError, KeyError, TypeError, ValueError, AttributeError, IndexError):
        add(
            checks,
            "fail",
            "서빙 등록",
            "SSM/RunPod 등록 조회 실패; 없는 상태로 간주하지 않습니다.",
        )

    try:
        pipeline = PROJECT + "-dev-integrated"
        history = aws.call(
            "codepipeline",
            "list-pipeline-executions",
            "--pipeline-name",
            pipeline,
            "--max-results",
            "1",
        ).get("pipelineExecutionSummaries", [])
        if history:
            latest = history[0]
            add(
                checks,
                "info",
                "통합 배포",
                f"최근 실행={latest['status']}, 시각={latest.get('startTime')}",
            )
            revisions = latest.get("sourceRevisions", [])
            sha = revisions[0].get("revisionId") if revisions else None
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=INFRA,
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip()
            if sha != head:
                add(
                    checks,
                    "warn",
                    "앱 revision",
                    "최근 Pipeline source가 현재 checkout과 다릅니다.",
                    "병합한 dev를 통합 Pipeline으로 배포 후 dev-verify",
                )
        else:
            add(checks, "fail", "통합 배포", "배포 실행 기록 없음")
    except QueryError as error:
        add(checks, "fail", "통합 배포", str(error))
    return checks


def verify_running(
    aws: Aws, workloads: list[str], account: str, profile: str
) -> list[dict]:
    """Invoke only existing synthetic application smoke; never start or switch."""
    groups = aws.call(
        "autoscaling",
        "describe-auto-scaling-groups",
        "--auto-scaling-group-names",
        PROJECT + "-dev-app",
    )["AutoScalingGroups"]
    if not groups or not any(
        i.get("LifecycleState") == "InService" for i in groups[0].get("Instances", [])
    ):
        raise QueryError(
            "앱이 기동되지 않았습니다. operations/README.md의 최초 배포 절차를 먼저 수행하세요."
        )
    for workload in workloads:
        if aws.parameter("ai/" + ENDPOINT[workload]).get("status") != "active":
            raise QueryError(
                f"{workload} endpoint가 offline입니다. 선택·기동 후 다시 실행하세요."
            )
    checks = []
    for workload in workloads:
        result = subprocess.run(
            [
                "uv",
                "run",
                "--script",
                str(INFRA / "scripts/manage_serving.py"),
                "--account-id",
                account,
                "--profile",
                profile,
                "smoke",
                workload,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=900,
        )
        add(
            checks,
            "ok" if result.returncode == 0 else "fail",
            workload,
            "앱 경유 합성 요청 통과"
            if result.returncode == 0
            else "합성 요청 실패; 원문 응답은 숨겼습니다.",
            "just dev-status; CloudWatch 안전 로그 확인" if result.returncode else "",
        )
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("doctor", "ready", "verify"))
    parser.add_argument("--account-id", default=os.environ.get("TARGET_ACCOUNT_ID", ""))
    parser.add_argument(
        "--profile", default=os.environ.get("AWS_PROFILE", "skn30-session")
    )
    parser.add_argument("--workload", choices=("all", "f2", "general"), default="all")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        aws = Aws(args.account_id, args.profile)
        if args.command == "verify":
            workloads = ["f2", "general"] if args.workload == "all" else [args.workload]
            checks = verify_running(aws, workloads, args.account_id, args.profile)
        else:
            checks = inspect_cloud(aws, ready=args.command == "ready")
    except (
        QueryError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        IndexError,
        subprocess.TimeoutExpired,
    ) as error:
        message = (
            str(error)
            if isinstance(error, QueryError)
            else "점검을 완료하지 못했습니다. 연결·설정·도구를 확인하세요. 원문은 숨겼습니다."
        )
        checks = [
            {
                "status": "fail",
                "target": "점검",
                "message": message,
                "next": "aws login --profile skn30-bootstrap",
            }
        ]
    if args.json:
        print(
            json.dumps(
                {
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "checks": checks,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for check in checks:
            print(f"[{check['status'].upper()}] {check['target']}: {check['message']}")
            if check.get("next"):
                print("  다음: " + check["next"])
        print(
            "기동·배포·추론 검증은 별도입니다."
            if args.command != "verify"
            else "이 검증은 모델 품질 평가와 양방향 전환 검증을 대체하지 않습니다."
        )
    return 1 if any(c["status"] == "fail" for c in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
