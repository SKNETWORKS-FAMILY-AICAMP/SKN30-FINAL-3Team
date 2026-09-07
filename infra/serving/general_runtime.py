"""Pinned general model runtime; the same image runs on AWS and RunPod."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

MODEL = "unsloth/Qwen3.8-27B-unsloth-bnb-4bit"
REVISION = "8aa5f05d26b7205477066e1449e0af13f762a299"


def main() -> None:
    key = os.environ.get("AI_GENERAL_API_KEY", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", key):
        raise ValueError("AI_GENERAL_API_KEY must be a resolved service credential")
    # A mounted, immutable snapshot is used on AWS; RunPod downloads the same commit.
    model = os.environ.get("GENERAL_MODEL_PATH", MODEL)
    if model != MODEL and model != "/models/general":
        raise ValueError("unexpected general model location")
    if model == "/models/general" and not Path(model, "config.json").is_file():
        raise ValueError("general model snapshot is missing")
    os.environ["VLLM_API_KEY"] = key
    os.environ["PYTHONPATH"] = "/opt/general"
    os.environ["VLLM_SERVER_DEV_MODE"] = "0"
    os.environ["VLLM_DEBUG_LOG_API_SERVER_RESPONSE"] = "0"
    os.environ.pop("AI_GENERAL_API_KEY", None)
    for name in (
        "HF_TOKEN",
        "HUGGING_FACE_HUB_TOKEN",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
    ):
        os.environ.pop(name, None)
    command = [
        "vllm",
        "serve",
        model,
        "--served-model-name",
        MODEL,
        "--revision",
        REVISION,
        "--tokenizer-revision",
        REVISION,
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
        "--quantization",
        "bitsandbytes",
        "--load-format",
        "bitsandbytes",
        "--max-model-len",
        "8192",
        "--max-num-seqs",
        "1",
        "--gpu-memory-utilization",
        "0.85",
        "--enforce-eager",
        "--limit-mm-per-prompt",
        json.dumps({"image": 0, "video": 0}),
        "--default-chat-template-kwargs",
        json.dumps({"enable_thinking": False}),
        "--disable-log-requests",
        "--disable-uvicorn-access-log",
        "--disable-fastapi-docs",
        "--middleware",
        "general_middleware.ServingRoutes",
    ]
    os.execvp(command[0], command)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError):
        print("general serving configuration/startup failed", file=sys.stderr)
        sys.exit(64)
