"""Credential-free, pinned general model profiles used by serving operations."""

from __future__ import annotations

import hashlib
import json
import re
from enum import Enum
from pathlib import Path


class GeneralModelProfile(str, Enum):
    QWEN3_14B_AWQ = "qwen3-14b-awq"
    QWEN3_32B_AWQ = "qwen3-32b-awq"
    QWEN38_27B_BNB = "qwen38-27b-bnb"
    QWEN38_27B_FP8 = "qwen38-27b-fp8"


# Menu/discovery default only; runtime entrypoints require an explicit profile.
DEFAULT_PROFILE = GeneralModelProfile.QWEN38_27B_FP8.value
PROFILE_FILE = Path(__file__).with_name("model-profiles.json")


def load_profile(name: str = DEFAULT_PROFILE) -> dict:
    name = GeneralModelProfile(name).value
    document = json.loads(PROFILE_FILE.read_text())
    if document.get("schema_version") != 1:
        raise ValueError("unsupported serving profile schema")
    profile = document["profiles"].get(name)
    if profile is None:
        raise ValueError("unknown general model profile")
    if not re.fullmatch(r"[0-9a-f]{40}", profile["revision"]):
        raise ValueError("model revision must be an immutable commit")
    if not re.fullmatch(
        r"vllm/vllm-openai@sha256:[0-9a-f]{64}", profile["runtime_image"]
    ):
        raise ValueError("runtime image must be an immutable official image")
    if profile["quantization"] not in {"awq", "bitsandbytes", "fp8"}:
        raise ValueError("unsupported quantization")
    if profile["load_format"] != (
        "bitsandbytes" if profile["quantization"] == "bitsandbytes" else "auto"
    ):
        raise ValueError("quantization and loader disagree")
    if not profile["weights"]:
        raise ValueError("profile must pin model weights")
    for weight in profile["weights"]:
        if Path(weight["name"]).name != weight["name"] or not re.fullmatch(
            r"[0-9a-f]{64}", weight["sha256"]
        ):
            raise ValueError("invalid weight manifest")
    return profile


def verify_weights(directory: Path, profile: dict) -> str:
    """Hash actual model files; metadata alone is not successful verification."""
    for weight in profile["weights"]:
        path = directory / weight["name"]
        if path.stat().st_size != weight["size"]:
            raise ValueError("model weight size differs from pinned manifest")
        with path.open("rb") as source:
            digest = hashlib.sha256()
            for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
                digest.update(chunk)
            actual = digest.hexdigest()
        if actual != weight["sha256"]:
            raise ValueError("model weight digest differs from pinned manifest")
    return hashlib.sha256(
        json.dumps(profile["weights"], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
