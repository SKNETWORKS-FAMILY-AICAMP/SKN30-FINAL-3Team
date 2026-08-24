from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import Any

from openai import OpenAI, OpenAIError

from brokerage_ai.core.errors import translate_openai_error
from brokerage_ai.f2.errors import AudioInputError, EmptyTranscriptionError, F2DependencyError
from brokerage_ai.f2.types import Transcription


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

        try:
            with path.open("rb") as audio_file:
                response = self._client.audio.transcriptions.create(
                    model=self._model_id,
                    file=audio_file,
                    language=self._language,
                    response_format="json",
                )
        except OpenAIError as error:
            raise translate_openai_error(error) from None

        text = response.text.strip()
        if not text:
            raise EmptyTranscriptionError("STT 결과가 비어 있어 sLLM 분석을 중단했습니다.")
        return Transcription(text=text, model=self._model_id)


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
