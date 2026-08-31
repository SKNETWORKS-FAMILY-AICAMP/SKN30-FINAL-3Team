from __future__ import annotations

import re
from typing import cast
from uuid import UUID

import pytest
from brokerage_ai.f2 import F2Pipeline, F2Runtime
from fastapi import FastAPI
from fastapi.testclient import TestClient

import main
from core.config import Config
from core.request_context import safe_request_id
from main import create_app

VALID_REQUEST_ID = "123e4567-e89b-12d3-a456-426614174000"


def test_valid_request_id_is_normalized_to_canonical_uuid() -> None:
    assert safe_request_id(VALID_REQUEST_ID.upper()) == VALID_REQUEST_ID


class FakeF2Runtime:
    def __init__(self) -> None:
        self.pipeline = cast(F2Pipeline, object())

    async def close(self) -> None:
        pass


def app_with_contract_routes(config: Config) -> FastAPI:
    runtime = FakeF2Runtime()
    app = create_app(
        config=config,
        readiness_probe=lambda _request: True,
        f2_runtime_factory=lambda: cast(F2Runtime, runtime),
    )

    @app.get("/api/v1/_error-contract/items/{item_id}")
    def read_item(item_id: int) -> dict[str, int]:
        return {"item_id": item_id}

    @app.get("/api/v1/_error-contract/explode")
    def explode() -> None:
        raise RuntimeError("customer phone 010-0000-0000")

    return app


@pytest.mark.parametrize(
    ("method", "path", "status_code", "code", "message"),
    [
        ("GET", "/api/v1/_error-contract/missing", 404, "NOT_FOUND", "resource is not found"),
        (
            "POST",
            "/api/v1/_error-contract/items/1",
            405,
            "METHOD_NOT_ALLOWED",
            "method is not allowed",
        ),
        (
            "GET",
            "/api/v1/_error-contract/items/not-an-integer",
            422,
            "VALIDATION_FAILED",
            "request validation failed",
        ),
    ],
)
def test_framework_api_errors_use_the_public_envelope(
    config: Config,
    method: str,
    path: str,
    status_code: int,
    code: str,
    message: str,
) -> None:
    app = app_with_contract_routes(config)

    with TestClient(app) as client:
        response = client.request(method, path, headers={"X-Request-ID": VALID_REQUEST_ID})

    assert response.status_code == status_code
    assert response.json() == {
        "code": code,
        "message": message,
        "request_id": VALID_REQUEST_ID,
    }
    assert response.headers["X-Request-ID"] == VALID_REQUEST_ID
    if status_code == 405:
        assert response.headers["Allow"] == "GET"


def test_non_api_and_health_responses_keep_their_existing_shape(config: Config) -> None:
    app = app_with_contract_routes(config)

    with TestClient(app) as client:
        health = client.get("/health/live")
        missing = client.get("/outside-api")

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Not Found"}


def test_unexpected_500_logs_only_alarmable_safe_metadata(
    config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[tuple[str, dict[str, object]]] = []

    class RecordingLogger:
        def error(self, event: str, **values: object) -> None:
            events.append((event, values))

    monkeypatch.setattr(main, "logger", RecordingLogger())
    app = app_with_contract_routes(config)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            "/api/v1/_error-contract/explode",
            headers={"X-Request-ID": VALID_REQUEST_ID},
        )

    assert response.status_code == 500
    assert response.json() == {
        "code": "INTERNAL_SERVER_ERROR",
        "message": "an unexpected error occurred",
        "request_id": VALID_REQUEST_ID,
    }
    assert len(events) == 1
    event, values = events[0]
    assert event == "unhandled_request_error"
    assert values == {
        "component": "backend",
        "request_id": VALID_REQUEST_ID,
        "status_code": 500,
        "error_code": "INTERNAL_SERVER_ERROR",
        "error_type": "RuntimeError",
        "error_location": values["error_location"],
    }
    assert re.fullmatch(r"[A-Za-z0-9_.<>]+:[^:]+:\d+", cast(str, values["error_location"]))
    assert "010-0000-0000" not in repr(events)


def test_untrusted_request_id_is_replaced_before_response_and_logging(
    config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    unsafe_request_id = "customer-phone-010-1234-5678"
    events: list[tuple[str, dict[str, object]]] = []

    class RecordingLogger:
        def error(self, event: str, **values: object) -> None:
            events.append((event, values))

    monkeypatch.setattr(main, "logger", RecordingLogger())
    app = app_with_contract_routes(config)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            "/api/v1/_error-contract/explode",
            headers={"X-Request-ID": unsafe_request_id},
        )

    generated = response.json()["request_id"]
    assert str(UUID(generated)) == generated
    assert response.headers["X-Request-ID"] == generated
    assert events[0][1]["request_id"] == generated
    assert unsafe_request_id not in response.text
    assert unsafe_request_id not in repr(events)
