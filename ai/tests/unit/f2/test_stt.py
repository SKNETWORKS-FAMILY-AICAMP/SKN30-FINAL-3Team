from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest
from openai import OpenAI

from brokerage_ai.core.config import AiProfile, bind_ai_config
from brokerage_ai.f2.errors import AudioInputError, EmptyTranscriptionError
from brokerage_ai.f2.runtime import SyncClientFactory, create_f2_runtime
from brokerage_ai.f2.stt import VllmWhisperTranscriber


class FakeTranscriptions:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[dict[str, Any]] = []

    def create(self, **parameters: Any) -> Any:
        self.calls.append(parameters)
        return SimpleNamespace(text=self.text)


class FakeClient:
    def __init__(self, text: str) -> None:
        self.transcriptions = FakeTranscriptions(text)
        self.audio = SimpleNamespace(transcriptions=self.transcriptions)


def test_sends_audio_to_openai_compatible_whisper_endpoint(tmp_path: Path) -> None:
    audio_path = tmp_path / "memo.wav"
    audio_path.write_bytes(b"not-real-audio")
    client = FakeClient(" 한강아파트를 12억에 매도합니다. ")
    transcriber = VllmWhisperTranscriber(
        cast(OpenAI, client),
        model_id="openai/whisper-large-v3-turbo",
        language="ko",
    )

    result = transcriber.transcribe(audio_path)

    assert result.text == "한강아파트를 12억에 매도합니다."
    assert result.model == "openai/whisper-large-v3-turbo"
    call = client.transcriptions.calls[0]
    assert call["language"] == "ko"
    assert call["response_format"] == "json"
    assert call["file"].closed is True


def test_rejects_missing_audio_before_calling_provider(tmp_path: Path) -> None:
    client = FakeClient("unused")
    transcriber = VllmWhisperTranscriber(cast(OpenAI, client))

    with pytest.raises(AudioInputError):
        transcriber.transcribe(tmp_path / "missing.wav")

    assert client.transcriptions.calls == []


def test_rejects_empty_provider_transcription(tmp_path: Path) -> None:
    audio_path = tmp_path / "memo.mp3"
    audio_path.write_bytes(b"not-real-audio")
    transcriber = VllmWhisperTranscriber(cast(OpenAI, FakeClient("   ")))

    with pytest.raises(EmptyTranscriptionError):
        transcriber.transcribe(audio_path)


@pytest.mark.asyncio
async def test_f2_runtime_composes_runpod_stt_and_qwen_and_closes_clients() -> None:
    client = FakeClient("unused")
    client.close = Mock()  # type: ignore[attr-defined]

    def client_factory(**_options: Any) -> OpenAI:
        return cast(OpenAI, client)

    config = bind_ai_config(
        {
            "AI_F2_PROVIDER_STATUS": "active",
            "AI_VLLM_SLLM_BASE_URL": "http://localhost:8001/v1",
            "AI_VLLM_STT_BASE_URL": "http://localhost:8002/v1",
        },
        AiProfile.TEST,
    )

    runtime = create_f2_runtime(
        config,
        sync_client_factory=cast(SyncClientFactory, client_factory),
    )

    assert runtime.pipeline is not None
    await runtime.close()
    await runtime.close()
    client.close.assert_called_once()  # type: ignore[attr-defined]
