"""Deployment JSON selection cannot silently replace existing pinned CHATBOT routes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chatbot_model import PROFILES, resolve_profile


def write_profile(tmp_path, key="qwen3-14b-awq", **overrides):
    path = tmp_path / "profiles.json"
    value = {
        "model": "Qwen/Qwen3-14B-AWQ",
        "revision": "a" * 40,
        "runtime_image": "vllm/vllm-openai@sha256:" + "b" * 64,
        **overrides,
    }
    path.write_text(json.dumps({"schema_version": 1, "profiles": {key: value}}))
    return path


def test_legacy_routes_remain_unchanged():
    for name, route in PROFILES.items():
        assert resolve_profile(name) == route


def test_explicit_deployment_profile_selects_only_general_vllm_route(tmp_path):
    assert resolve_profile("qwen3-14b-awq", write_profile(tmp_path)) == (
        "vllm",
        "Qwen/Qwen3-14B-AWQ",
        "a" * 40,
        "general-dev-gpu",
    )


@pytest.mark.parametrize("changes", [{"revision": "main"}, {"runtime_image": "vllm:latest"}])
def test_unpinned_profile_is_rejected(tmp_path, changes):
    with pytest.raises(ValueError, match="pinned"):
        resolve_profile("qwen3-14b-awq", write_profile(tmp_path, **changes))


def test_external_contract_cannot_override_builtin_profile(tmp_path):
    with pytest.raises(ValueError, match="cannot be overridden"):
        resolve_profile("local-openai", write_profile(tmp_path, key="local-openai"))


def test_repository_profile_contract_can_be_consumed_without_infra_imports():
    source = Path(__file__).resolve().parents[3] / "infra/serving/model-profiles.json"
    document = json.loads(source.read_bytes())
    for key in ("qwen3-14b-awq", "qwen3-32b-awq", "qwen38-27b-bnb"):
        route = resolve_profile(key, source)
        assert route[1:3] == (
            document["profiles"][key]["model"],
            document["profiles"][key]["revision"],
        )
