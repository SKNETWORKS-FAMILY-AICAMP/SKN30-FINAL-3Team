from __future__ import annotations

from pathlib import Path
from typing import Protocol

from brokerage_ai.core.types import ProviderDiagnostics
from brokerage_ai.f2.types import ConsultationAnalysis, LedgerType, Transcription


class Transcriber(Protocol):
    """로컬 faster-whisper와 원격 RunPod STT가 공통으로 구현할 경계."""

    def transcribe(self, audio_path: Path) -> Transcription: ...


class ConsultationAnalyzer(Protocol):
    """Qwen 원본·QLoRA 모델을 교체 가능하게 만드는 분석 경계."""

    async def analyze(
        self,
        *,
        transcript: str,
        ledger_type: LedgerType,
    ) -> tuple[ConsultationAnalysis, ProviderDiagnostics | None]: ...
