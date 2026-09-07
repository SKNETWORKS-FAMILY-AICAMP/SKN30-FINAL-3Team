from __future__ import annotations

import io
import wave
from importlib import import_module
from pathlib import Path
from typing import Any

from openai import OpenAI, OpenAIError

from brokerage_ai.core.errors import translate_openai_error
from brokerage_ai.f2.errors import AudioInputError, EmptyTranscriptionError, F2DependencyError
from brokerage_ai.f2.types import Transcription

# libsndfile은 MP4 컨테이너와 AAC를 열지 못해 vLLM 전사가 "Format not recognised"로 실패한다.
# 해당 확장자만 호출 전에 WAV로 바꾸고 나머지는 원본 그대로 보낸다.
TRANSCODED_SUFFIXES = frozenset({".aac", ".m4a", ".mp4"})
TRANSCODE_SAMPLE_RATE = 16000


def _frame_bytes(frame: Any) -> bytes:
    """packed s16 mono frame에서 정렬 padding을 제외한 실제 샘플만 꺼낸다."""

    return bytes(frame.planes[0])[: frame.samples * 2]


def decode_to_wav_bytes(path: Path) -> bytes:
    """AAC 계열 음성을 16kHz mono WAV 바이트로 디코딩한다.

    Whisper가 어차피 16kHz mono로 다시 샘플링하므로 여기서 맞춰 보내면 업로드 크기도
    줄어든다. PyAV는 ffmpeg 라이브러리를 wheel에 포함하므로 시스템 ffmpeg가 필요없다.
    """

    try:
        av = import_module("av")
    except ModuleNotFoundError as error:
        raise F2DependencyError(
            "av가 설치되어 있지 않아 AAC 계열 음성을 변환할 수 없습니다."
        ) from error

    resampler = av.AudioResampler(format="s16", layout="mono", rate=TRANSCODE_SAMPLE_RATE)
    chunks: list[bytes] = []
    try:
        with av.open(str(path)) as container:
            streams = container.streams.audio
            if not streams:
                raise AudioInputError(f"음성 트랙이 없습니다: {path.name}")
            for frame in container.decode(streams[0]):
                chunks.extend(_frame_bytes(resampled) for resampled in resampler.resample(frame))
            chunks.extend(_frame_bytes(resampled) for resampled in resampler.resample(None))
    except (OSError, av.FFmpegError) as error:
        raise AudioInputError(f"음성 파일을 디코딩할 수 없습니다: {path.name}") from error

    payload = b"".join(chunks)
    if not payload:
        raise AudioInputError(f"디코딩 결과가 비어 있습니다: {path.name}")

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(TRANSCODE_SAMPLE_RATE)
        wav_file.writeframes(payload)
    return buffer.getvalue()


class VllmWhisperTranscriber:
    """vLLM의 OpenAI 호환 전사 API를 통해 RunPod Whisper를 호출한다."""

    def __init__(
        self,
        client: OpenAI,
        *,
        model_id: str = "openai/whisper-large-v3-turbo",
        language: str = "ko",
    ) -> None:
        self._client = client
        self._model_id = model_id
        self._language = language

    def transcribe(self, audio_path: Path) -> Transcription:
        path = audio_path.expanduser().resolve()
        if not path.is_file():
            raise AudioInputError(f"음성 파일을 찾을 수 없습니다: {path}")

        if path.suffix.lower() in TRANSCODED_SUFFIXES:
            upload: Any = (f"{path.stem}.wav", decode_to_wav_bytes(path), "audio/wav")
            response = self._create(upload)
        else:
            with path.open("rb") as audio_file:
                response = self._create(audio_file)

        text = response.text.strip()
        if not text:
            raise EmptyTranscriptionError("STT 결과가 비어 있어 sLLM 분석을 중단했습니다.")
        return Transcription(text=text, model=self._model_id)

    def _create(self, upload: Any) -> Any:
        try:
            return self._client.audio.transcriptions.create(
                model=self._model_id,
                file=upload,
                language=self._language,
                response_format="json",
            )
        except OpenAIError as error:
            raise translate_openai_error(error) from None


class FasterWhisperTranscriber:
    """faster-whisper를 사용해 음성 파일을 로컬에서 전사한다.

    모델은 객체 생성 시 한 번만 메모리에 올린다. ``faster_whisper`` import를 이 파일의
    최상단이 아니라 생성자 안에서 수행하므로, F2를 사용하지 않는 AI 테스트에는 무거운
    STT 의존성이 필요하지 않다.
    """

    def __init__(
        self,
        model_id: str = "large-v3",
        *,
        device: str = "auto",
        compute_type: str = "default",
        language: str = "ko",
        beam_size: int = 5,
    ) -> None:
        try:
            whisper_module = import_module("faster_whisper")
        except ModuleNotFoundError as error:
            raise F2DependencyError(
                "faster-whisper가 설치되어 있지 않아 STT 모델을 불러올 수 없습니다."
            ) from error

        self._model_id = model_id
        self._model: Any = whisper_module.WhisperModel(
            model_id,
            device=device,
            compute_type=compute_type,
        )
        self._language = language
        self._beam_size = beam_size

    def transcribe(self, audio_path: Path) -> Transcription:
        path = audio_path.expanduser().resolve()
        if not path.is_file():
            raise AudioInputError(f"음성 파일을 찾을 수 없습니다: {path}")

        segments, _ = self._model.transcribe(
            str(path),
            language=self._language,
            task="transcribe",
            beam_size=self._beam_size,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        text = " ".join(segment.text.strip() for segment in segments if segment.text.strip())
        if not text.strip():
            raise EmptyTranscriptionError("STT 결과가 비어 있어 sLLM 분석을 중단했습니다.")
        return Transcription(text=text, model=self._model_id)
