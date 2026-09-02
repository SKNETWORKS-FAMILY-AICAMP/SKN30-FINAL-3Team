#!/usr/bin/env python3
"""Bootstrap one SLLM release and supervise the SLLM and STT vLLM services."""

from __future__ import annotations

import hmac
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from artifact_bootstrap import BootstrapError, Release, bootstrap

SHUTDOWN_GRACE_SECONDS = 30
API_KEY_PATTERN = re.compile(r"[A-Za-z0-9_-]{43,128}\Z")
MODEL_ID_PATTERN = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*\Z"
)
MODEL_REVISION_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
CONTROL_KEYS = {
    "AI_VLLM_SLLM_API_KEY",
    "AI_VLLM_STT_API_KEY",
    "F2_SLLM_BUNDLE_URL",
    "RUNPOD_API_KEY",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "GHCR_TOKEN",
    "GITHUB_TOKEN",
}


class ConfigurationError(ValueError):
    """Runtime setting violates the shared serving contract."""


@dataclass(frozen=True)
class RuntimeConfig:
    sllm_model_id: str
    sllm_model_revision: str
    sllm_adapter_path: str
    stt_model_id: str
    stt_model_revision: str
    sllm_max_model_len: int
    sllm_gpu_memory_utilization: float
    stt_gpu_memory_utilization: float
    sllm_api_key: str
    stt_api_key: str


def _secret(source: dict[str, str], name: str) -> str:
    value = source.get(name, "")
    if (
        not value
        or value.startswith("{{ RUNPOD_SECRET_")
        or API_KEY_PATTERN.fullmatch(value) is None
    ):
        raise ConfigurationError(
            f"{name} must resolve to a 43-128 character URL-safe RunPod Secret"
        )
    return value


def _bounded_float(source: dict[str, str], name: str, default: str) -> float:
    try:
        value = float(source.get(name, default))
    except ValueError as error:
        raise ConfigurationError(f"{name} must be numeric") from error
    if not 0 < value < 1:
        raise ConfigurationError(f"{name} must be greater than 0 and less than 1")
    return value


def load_config(
    release: Release, environment: dict[str, str] | None = None
) -> RuntimeConfig:
    source = dict(os.environ if environment is None else environment)
    stt_model = source.get("F2_STT_MODEL_ID", "").strip()
    stt_revision = source.get("F2_STT_MODEL_REVISION", "").strip()
    if MODEL_ID_PATTERN.fullmatch(stt_model) is None:
        raise ConfigurationError(
            "F2_STT_MODEL_ID must be a Hugging Face owner/model ID"
        )
    if MODEL_REVISION_PATTERN.fullmatch(stt_revision) is None:
        raise ConfigurationError(
            "F2_STT_MODEL_REVISION must be an immutable 40-character commit"
        )
    try:
        max_length = int(source.get("F2_SLLM_MAX_MODEL_LEN", "4096"))
    except ValueError as error:
        raise ConfigurationError("F2_SLLM_MAX_MODEL_LEN must be an integer") from error
    if not 1 <= max_length <= 131_072:
        raise ConfigurationError("F2_SLLM_MAX_MODEL_LEN must be between 1 and 131072")
    sllm_memory = _bounded_float(source, "F2_SLLM_GPU_MEMORY_UTILIZATION", "0.65")
    stt_memory = _bounded_float(source, "F2_STT_GPU_MEMORY_UTILIZATION", "0.20")
    if sllm_memory + stt_memory > 0.95:
        raise ConfigurationError("combined GPU memory utilization must not exceed 0.95")
    sllm_key = _secret(source, "AI_VLLM_SLLM_API_KEY")
    stt_key = _secret(source, "AI_VLLM_STT_API_KEY")
    if hmac.compare_digest(sllm_key, stt_key):
        raise ConfigurationError("SLLM and STT API keys must be different")
    return RuntimeConfig(
        release.base_model_id,
        release.base_model_revision,
        release.adapter_path,
        stt_model,
        stt_revision,
        max_length,
        sllm_memory,
        stt_memory,
        sllm_key,
        stt_key,
    )


def build_commands(config: RuntimeConfig, executable: str) -> dict[str, list[str]]:
    common = [
        "--host",
        "127.0.0.1",
        "--disable-log-requests",
        "--disable-uvicorn-access-log",
    ]
    sllm = [
        executable,
        "serve",
        config.sllm_model_id,
        "--revision",
        config.sllm_model_revision,
        "--tokenizer-revision",
        config.sllm_model_revision,
        "--served-model-name",
        "sllm-base",
        "--port",
        "18001",
        "--dtype",
        "bfloat16",
        "--max-model-len",
        str(config.sllm_max_model_len),
        "--gpu-memory-utilization",
        str(config.sllm_gpu_memory_utilization),
        "--default-chat-template-kwargs",
        '{"enable_thinking":false}',
        "--enable-lora",
        "--lora-modules",
        f"sllm={config.sllm_adapter_path}",
        *common,
    ]
    stt = [
        executable,
        "serve",
        config.stt_model_id,
        "--revision",
        config.stt_model_revision,
        "--tokenizer-revision",
        config.stt_model_revision,
        "--served-model-name",
        "stt",
        "--port",
        "18002",
        "--gpu-memory-utilization",
        str(config.stt_gpu_memory_utilization),
        *common,
    ]
    return {"sllm": sllm, "stt": stt}


def _clean_environment(environment: dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in environment.items() if key not in CONTROL_KEYS}


def _model_environment(
    environment: dict[str, str], *, api_key: str, stt: bool = False
) -> dict[str, str]:
    result = _clean_environment(environment)
    result.update(
        {
            "CUDA_VISIBLE_DEVICES": "0",
            "VLLM_API_KEY": api_key,
            "VLLM_NO_USAGE_STATS": "1",
        }
    )
    if stt:
        result["VLLM_MAX_AUDIO_CLIP_FILESIZE_MB"] = "25"
    return result


def _proxy_environment(environment: dict[str, str], api_key: str) -> dict[str, str]:
    result = _clean_environment(environment)
    result.pop("HF_TOKEN", None)
    result["F2_PROXY_API_KEY"] = api_key
    return result


def _start(command: list[str], environment: dict[str, str]) -> subprocess.Popen[bytes]:
    return subprocess.Popen(command, env=environment, start_new_session=True)


def _proxy_command(service: str, listen: int, upstream: int) -> list[str]:
    return [
        sys.executable,
        str(Path(__file__).with_name("auth_proxy.py")),
        "--listen-port",
        str(listen),
        "--upstream-port",
        str(upstream),
        "--service",
        service,
    ]


def _stop(processes: list[subprocess.Popen[bytes]]) -> None:
    for process in processes:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    deadline = time.monotonic() + SHUTDOWN_GRACE_SECONDS
    while time.monotonic() < deadline and any(p.poll() is None for p in processes):
        time.sleep(0.1)
    for process in processes:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def run() -> int:
    try:
        release = bootstrap()
        config = load_config(release)
    except (BootstrapError, ConfigurationError) as error:
        print(f"f2-serving configuration error: {error}", file=sys.stderr, flush=True)
        return 64
    executable = shutil.which("vllm")
    if executable is None:
        print(
            "f2-serving startup error: vllm is unavailable", file=sys.stderr, flush=True
        )
        return 70
    environment = os.environ.copy()
    commands = build_commands(config, executable)
    requested: list[int] = []
    signal.signal(signal.SIGTERM, lambda number, _frame: requested.append(number))
    signal.signal(signal.SIGINT, lambda number, _frame: requested.append(number))
    serving: dict[str, subprocess.Popen[bytes]] = {}
    try:
        print(
            f"f2-serving: starting sllm release {release.release_id} and stt",
            flush=True,
        )
        serving["sllm-vllm"] = _start(
            commands["sllm"],
            _model_environment(environment, api_key=config.sllm_api_key),
        )
        serving["sllm-proxy"] = _start(
            _proxy_command("sllm", 8001, 18001),
            _proxy_environment(environment, config.sllm_api_key),
        )
        serving["stt-vllm"] = _start(
            commands["stt"],
            _model_environment(environment, api_key=config.stt_api_key, stt=True),
        )
        serving["stt-proxy"] = _start(
            _proxy_command("stt", 8002, 18002),
            _proxy_environment(environment, config.stt_api_key),
        )
        while True:
            if requested:
                return 128 + requested[0]
            stopped = next(
                (
                    (name, process)
                    for name, process in serving.items()
                    if process.poll() is not None
                ),
                None,
            )
            if stopped:
                name, process = stopped
                print(
                    f"f2-serving: {name} exited with status {process.returncode}; stopping container",
                    file=sys.stderr,
                    flush=True,
                )
                return process.returncode if process.returncode not in (None, 0) else 1
            time.sleep(0.25)
    finally:
        _stop(list(serving.values()))


if __name__ == "__main__":
    raise SystemExit(run())
