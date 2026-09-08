from __future__ import annotations

import io
import wave
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest
from openai import OpenAI

from brokerage_ai.core.config import AiProfile, bind_ai_config
from brokerage_ai.f2.errors import AudioInputError, EmptyTranscriptionError
from brokerage_ai.f2.runtime import SyncClientFactory, create_f2_runtime
from brokerage_ai.f2.stt import VllmWhisperTranscriber, decode_to_wav_bytes


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


def write_aac_memo(path: Path, *, seconds: float = 0.2, rate: int = 44100) -> None:
    """libsndfile이 못 여는 AAC 음성을 실제로 만들어 변환 경로를 검증한다."""

    import av

    samples = int(rate * seconds)
    with av.open(str(path), "w") as container:
        stream = container.add_stream("aac", rate=rate)
        frame = av.AudioFrame(format="s16", layout="mono", samples=samples)
        frame.planes[0].update(b"\x00\x00" * samples)
        frame.rate = rate
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)


def write_wav_memo(
    path: Path,
    *,
    seconds: float = 0.2,
    rate: int = 48000,
    channels: int = 2,
) -> None:
    """전사 서버가 거부할 수 있는 48kHz 스테레오 WAV를 만든다."""

    frames = int(rate * seconds)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(rate)
        wav_file.writeframes(b"\x00\x00" * frames * channels)


def test_sends_audio_to_openai_compatible_whisper_endpoint(tmp_path: Path) -> None:
    audio_path = tmp_path / "memo.wav"
    write_wav_memo(audio_path)
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
    filename, payload, content_type = call["file"]
    assert (filename, content_type) == ("memo.wav", "audio/wav")
    assert payload[:4] == b"RIFF"


def test_normalizes_wav_input_to_16k_mono_before_calling_provider(tmp_path: Path) -> None:
    """WAV 확장자도 전사 서버가 못 읽는 형식일 수 있어 항상 정규화한다."""

    audio_path = tmp_path / "memo.wav"
    write_wav_memo(audio_path, rate=48000, channels=2)
    client = FakeClient("한강아파트 매물 문의입니다.")
    transcriber = VllmWhisperTranscriber(cast(OpenAI, client), model_id="stt")

    transcriber.transcribe(audio_path)

    _, payload, _ = client.transcriptions.calls[0]["file"]
    with wave.open(io.BytesIO(payload)) as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getframerate() == 16000
        assert wav_file.getsampwidth() == 2


def test_converts_aac_memo_to_wav_before_calling_provider(tmp_path: Path) -> None:
    audio_path = tmp_path / "memo.m4a"
    write_aac_memo(audio_path)
    client = FakeClient("한강아파트 매물 문의입니다.")
    transcriber = VllmWhisperTranscriber(cast(OpenAI, client), model_id="stt")

    transcriber.transcribe(audio_path)

    filename, payload, content_type = client.transcriptions.calls[0]["file"]
    assert filename == "memo.wav"
    assert content_type == "audio/wav"
    assert payload[:4] == b"RIFF"
    assert payload[8:12] == b"WAVE"


def test_decode_to_wav_bytes_produces_16k_mono_pcm(tmp_path: Path) -> None:
    audio_path = tmp_path / "memo.m4a"
    write_aac_memo(audio_path)

    payload = decode_to_wav_bytes(audio_path)

    with wave.open(io.BytesIO(payload)) as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == 16000
        assert wav_file.getnframes() > 0


@pytest.mark.parametrize("name", ["memo.m4a", "memo.wav"])
def test_rejects_unreadable_audio_container(tmp_path: Path, name: str) -> None:
    audio_path = tmp_path / name
    audio_path.write_bytes(b"not-real-audio")

    with pytest.raises(AudioInputError):
        decode_to_wav_bytes(audio_path)


def test_rejects_missing_audio_before_calling_provider(tmp_path: Path) -> None:
    client = FakeClient("unused")
    transcriber = VllmWhisperTranscriber(cast(OpenAI, client))

    with pytest.raises(AudioInputError):
        transcriber.transcribe(tmp_path / "missing.wav")

    assert client.transcriptions.calls == []


def test_rejects_empty_provider_transcription(tmp_path: Path) -> None:
    audio_path = tmp_path / "memo.wav"
    write_wav_memo(audio_path)
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
