"""Reject malformed uploads and unauthorized callers before any provider work."""

import json
import tempfile
from pathlib import Path

import pytest
from f2_fixtures import FakePipeline, app_with_pipeline
from fastapi.testclient import TestClient

import api.f2
from domain.authentication.dependencies import (
    get_authentication_context,
    get_current_user,
    require_csrf,
)
from domain.authentication.models import AuthenticationContext, CurrentUser, UserRole
from domain.authentication.service import hash_token
from domain.session import get_db_session


@pytest.mark.parametrize(
    "current_fields",
    ["{", "null", "[]", '"value"', '{"price": 12}', '{"price": true}', '{"price": {}}'],
    ids=[
        "invalid-json",
        "null",
        "array",
        "string",
        "number-value",
        "boolean-value",
        "object-value",
    ],
)
def test_current_fields_requires_a_json_object_with_string_or_null_values(
    config, current_fields: str
) -> None:
    pipeline = FakePipeline()
    app = app_with_pipeline(config, pipeline)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/f2/analyses",
            files={"audio": ("memo.wav", b"audio", "audio/wav")},
            data={"current_fields": current_fields, "privacy_confirmed": "true"},
        )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert pipeline.request is None
    assert app.state.f2_analysis_busy is False


@pytest.mark.parametrize("excess_bytes", [0, 1], ids=["at-limit", "over-limit"])
def test_current_fields_limit_counts_utf8_bytes(config, excess_bytes: int) -> None:
    # A multibyte payload distinguishes byte limits from Python character limits.
    current_fields = json.dumps({"note": "한" * 21000}, ensure_ascii=False)
    current_fields += " " * (64 * 1024 + excess_bytes - len(current_fields.encode("utf-8")))
    pipeline = FakePipeline()
    app = app_with_pipeline(config, pipeline)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/f2/analyses",
            files={"audio": ("memo.wav", b"audio", "audio/wav")},
            data={"current_fields": current_fields, "privacy_confirmed": "true"},
        )

    assert response.status_code == (200 if excess_bytes == 0 else 422)
    assert (pipeline.request is not None) == (excess_bytes == 0)
    if pipeline.request is not None:
        assert pipeline.request.current_fields == {"note": "한" * 21000}
    assert app.state.f2_analysis_busy is False


@pytest.mark.parametrize("size", [0, 4, 5], ids=["empty", "at-limit", "over-limit"])
def test_audio_limit_cleans_temporary_files_and_releases_admission_slot(
    make_config, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, size: int
) -> None:
    config = make_config({"F2_MAX_AUDIO_BYTES": "4"})
    pipeline = FakePipeline()
    app = app_with_pipeline(config, pipeline)
    named_temporary_file = tempfile.NamedTemporaryFile

    def isolated_temporary_file(*args, **kwargs):
        return named_temporary_file(*args, **kwargs, dir=tmp_path)

    monkeypatch.setattr(api.f2.tempfile, "NamedTemporaryFile", isolated_temporary_file)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/f2/analyses",
            files={"audio": ("memo.wav", b"a" * size, "audio/wav")},
            data={"privacy_confirmed": "true"},
        )
        assert response.status_code == (200 if size == 4 else 422)
        assert (pipeline.request is not None) == (size == 4)
        assert list(tmp_path.iterdir()) == []
        assert app.state.f2_analysis_busy is False

        # A rejected request must not keep later valid requests busy.
        retry = client.post(
            "/api/v1/f2/analyses",
            files={"audio": ("memo.wav", b"okay", "audio/wav")},
            data={"privacy_confirmed": "true"},
        )
        assert retry.status_code == 200
        assert list(tmp_path.iterdir()) == []


def test_missing_session_is_rejected_by_the_real_authentication_dependency(config) -> None:
    pipeline = FakePipeline()
    app = app_with_pipeline(config, pipeline)
    del app.dependency_overrides[get_current_user]
    del app.dependency_overrides[require_csrf]
    # No cookie means no query; only prevent creating an unused real DB session.
    app.dependency_overrides[get_db_session] = lambda: None
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/f2/analyses",
            files={"audio": ("memo.wav", b"audio", "audio/wav")},
            data={"privacy_confirmed": "true"},
        )

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"
    assert pipeline.request is None
    assert app.state.f2_analysis_busy is False


@pytest.mark.parametrize("csrf_token", [None, "wrong-token", "valid-csrf"])
def test_f2_route_enforces_csrf_for_an_authenticated_user(config, csrf_token: str | None) -> None:
    pipeline = FakePipeline()
    app = app_with_pipeline(config, pipeline)
    del app.dependency_overrides[get_current_user]
    del app.dependency_overrides[require_csrf]
    app.dependency_overrides[get_authentication_context] = lambda: AuthenticationContext(
        user=CurrentUser(7, 3, "developer", "Developer", UserRole.OWNER),
        session_id=11,
        csrf_token_hash=hash_token("valid-csrf"),
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/f2/analyses",
            files={"audio": ("memo.wav", b"audio", "audio/wav")},
            data={"privacy_confirmed": "true"},
            headers={"X-CSRF-Token": csrf_token} if csrf_token else {},
        )

    assert response.status_code == (200 if csrf_token == "valid-csrf" else 403)
    if csrf_token != "valid-csrf":
        assert response.json()["code"] == "INVALID_CSRF_TOKEN"
    assert (pipeline.request is not None) == (csrf_token == "valid-csrf")
    assert app.state.f2_analysis_busy is False
