"""Explicit module-owned local environment injection. No shell/dotenv evaluation."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path

from brokerage_ai.core.errors import ConfigurationError as AiConfigurationError
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]


class LocalInputError(ValueError):
    """Safe diagnostic containing only fixed text and environment names."""


class Role(StrEnum):
    API = "api"
    WORKER = "worker"
    CONFIG = "config"
    MODEL = "model"


def module_values(root: Path, module: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for filename in (".env.local", ".env"):
        path = root / module / filename
        if path.is_symlink():
            raise LocalInputError(
                f"{module}/{filename}: symbolic links are not supported"
            )
        current = {
            k: v
            for k, v in dotenv_values(path, interpolate=False).items()
            if v is not None
        }
        wrong = [key for key in current if key.startswith("AI_") != (module == "ai")]
        if wrong:
            raise LocalInputError(
                f"{module}/{filename}: wrong owner for " + ", ".join(sorted(wrong))
            )
        values.update(current)
    return values


def environment(root: Path, role: Role, process: Mapping[str, str]) -> dict[str, str]:
    if process.get("APP_ENV", "local") != "local":
        raise LocalInputError(
            "local launcher requires APP_ENV=local; shared deployments use Infra injection"
        )
    backend = module_values(root, "backend")
    ai = module_values(root, "ai")
    if backend.keys() & ai.keys():
        raise LocalInputError("duplicate module environment ownership")
    result = {**backend, **ai, **process}
    if result.get("APP_ENV") != "local":
        raise LocalInputError("local launcher requires APP_ENV=local")
    if role is Role.WORKER:
        result = {
            k: v for k, v in result.items() if not k.startswith(("AI_F2_", "AI_VLLM_"))
        }
    if role is Role.API and result.get("CHATBOT_ENABLED", "").strip().lower() not in {
        "true",
        "1",
        "yes",
        "on",
    }:
        result.pop("AI_GENERAL_API_KEY", None)
        result.pop("AI_GENERAL_BASE_URL", None)
    result["PYTHONPATH"] = str(root / "backend/src")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", type=Role, choices=list(Role))
    args, rest = parser.parse_known_args()
    try:
        values = environment(ROOT, args.role, os.environ)
        sys.path.insert(0, str(ROOT / "backend/src"))
        from brokerage_ai import bind_ai_config
        from core.config import load_config

        config = load_config("local", values)
        ai = bind_ai_config(values, "local")
        if args.role is Role.WORKER:
            from worker import require_synthetic_prototype_opt_in

            require_synthetic_prototype_opt_in(config)
            if ai.openai is None and not ai.llm_endpoints:
                raise LocalInputError("Worker requires a general provider connection")
        if args.role is Role.CONFIG:
            print(
                f"Configuration valid. general={ai.general.provider}/{ai.general.model}; F2={ai.f2.provider_status}. No DB/provider connection performed."
            )
            return
    except (ValueError, OSError, RuntimeError, AiConfigurationError) as error:
        # Do not print Pydantic errors which may contain a secret input.
        if isinstance(error, LocalInputError):
            parser.exit(2, str(error) + "\n")
        parser.exit(
            2,
            "Configuration invalid. Check module ownership, required DB input and enum choices; values are hidden.\n",
        )
    target = {
        Role.API: "server.py",
        Role.WORKER: "worker.py",
        Role.MODEL: "model_selection.py",
    }[args.role]
    os.chdir(ROOT / "backend")
    os.execve(
        sys.executable,
        [sys.executable, str(ROOT / "backend/src" / target), *rest],
        values,
    )


if __name__ == "__main__":
    main()
