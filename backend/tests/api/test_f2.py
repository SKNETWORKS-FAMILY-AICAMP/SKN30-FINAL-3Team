from __future__ import annotations

import asyncio
import re
from typing import cast

import httpx
import pytest
from brokerage_ai.core.errors import ProviderTimeoutError
from brokerage_ai.f2 import (
    ConsultationType,
    EmptyTranscriptionError,
    F2PipelineError,
    F2PipelineRequest,
    F2PipelineResult,
    LedgerType,
)
from f2_fixtures import FakePipeline, app_with_pipeline, client_with_pipeline

import main
from main import create_app


def test_analyzes_multipart_audio_and_removes_temporary_file(config) -> None:
    pipeline = FakePipeline()
    with client_with_pipeline(config, pipeline) as client:
        response = client.post(
            "/api/v1/f2/analyses",
            files={"audio": ("memo.wav", b"audio-content", "audio/wav")},
            data={
                "current_ledger_type": "매물장",
                "current_fields": '{"매매가": null}',
                "privacy_confirmed": "true",
            },
        )

    assert response.status_code == 200, response.text
    assert pipeline.audio_bytes == b"audio-content"
    assert pipeline.request is not None
    assert pipeline.request.current_ledger_type is LedgerType.PROPERTY
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
    assert response.json()["ledger_type"] == "매물장"


def test_new_intake_omits_current_ledger_and_returns_recommended_buyer_ledger(config) -> None:
    pipeline = FakePipeline(consultation_type=ConsultationType.BUY_REQUEST)
    with client_with_pipeline(config, pipeline) as client:
        response = client.post(
            "/api/v1/f2/analyses",
            files={"audio": ("memo.wav", b"audio-content", "audio/wav")},
            data={"privacy_confirmed": "true"},
        )

    assert response.status_code == 200, response.text
    assert pipeline.request is not None
    assert pipeline.request.current_ledger_type is None
    assert pipeline.request.current_fields == {}
    assert response.json()["consultation_type"] == "매수문의"
    assert response.json()["ledger_type"] == "구입장"
    assert response.json()["ledger_mismatch"] is False


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


class BlockingPipeline(FakePipeline):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.finish = asyncio.Event()
        self.calls = 0

    async def run(self, request: F2PipelineRequest) -> F2PipelineResult:
        self.calls += 1
        self.temp_path = request.audio_path
        self.started.set()
        await self.finish.wait()
        return await super().run(request)


def test_ten_overlapping_analyses_admit_one_and_reject_nine_without_blocking_health(config):
    async def scenario():
        pipeline = BlockingPipeline()
        app = app_with_pipeline(config, pipeline)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:

            async def submit():
                return await client.post(
                    "/api/v1/f2/analyses",
                    files={"audio": ("memo.wav", b"audio", "audio/wav")},
                    data={
                        "ledger_type": "매물장",
                        "current_fields": "{}",
                        "privacy_confirmed": "true",
                    },
                )

            first = asyncio.create_task(submit())
            try:
                await asyncio.wait_for(pipeline.started.wait(), timeout=5)
                responses = await asyncio.wait_for(
                    asyncio.gather(*(submit() for _ in range(9))), timeout=5
                )
                assert all(response.status_code == 429 for response in responses)
                assert all(response.json()["code"] == "F2_BUSY" for response in responses)
                assert all(response.headers["Retry-After"] == "5" for response in responses)
                assert pipeline.calls == 1
                assert (await client.get("/health/live")).status_code == 200
            finally:
                pipeline.finish.set()
                response = await first
            assert response.status_code == 200
            assert (await submit()).status_code == 200
            assert pipeline.calls == 2

    asyncio.run(scenario())


def test_canceled_caller_keeps_file_and_slot_until_analysis_finishes(config):
    async def scenario():
        pipeline = BlockingPipeline()
        app = app_with_pipeline(config, pipeline)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            caller = asyncio.create_task(
                client.post(
                    "/api/v1/f2/analyses",
                    files={"audio": ("memo.wav", b"audio", "audio/wav")},
                    data={
                        "ledger_type": "매물장",
                        "current_fields": "{}",
                        "privacy_confirmed": "true",
                    },
                )
            )
            await asyncio.wait_for(pipeline.started.wait(), timeout=5)
            analysis = app.state.f2_analysis_task
            try:
                caller.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await caller
                assert app.state.f2_analysis_busy
                assert not analysis.done()
                assert pipeline.temp_path is not None and pipeline.temp_path.exists()
            finally:
                pipeline.finish.set()
                await analysis
            assert not app.state.f2_analysis_busy
            assert app.state.f2_analysis_task is None
            assert not pipeline.temp_path.exists()

    asyncio.run(scenario())


def test_busy_request_is_rejected_before_reading_upload(config):
    class UnreadBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            raise AssertionError("busy requests must not consume the upload body")
            yield b""  # pragma: no cover

    async def scenario():
        app = create_app(config=config)
        app.state.f2_analysis_busy = True
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post("/api/v1/f2/analyses", content=UnreadBody())
        assert response.status_code == 429
        assert response.json()["code"] == "F2_BUSY"

    asyncio.run(scenario())


@pytest.mark.parametrize("error", [ProviderTimeoutError(), F2PipelineError("private")])
def test_failed_analysis_releases_capacity_for_retry(config, error):
    pipeline = FakePipeline(error)
    with client_with_pipeline(config, pipeline) as client:

        def submit(content=b"audio"):
            return client.post(
                "/api/v1/f2/analyses",
                files={"audio": ("memo.wav", content, "audio/wav")},
                data={"ledger_type": "매물장", "current_fields": "{}", "privacy_confirmed": "true"},
            )

        assert submit().status_code in (502, 503)
        assert pipeline.temp_path is not None and not pipeline.temp_path.exists()
        pipeline.error = None
        assert submit(b"").status_code == 422
        assert submit().status_code == 200
