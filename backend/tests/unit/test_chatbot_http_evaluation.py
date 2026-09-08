"""Evaluation provenance must come from the endpoint's control-plane Pod."""

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

_spec = importlib.util.spec_from_file_location(
    "chatbot_http_evaluation", Path(__file__).parents[2] / "eval/chatbot_http.py"
)
assert _spec is not None and _spec.loader is not None
module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(module)
IMAGE = "ghcr.io/example/general@sha256:" + "a" * 64
URL = "https://syntheticpod-8000.proxy.runpod.net/v1"
POD = {"id": "syntheticpod", "image": IMAGE, "desiredStatus": "RUNNING", "ports": ["8000/http"]}


def verify(monkeypatch, payload, *, status=200):
    monkeypatch.setenv("RUNPOD_API_KEY", "synthetic-control-token")

    def respond(request):
        assert str(request.url) == "https://rest.runpod.io/v1/pods/syntheticpod"
        assert request.headers["Authorization"] == "Bearer synthetic-control-token"
        return httpx.Response(status, json=payload)

    return asyncio.run(
        module.verify_deployment_image(URL, IMAGE, transport=httpx.MockTransport(respond))
    )


def test_deployment_image_is_verified_by_control_plane(monkeypatch):
    result = verify(monkeypatch, POD)
    assert result == {"source": "runpod-control-plane", "deployment_image": IMAGE}
    assert "syntheticpod" not in str(result)


@pytest.mark.parametrize(
    "change",
    [
        {"image": None},
        {"image": IMAGE.replace("a" * 64, "b" * 64)},
        {"image": "ghcr.io/example/general:latest"},
        {"id": "anotherpod"},
        {"desiredStatus": "EXITED"},
        {"ports": ["8001/http"]},
    ],
)
def test_missing_or_mismatched_deployment_is_rejected(monkeypatch, change):
    with pytest.raises(ValueError, match="verification failed"):
        verify(monkeypatch, POD | change)


@pytest.mark.parametrize("status", [302, 401, 403, 404, 503])
def test_control_plane_failure_cannot_produce_verified_result(monkeypatch, status):
    with pytest.raises(ValueError, match="verification failed") as caught:
        verify(monkeypatch, {"secret": "synthetic-private-detail"}, status=status)
    assert "synthetic-private-detail" not in str(caught.value)


@pytest.mark.parametrize(
    "url",
    [
        "http://syntheticpod-8000.proxy.runpod.net/v1",
        "https://syntheticpod-8001.proxy.runpod.net/v1",
        "https://custom.example/v1",
        URL + "?redirect=anotherpod",
        URL.replace("/v1", "/other"),
    ],
)
def test_unverifiable_endpoint_is_rejected_without_network(url):
    with pytest.raises(ValueError, match="direct HTTPS"):
        asyncio.run(module.verify_deployment_image(url, IMAGE))


def test_missing_control_plane_key_fails_closed(monkeypatch):
    monkeypatch.delenv("RUNPOD_API_KEY", raising=False)
    with pytest.raises(ValueError, match="RUNPOD_API_KEY"):
        asyncio.run(module.verify_deployment_image(URL, IMAGE))


def test_model_metadata_also_checks_deployment_on_each_verification(monkeypatch):
    endpoint = SimpleNamespace(
        alias="general", provider="vllm", base_url=URL, api_key=SecretStr("synthetic-service-token")
    )
    monkeypatch.setattr(
        module, "load_ai_config", lambda _: SimpleNamespace(llm_endpoints=[endpoint])
    )
    expected = {"model": "model", "revision": "revision", "artifact_sha256": "digest"}
    original = httpx.AsyncClient
    calls = []

    def respond(request):
        calls.append(request.url.path)
        if request.url.path == "/ops/status":
            return httpx.Response(200, json={"model": expected})
        payload = POD if calls.count("/v1/pods/syntheticpod") == 1 else POD | {"image": "wrong"}
        return httpx.Response(200, json=payload)

    monkeypatch.setenv("RUNPOD_API_KEY", "synthetic-control-token")

    def client(**kwargs: Any):
        kwargs["transport"] = httpx.MockTransport(respond)
        return original(**kwargs)

    monkeypatch.setattr(module.httpx, "AsyncClient", client)
    route = ("vllm", "model", "revision", "general")
    provenance = {"artifact_sha256": "digest", "deployment_image": IMAGE}
    before = asyncio.run(module.verify_model_metadata(route, provenance))
    assert before["deployment_image"] == IMAGE
    with pytest.raises(ValueError, match="verification failed"):
        asyncio.run(module.verify_model_metadata(route, provenance))
    assert calls == ["/ops/status", "/v1/pods/syntheticpod"] * 2


def test_openai_does_not_require_deployment_credentials():
    assert asyncio.run(module.verify_model_metadata(("openai",), {})) is None
