"""Pinned general model runtime; the same image runs on AWS and RunPod."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from model_profiles import DEFAULT_PROFILE, load_profile, verify_weights

MODEL = "unsloth/Qwen3.8-27B-unsloth-bnb-4bit"
REVISION = "8aa5f05d26b7205477066e1449e0af13f762a299"


def build_command(model: str, profile_name: str = DEFAULT_PROFILE) -> list[str]:
    profile = load_profile(profile_name)
    return [
        "vllm",
        "serve",
        model,
        "--served-model-name",
        profile["model"],
        "--revision",
        profile["revision"],
        "--tokenizer-revision",
        profile["revision"],
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
        "--quantization",
        profile["quantization"],
        "--load-format",
        profile["load_format"],
        "--max-model-len",
        str(profile["max_model_len"]),
        "--max-num-seqs",
        str(profile["max_num_seqs"]),
        "--gpu-memory-utilization",
        str(profile["gpu_memory_utilization"]),
        "--enforce-eager",
        "--limit-mm-per-prompt",
        json.dumps({"image": 0, "video": 0}),
        "--default-chat-template-kwargs",
        json.dumps({"enable_thinking": False}),
        "--no-enable-log-requests",
        "--disable-uvicorn-access-log",
        "--disable-fastapi-docs",
        "--middleware",
        "general_middleware.ServingRoutes",
    ]


def prepare_model(model: str, profile: dict) -> tuple[str, str]:
    if model == profile["model"]:
        from huggingface_hub import snapshot_download

        model = snapshot_download(
            repo_id=profile["model"], revision=profile["revision"]
        )
    return model, verify_weights(Path(model), profile)


def main() -> None:
    key = os.environ.get("AI_GENERAL_API_KEY", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", key):
        raise ValueError("AI_GENERAL_API_KEY must be a resolved service credential")
    # A mounted, immutable snapshot is used on AWS; RunPod downloads the same commit.
    profile_name = os.environ.get("GENERAL_MODEL_PROFILE", DEFAULT_PROFILE)
    profile = load_profile(profile_name)
    model = os.environ.get("GENERAL_MODEL_PATH", profile["model"])
    if model != profile["model"] and model != "/models/general":
        raise ValueError("unexpected general model location")
    if model == "/models/general" and not Path(model, "config.json").is_file():
        raise ValueError("general model snapshot is missing")
    # Public snapshots must never use inherited cloud/Hugging Face credentials.
    for name in (
        "HF_TOKEN",
        "HUGGING_FACE_HUB_TOKEN",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
    ):
        os.environ.pop(name, None)
    # Download on the GPU host only, before opening inference. Check actual bytes.
    model, artifact_hash = prepare_model(model, profile)
    metadata = {
        "profile": profile_name,
        "model": profile["model"],
        "revision": profile["revision"],
        "artifact_sha256": artifact_hash,
        "runtime_version": profile["runtime_version"],
        "runtime_image": profile["runtime_image"],
    }
    os.environ["GENERAL_MODEL_METADATA"] = json.dumps(metadata)
    print(json.dumps({"event": "model-weights-verified", **metadata}), flush=True)
    os.environ["VLLM_API_KEY"] = key
    os.environ["PYTHONPATH"] = "/opt/general"
    os.environ["VLLM_SERVER_DEV_MODE"] = "0"
    os.environ["VLLM_DEBUG_LOG_API_SERVER_RESPONSE"] = "0"
    os.environ.pop("AI_GENERAL_API_KEY", None)
    command = build_command(model, profile_name)
    os.execvp(command[0], command)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError):
        print("general serving configuration/startup failed", file=sys.stderr)
        sys.exit(64)
