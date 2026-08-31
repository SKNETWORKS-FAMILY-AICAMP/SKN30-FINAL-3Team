from __future__ import annotations

import re
from pathlib import Path
from typing import cast

import pytest
from brokerage_ai.core.errors import ProviderTimeoutError
from brokerage_ai.f2 import (
    ConsultationType,
    EmptyTranscriptionError,
    F2PipelineError,
    F2PipelineRequest,
    F2PipelineResult,
    FieldProposal,
    LedgerType,
    ProposalStatus,
)
from fastapi.testclient import TestClient

import main
from api.f2 import get_f2_pipeline
from domain.authentication.dependencies import get_current_user, require_csrf
from domain.authentication.models import CurrentUser, UserRole
from main import create_app


class FakePipeline:
    def __init__(self, error: Exception | None = None) -> None:
        self.request: F2PipelineRequest | None = None
        self.audio_bytes = b""
        self.temp_path: Path | None = None
        self.error = error

    async def run(self, request: F2PipelineRequest) -> F2PipelineResult:
        self.request = request
        self.temp_path = request.audio_path
        self.audio_bytes = request.audio_path.read_bytes()
        if self.error is not None:
            raise self.error
        return F2PipelineResult(
            transcript="한강아파트를 12억에 매도합니다.",
            transcription_model="openai/whisper-large-v3-turbo",
            ledger_type=request.ledger_type,
            consultation_type=ConsultationType.SELL_REQUEST,
            ledger_mismatch=False,
            proposals=(
                FieldProposal(
                    field_name="매매가",
                    current_value=None,
                    proposed_value="12억",
                    evidence="12억에 매도",
                    status=ProposalStatus.CONFIRMED,
                    selected_by_default=True,
                ),
            ),
            uncertainties=(),
            consultation_log_draft="한강아파트 12억 매도 의뢰.",
        )


def client_with_pipeline(config, pipeline: FakePipeline) -> TestClient:
    app = create_app(config=config, readiness_probe=lambda request: True)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=1,
        brokerage_id=1,
        login_id="f2-test",
        display_name="F2 검증",
        role=UserRole.OWNER,
    )
    app.dependency_overrides[require_csrf] = lambda: None
    app.dependency_overrides[get_f2_pipeline] = lambda: pipeline
    return TestClient(app)


def test_analyzes_multipart_audio_and_removes_temporary_file(config) -> None:
    pipeline = FakePipeline()
    with client_with_pipeline(config, pipeline) as client:
        response = client.post(
            "/api/v1/f2/analyses",
            files={"audio": ("memo.wav", b"audio-content", "audio/wav")},
            data={
                "ledger_type": "매물장",
                "current_fields": '{"매매가": null}',
                "privacy_confirmed": "true",
            },
        )

    assert response.status_code == 200, response.text
    assert pipeline.audio_bytes == b"audio-content"
    assert pipeline.request is not None
    assert pipeline.request.ledger_type is LedgerType.PROPERTY
    assert pipeline.request.current_fields == {"매매가": None}
    assert pipeline.temp_path is not None and not pipeline.temp_path.exists()
    assert response.json()["proposals"][0] == {
        "field_name": "매매가",
        "current_value": None,
        "proposed_value": "12억",
        "evidence": "12억에 매도",
        "status": "확인됨",
        "selected_by_default": True,
    }
    assert "transcript" not in response.json()


def test_requires_privacy_confirmation(config) -> None:
    pipeline = FakePipeline()
    with client_with_pipeline(config, pipeline) as client:
        response = client.post(
            "/api/v1/f2/analyses",
            files={"audio": ("memo.wav", b"audio-content", "audio/wav")},
            data={
                "ledger_type": "매물장",
                "current_fields": "{}",
                "privacy_confirmed": "false",
            },
        )

    assert response.status_code == 422
    assert response.json()["code"] == "PRIVACY_CONSENT_REQUIRED"
    assert pipeline.request is None


def test_rejects_unsupported_audio_without_calling_pipeline(config) -> None:
    pipeline = FakePipeline()
    with client_with_pipeline(config, pipeline) as client:
        response = client.post(
            "/api/v1/f2/analyses",
            files={"audio": ("memo.txt", b"not-audio", "text/plain")},
            data={
                "ledger_type": "구입장",
                "current_fields": "{}",
                "privacy_confirmed": "true",
            },
        )

    assert response.status_code == 422
    assert pipeline.request is None


@pytest.mark.parametrize(
    ("error", "status_code", "error_code"),
    [
        (ProviderTimeoutError(), 503, "F2_UNAVAILABLE"),
        (F2PipelineError("raw transcript must stay private"), 502, "F2_PROCESSING_FAILED"),
    ],
)
def test_f2_502_and_503_emit_exactly_one_safe_terminal_event(
    config,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    status_code: int,
    error_code: str,
) -> None:
    events: list[tuple[str, dict[str, object]]] = []

    class RecordingLogger:
        def error(self, event: str, **values: object) -> None:
            events.append((event, values))

    monkeypatch.setattr(main, "logger", RecordingLogger())
    pipeline = FakePipeline(error)
    with client_with_pipeline(config, pipeline) as client:
        response = client.post(
            "/api/v1/f2/analyses",
            files={"audio": ("memo.wav", b"audio-content", "audio/wav")},
            data={
                "ledger_type": "매물장",
                "current_fields": "{}",
                "privacy_confirmed": "true",
            },
        )

    assert response.status_code == status_code
    assert response.json()["code"] == error_code
    assert len(events) == 1
    event, values = events[0]
    assert event == "ai_terminal_failure"
    assert values["component"] == "ai"
    assert values["source"] == "f2"
    assert values["request_id"] == response.json()["request_id"]
    assert values["status_code"] == status_code
    assert values["error_code"] == error_code
    assert values["failure_stage"] == "F2_ANALYSIS"
    assert values["error_type"] == type(error).__name__
    assert re.fullmatch(r"[A-Za-z0-9_.<>]+:[^:]+:\d+", cast(str, values["error_location"]))
    assert "raw transcript" not in repr(events)


def test_empty_transcription_remains_422_without_a_terminal_event(
    config, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[tuple[str, dict[str, object]]] = []

    class RecordingLogger:
        def error(self, event: str, **values: object) -> None:
            events.append((event, values))

    monkeypatch.setattr(main, "logger", RecordingLogger())
    pipeline = FakePipeline(EmptyTranscriptionError("raw transcript must stay private"))
    with client_with_pipeline(config, pipeline) as client:
        response = client.post(
            "/api/v1/f2/analyses",
            files={"audio": ("memo.wav", b"audio-content", "audio/wav")},
            data={
                "ledger_type": "매물장",
                "current_fields": "{}",
                "privacy_confirmed": "true",
            },
        )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert events == []
