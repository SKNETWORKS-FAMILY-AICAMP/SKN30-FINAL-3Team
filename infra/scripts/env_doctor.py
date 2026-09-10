#!/usr/bin/env python3
"""Inspect local configuration without displaying or copying private values."""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import secrets
import stat
import subprocess
import tempfile
from enum import Enum
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSIGNMENT = re.compile(r"^(\s*(?:export\s+)?)([A-Za-z_][A-Za-z0-9_]*)(\s*=.*)$")
RENAMES = {
    "ai": {
        "AI_VLLM_LLM_API_KEY": "AI_VLLM_SLLM_API_KEY",
        "AI_VLLM_LLM_BASE_URL": "AI_VLLM_SLLM_BASE_URL",
    },
    "backend": {
        "AI_VLLM_LLM_API_KEY": "AI_VLLM_SLLM_API_KEY",
        "AI_VLLM_LLM_BASE_URL": "AI_VLLM_SLLM_BASE_URL",
    },
    "frontend": {"VITE_BACKEND_ORIGIN": "FRONTEND_BACKEND_ORIGIN"},
}
PRIVATE_FILES = (
    "ai/.env",
    "backend/.env",
    "frontend/.env",
    "infra/.env",
    "infra/local/.env",
)
ENV_NAME = re.compile(
    r"(?:APP|AUTH|DB|HTTP|LOG|WORKER|F2|F3|CHATBOT|AI|VITE|FRONTEND|TEST)_[A-Z0-9_]*[A-Z0-9]"
)


class LocalProvider(str, Enum):
    OPENAI = "openai"

    def __str__(self) -> str:
        return self.value


def environment_names(root: Path, module: str) -> set[str]:
    """Read consumer definitions without importing the app or reading secrets."""
    sources = {
        "backend": ("backend/src/core/config.py",),
        "ai": ("ai/src/brokerage_ai/core/config.py",),
        "frontend": ("frontend/src/config/envSchema.ts", "frontend/vite.config.mjs"),
    }
    names = set()
    for relative in sources.get(module, ()):
        path = root / relative
        if not path.exists():
            continue
        source = path.read_text()
        if path.suffix == ".py":
            literals = [
                n.value
                for n in ast.walk(ast.parse(source))
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
            ]
        else:
            literals = re.findall(r'["\']([A-Z][A-Z0-9_]+)["\']', source)
        names.update(value for value in literals if ENV_NAME.fullmatch(value))
    return names - {
        "APP_OPENAPI_ENABLED",
        "WORKER_ENABLED",
        "WORKER_READY_FILE",
        "WORKER_ID",
        "AUTH_SESSION_COOKIE_NAME",
        "AUTH_CSRF_COOKIE_NAME",
        "AI_LLM_ENDPOINTS",
        "AI_F2_PROVIDER_STATUS",
        "AI_OPENAI_API_KEY",
        "AI_OPENAI_BASE_URL",
    }


def documented_names(text: str) -> set[str]:
    return set(
        entries(
            "\n".join(line.lstrip().removeprefix("# ") for line in text.splitlines())
        )
    )


def effective_values(
    module: str, public: dict[str, str], private: dict[str, str]
) -> dict[str, str]:
    if module == "backend" and os.environ.get("APP_ENV", "local") != "local":
        return dict(os.environ)
    return {**public, **private, **os.environ}


def combination_checks(module: str, values: dict[str, str]) -> list[dict]:
    checks = []

    def warn(message: str) -> None:
        checks.append(
            {"status": "warn", "target": module + " 설정 조합", "message": message}
        )

    def enabled(name: str) -> bool:
        return values.get(name, "").strip().lower() in {"true", "1", "yes", "on"}

    if (
        module == "backend"
        and values.get("APP_ENV") == "prod"
        and (enabled("CHATBOT_ENABLED") or enabled("AUTH_DEVELOPMENT_ENABLED"))
    ):
        warn("prod에서 챗봇·개발 인증을 활성화할 수 없습니다.")
    if module == "ai":
        urls = [
            bool(values.get(key))
            for key in ("AI_VLLM_SLLM_BASE_URL", "AI_VLLM_STT_BASE_URL")
        ]
        if any(urls) and not all(urls):
            warn("F2는 SLLM/STT URL을 함께 설정하거나 둘 다 제거해야 합니다.")
        if values.get("AI_GENERAL_PROVIDER") in {"vllm", "llama_cpp"} and (
            bool(values.get("AI_GENERAL_BASE_URL"))
            != bool(values.get("AI_GENERAL_API_KEY"))
        ):
            warn("범용 자체 서버 URL과 API key를 함께 설정해야 합니다.")
    if module == "backend" and any(
        key.startswith("AI_") for key in values if key not in os.environ
    ):
        warn(
            "AI 입력은 ai/.env로 이전하세요. Backend 개인 파일에 중복 선언할 수 없습니다."
        )
    flags = (
        {
            "AUTH_DEVELOPMENT_ENABLED",
            "CHATBOT_ENABLED",
            "F3_ALLOW_SYNTHETIC_PROTOTYPE",
        }
        if module == "backend"
        else {"VITE_AUTH_DEVELOPMENT_ENABLED"}
        if module == "frontend"
        else set()
    )
    for key in flags & values.keys():
        value = values[key]
        if (
            (key.endswith("_ENABLED") or key == "F3_ALLOW_SYNTHETIC_PROTOTYPE")
            and value.strip()
            and value not in {"true", "false"}
        ):
            warn(
                key
                + ": 작성 규칙은 true/false입니다. 기존 Backend 별칭은 읽기 호환만 유지합니다."
            )
    return checks


def mode_checks(
    module: str, values: dict[str, str], private: dict[str, str]
) -> list[dict]:
    """Expose only bounded, non-secret mode values and their input layer."""
    modes = {
        "APP_ENV": {"local", "dev", "test", "prod"},
        "F3_ALLOW_SYNTHETIC_PROTOTYPE": {
            "true",
            "false",
            "1",
            "0",
            "yes",
            "no",
            "on",
            "off",
        },
        "CHATBOT_ENABLED": {"true", "false", "1", "0", "yes", "no", "on", "off"},
        "AI_GENERAL_PROVIDER": {"openai", "vllm", "llama_cpp", "bedrock"},
        "VITE_LEDGER_SOURCE": {"mock", "api"},
        "VITE_F3_SOURCE": {"mock", "api"},
        "VITE_CALENDAR_SOURCE": {"mock", "api"},
    }
    result = []
    for key, accepted in modes.items():
        if module == "frontend" and not key.startswith("VITE_"):
            continue
        if module == "ai" and not key.startswith("AI_"):
            continue
        if module == "backend" and key.startswith("VITE_"):
            continue
        if key not in values:
            continue
        value = values[key].strip().lower()
        origin = (
            "process env"
            if key in os.environ
            else ".env"
            if key in private
            else ".env.local"
        )
        shown = value if value in accepted else "미설정/유효값 확인 필요"
        if not value and key in {"VITE_F3_SOURCE", "VITE_CALENDAR_SOURCE"}:
            inherited = values.get("VITE_LEDGER_SOURCE")
            shown = "장부 출처 상속: " + (
                inherited if inherited in {"mock", "api"} else "유효값 확인 필요"
            )
        result.append(
            {
                "status": "info",
                "target": module + "/" + key,
                "message": shown + " (출처: " + origin + ")",
            }
        )
    return result


def entries(text: str) -> dict[str, str]:
    result = {}
    for line in text.splitlines():
        match = ASSIGNMENT.fullmatch(line)
        if match:
            raw = match[3].split("=", 1)[1].strip()
            if raw.startswith(("'", '"')):
                quoted = re.match(r"""(['"])((?:\\.|(?!\1).)*)\1""", raw)
                raw = quoted[2] if quoted else raw
            else:
                raw = re.split(r"\s+#", raw, maxsplit=1)[0].rstrip()
            result[match[2]] = raw
    return result


def tracked(root: Path, path: Path) -> bool:
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", str(path.relative_to(root))],
        cwd=root,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def rewrite_names(text: str, renames: dict[str, str]) -> tuple[str, list[str]]:
    """Preserve values/comments exactly; ambiguous assignments require a human."""
    for line in text.splitlines():
        match = ASSIGNMENT.fullmatch(line)
        if not match:
            continue
        value = match[3].split("=", 1)[1].lstrip()
        if not value or value[0] not in {"'", '"'}:
            continue
        escaped = False
        for character in value[1:]:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == value[0]:
                break
        else:
            raise ValueError(
                "여러 줄 또는 닫히지 않은 인용 값이 있습니다. 자동 수정하지 않습니다."
            )
    keys = [m[2] for line in text.splitlines() if (m := ASSIGNMENT.fullmatch(line))]
    for old, new in renames.items():
        if old in keys and (new in keys or keys.count(old) > 1):
            raise ValueError(
                f"{old} / {new}: 중복 설정을 직접 정리하세요. 값은 출력하지 않습니다."
            )
    changed = []
    lines = []
    for line in text.splitlines(keepends=True):
        # A rename is only safe at a physical assignment line; no value parsing.
        match = ASSIGNMENT.fullmatch(line.rstrip("\r\n"))
        if match and match[2] in renames:
            old = match[2]
            line = (
                line[: len(match[1])] + renames[old] + line[len(match[1]) + len(old) :]
            )
            changed.append(f"{old} → {renames[old]}")
        lines.append(line)
    return "".join(lines), changed


def private_write(path: Path, text: str) -> None:
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def rewrite_openai_inputs(
    text: str, public: str, local_provider: LocalProvider | None = None
) -> tuple[str, list[str]]:
    """Migrate only unambiguous OpenAI file inputs; never pick between keys."""
    renames = {
        "AI_OPENAI_API_KEY": "AI_GENERAL_API_KEY",
        "AI_OPENAI_BASE_URL": "AI_GENERAL_BASE_URL",
    }
    private = entries(text)
    legacy = set(renames) & private.keys()
    if not legacy:
        return text, []
    # Validate physical assignments first. The literal parser does not support
    # multiline values, and duplicate assignments must not silently select one.
    rewrite_names(text, {})
    names = [m[2] for line in text.splitlines() if (m := ASSIGNMENT.fullmatch(line))]
    relevant = (
        set(renames)
        | set(renames.values())
        | {"AI_GENERAL_PROVIDER", "AI_GENERAL_AWS_REGION"}
    )
    if any(names.count(name) > 1 for name in relevant):
        raise ValueError("범용 Provider 입력이 중복입니다. 값은 출력하지 않습니다.")
    provider = {**entries(public), **private}.get("AI_GENERAL_PROVIDER", "openai")
    if provider not in {"openai", "vllm", "llama_cpp", "bedrock"}:
        raise ValueError(
            "AI_GENERAL_PROVIDER 허용값: openai | vllm | llama_cpp | bedrock. "
            "개인 파일의 선택을 확인하세요. 값은 출력하지 않습니다."
        )
    if local_provider is not None:
        LocalProvider(local_provider)
        if not private.get("AI_OPENAI_API_KEY"):
            raise ValueError(
                "명시 이전에는 비어 있지 않은 AI_OPENAI_API_KEY가 필요합니다. "
                "기존 GENERAL 키를 OpenAI 키로 추정하지 않습니다."
            )
        # The original file is backed up before this rewrite is installed.
        # Remove the GPU URL as well as its key, so the OpenAI key cannot be
        # sent to the old self-hosted endpoint. Missing legacy URL uses default.
        replaced = set(renames.values()) | {
            "AI_GENERAL_PROVIDER",
            "AI_GENERAL_AWS_REGION",
        }
        lines = []
        for line in text.splitlines(keepends=True):
            match = ASSIGNMENT.fullmatch(line.rstrip("\r\n"))
            if not match or match[2] not in replaced:
                lines.append(line)
        result, changes = rewrite_names("".join(lines), renames)
        newline = "\r\n" if "\r\n" in text else "\n"
        if result and not result.endswith(("\n", "\r")):
            result += newline
        result += "AI_GENERAL_PROVIDER=openai" + newline
        return result, changes + ["로컬 Provider를 openai로 명시; 원본 백업 후 이전"]
    if provider != "openai":
        raise ValueError(
            "AI_OPENAI_*는 openai 선택에서만 AI_GENERAL_*로 이전합니다. "
            "다른 Provider의 키로 덮어쓰지 않습니다. 기존 OpenAI 입력을 "
            "별도 비밀 저장소에 보존한 뒤 활성 .env에서 직접 정리하세요."
        )
    for old in sorted(legacy):
        new = renames[old]
        if new in private and private[old] != private[new]:
            raise ValueError(
                f"{old} / {new}: 서로 다른 입력이 있어 자동 이전하지 않습니다. "
                "openai에 사용할 입력을 확인하고 다른 입력은 별도 비밀 저장소에 "
                "보존한 뒤 직접 정리하세요. 값은 출력하지 않습니다."
            )
    duplicate_old = {old for old in legacy if renames[old] in private}
    lines = []
    for line in text.splitlines(keepends=True):
        match = ASSIGNMENT.fullmatch(line.rstrip("\r\n"))
        if not match or match[2] not in duplicate_old:
            lines.append(line)
    result, changes = rewrite_names(
        "".join(lines),
        {old: new for old, new in renames.items() if old not in duplicate_old},
    )
    changes.extend(
        f"{old}: 동일한 {renames[old]} 입력으로 통합" for old in sorted(duplicate_old)
    )
    return result, changes


def private_backup(root: Path, path: Path, text: str) -> None:
    """Create an ignored, exclusive 0600 backup before replacing any input."""
    backup = path.with_name(f".env.migration-backup-{secrets.token_hex(12)}")
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "--", str(backup.relative_to(root))],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if ignored.returncode != 0 or tracked(root, backup):
        raise ValueError(
            "원본 백업 경로가 Git ignored 상태가 아닙니다. 이전하지 않습니다."
        )
    fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w", newline="") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        backup.unlink(missing_ok=True)
        raise


def inspect(
    root: Path, *, fix: bool = False, local_provider: LocalProvider | None = None
) -> list[dict]:
    if local_provider is not None:
        local_provider = LocalProvider(local_provider)
        if not fix:
            raise ValueError("--local-provider는 --fix와 함께 지정해야 합니다.")
    checks = []
    resolved = {}
    for relative in PRIVATE_FILES:
        path = root / relative
        if path.is_symlink():
            checks.append(
                {
                    "status": "fail",
                    "target": relative,
                    "message": "symlink 개인 파일은 자동 처리하지 않습니다.",
                }
            )
            continue
        if not path.exists():
            checks.append(
                {
                    "status": "info",
                    "target": relative,
                    "message": "개인 파일 없음; 필요한 모듈만 .env.example에서 준비하세요.",
                }
            )
            module = relative.split("/")[0]
            public = root / module / ".env.local"
            if module in RENAMES and public.exists():
                resolved[module] = effective_values(
                    module, entries(public.read_text()), {}
                )
                checks.extend(combination_checks(module, resolved[module]))
                checks.extend(mode_checks(module, resolved[module], {}))
            continue
        if tracked(root, path):
            checks.append(
                {
                    "status": "fail",
                    "target": relative,
                    "message": "개인 파일이 Git 추적 중입니다. 자동 수정하지 않습니다.",
                }
            )
            continue
        with path.open(newline="") as stream:
            text = stream.read()
        try:
            rewritten, changes = rewrite_names(
                text, RENAMES.get(relative.split("/")[0], {})
            )
            if relative == "ai/.env":
                public_path = root / "ai/.env.local"
                rewritten, openai_changes = rewrite_openai_inputs(
                    rewritten,
                    public_path.read_text() if public_path.exists() else "",
                    local_provider,
                )
                changes.extend(openai_changes)
        except ValueError as error:
            checks.append({"status": "fail", "target": relative, "message": str(error)})
            continue
        insecure = bool(stat.S_IMODE(path.stat().st_mode) & 0o077)
        if fix and (changes or insecure):
            if (
                local_provider is not None
                and relative == "ai/.env"
                and rewritten != text
            ):
                try:
                    private_backup(root, path, text)
                except ValueError as error:
                    checks.append(
                        {"status": "fail", "target": relative, "message": str(error)}
                    )
                    continue
            private_write(path, rewritten)
            checks.append(
                {
                    "status": "ok",
                    "target": relative,
                    "message": "; ".join(changes + ["파일 권한 600; 비밀값 유지"]),
                }
            )
            text = rewritten
        else:
            checks.append(
                {
                    "status": "warn" if changes or insecure else "ok",
                    "target": relative,
                    "message": "; ".join(
                        changes + (["권한 600 필요"] if insecure else [])
                    )
                    or "변수명·파일 권한 정상",
                }
            )
        module = relative.split("/")[0]
        if module in RENAMES:
            public = root / module / ".env.local"
            example = root / module / ".env.example"
            allowed = environment_names(root, module)
            allowed.update(
                documented_names(example.read_text()) if example.exists() else {}
            )
            private = entries(text)
            merged = effective_values(
                module, entries(public.read_text()) if public.exists() else {}, private
            )
            unknown = sorted(set(private) - allowed - set(RENAMES[module]))
            if unknown:
                checks.append(
                    {
                        "status": "warn",
                        "target": relative,
                        "message": "설정 목록에 없는 이름: " + ", ".join(unknown),
                    }
                )
            resolved[module] = merged
            checks.extend(combination_checks(module, merged))
            checks.extend(mode_checks(module, merged, private))
            if (
                module == "ai"
                and merged.get("AI_GENERAL_PROVIDER", "openai") == "openai"
                and not merged.get("AI_GENERAL_API_KEY")
            ):
                checks.append(
                    {
                        "status": "info",
                        "target": relative,
                        "message": "개인 OpenAI 키 없음. ai/.env의 AI_GENERAL_API_KEY에 선택한 Provider 키를 입력하세요.",
                    }
                )
    backend = resolved.get("backend", {})
    frontend = resolved.get("frontend", {})
    backend_auth = backend.get("AUTH_DEVELOPMENT_ENABLED", "").lower()
    frontend_auth = frontend.get("VITE_AUTH_DEVELOPMENT_ENABLED", "").lower()
    if (
        backend_auth
        and frontend_auth
        and (backend_auth in {"true", "1", "yes", "on"}) != (frontend_auth == "true")
    ):
        checks.append(
            {
                "status": "warn",
                "target": "개발 인증",
                "message": "Backend route 허용과 Frontend 로그인 UI 표시가 다릅니다.",
            }
        )
    dev = root / "infra/environments/dev"
    for path in sorted(dev.glob("*.auto.tfvars.json")):
        if path.name not in {
            "gpu-profiles.auto.tfvars.json",
            "serving-capacity.auto.tfvars.json",
        }:
            checks.append(
                {
                    "status": "warn",
                    "target": str(path.relative_to(root)),
                    "message": "표준 이름 외 자동 로딩 입력입니다. gpu-profiles-import로 검토 후 root 밖으로 분리하세요.",
                }
            )
    plans = list(dev.glob("*.tfplan"))
    if plans:
        checks.append(
            {
                "status": "info",
                "target": "saved plan",
                "message": f"{len(plans)}개 존재. 예전 plan은 재사용하지 말고 현재 입력으로 *-plan → *-show를 실행하세요.",
            }
        )
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--fix", action="store_true", help="ignored 개인 파일의 옛 변수명과 권한만 수정"
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--local-provider",
        type=LocalProvider,
        choices=list(LocalProvider),
        help="허용 openai; --fix와 함께 원본 600 백업 후 로컬 OpenAI 키로 명시 이전",
    )
    args = parser.parse_args()
    if args.local_provider is not None and not args.fix:
        parser.error("--local-provider는 --fix와 함께 지정해야 합니다.")
    try:
        checks = inspect(
            args.root.resolve(), fix=args.fix, local_provider=args.local_provider
        )
    except (OSError, UnicodeError):
        print(
            "개인 파일을 읽을 수 없습니다. 경로·권한을 확인하세요. 값은 출력하지 않습니다."
        )
        return 2
    if args.json:
        print(json.dumps(checks, ensure_ascii=False, indent=2))
    else:
        for check in checks:
            print(f"[{check['status'].upper()}] {check['target']}: {check['message']}")
        if not args.fix and any(c["status"] == "warn" for c in checks):
            print("다음: just env-fix (해당 checkout의 개인 파일만 정리)")
    return 1 if any(c["status"] == "fail" for c in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
