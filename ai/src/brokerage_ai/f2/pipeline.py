from __future__ import annotations

import asyncio
import re

from brokerage_ai.f2.errors import EmptyTranscriptionError
from brokerage_ai.f2.ports import ConsultationAnalyzer, Transcriber
from brokerage_ai.f2.prompts import ALLOWED_FIELDS
from brokerage_ai.f2.types import (
    ConsultationAnalysis,
    ConsultationType,
    F2PipelineRequest,
    F2PipelineResult,
    FieldProposal,
    LedgerType,
    ProposalStatus,
)


class F2Pipeline:
    """음성 전사와 상담 분석을 연결해 사용자 검토용 제안만 반환한다.

    이 클래스는 DB나 Repository를 알지 않는다. 반환된 제안의 승인, 타입 변환, 중복 검사,
    저장과 감사 이력은 Backend가 담당한다.
    """

    def __init__(
        self,
        *,
        transcriber: Transcriber,
        analyzer: ConsultationAnalyzer,
    ) -> None:
        self._transcriber = transcriber
        self._analyzer = analyzer

    async def run(self, request: F2PipelineRequest) -> F2PipelineResult:
        # faster-whisper는 동기 작업이므로 이벤트 루프를 막지 않도록 worker thread에서 실행한다.
        transcription = await asyncio.to_thread(
            self._transcriber.transcribe,
            request.audio_path,
        )
        transcript = transcription.text.strip()
        if not transcript:
            raise EmptyTranscriptionError("STT 결과가 비어 있어 sLLM 분석을 중단했습니다.")

        # 기존 필드값은 모델에 전달하지 않는다. 분석 이후 제안 상태를 정할 때만 사용한다.
        analysis, diagnostics = await self._analyzer.analyze(
            transcript=transcript,
            ledger_type=request.ledger_type,
        )
        ledger_mismatch = self._is_ledger_mismatch(
            request.ledger_type,
            analysis.consultation_type,
        )
        proposals, validation_notes = self._build_proposals(
            analysis=analysis,
            transcript=transcript,
            ledger_type=request.ledger_type,
            current_fields=request.current_fields,
            allow_fields=self._allows_field_proposals(
                ledger_type=request.ledger_type,
                consultation_type=analysis.consultation_type,
                ledger_mismatch=ledger_mismatch,
            ),
        )

        return F2PipelineResult(
            transcript=transcript,
            transcription_model=transcription.model,
            ledger_type=request.ledger_type,
            consultation_type=analysis.consultation_type,
            ledger_mismatch=ledger_mismatch,
            proposals=proposals,
            uncertainties=tuple(analysis.uncertainties) + validation_notes,
            consultation_log_draft=analysis.summary,
            analysis_diagnostics=diagnostics,
        )

    @staticmethod
    def _is_ledger_mismatch(
        ledger_type: LedgerType,
        consultation_type: ConsultationType,
    ) -> bool:
        return (
            ledger_type is LedgerType.PROPERTY and consultation_type is ConsultationType.BUY_REQUEST
        ) or (
            ledger_type is LedgerType.BUYER and consultation_type is ConsultationType.SELL_REQUEST
        )

    @staticmethod
    def _allows_field_proposals(
        *,
        ledger_type: LedgerType,
        consultation_type: ConsultationType,
        ledger_mismatch: bool,
    ) -> bool:
        if ledger_mismatch:
            return False
        return (
            ledger_type is LedgerType.PROPERTY
            and consultation_type is ConsultationType.SELL_REQUEST
        ) or (ledger_type is LedgerType.BUYER and consultation_type is ConsultationType.BUY_REQUEST)

    @classmethod
    def _build_proposals(
        cls,
        *,
        analysis: ConsultationAnalysis,
        transcript: str,
        ledger_type: LedgerType,
        current_fields: dict[str, str | None],
        allow_fields: bool,
    ) -> tuple[tuple[FieldProposal, ...], tuple[str, ...]]:
        if not allow_fields:
            note = (
                "현재 장부와 상담 유형이 다르거나 필드 자동 제안 대상이 아닌 상담 유형입니다."
                if analysis.fields
                else None
            )
            return (), (note,) if note else ()

        proposals: list[FieldProposal] = []
        notes: list[str] = []
        allowed_fields = ALLOWED_FIELDS[ledger_type]
        normalized_transcript = cls._without_whitespace(transcript)

        for field_name, proposed_value in analysis.fields.items():
            if field_name not in allowed_fields:
                notes.append(f"허용되지 않은 필드 제안을 제외했습니다: {field_name}")
                continue
            evidence = analysis.evidence.get(field_name, "").strip()
            if not evidence or cls._without_whitespace(evidence) not in normalized_transcript:
                notes.append(f"STT 원문 근거가 없는 필드 제안을 제외했습니다: {field_name}")
                continue

            current_value = current_fields.get(field_name)
            current_is_empty = current_value is None or not current_value.strip()
            same_value = (
                current_value is not None
                and bool(current_value.strip())
                and cls._normalized_value(current_value) == cls._normalized_value(proposed_value)
            )
            status = (
                ProposalStatus.CONFIRMED
                if current_is_empty or same_value
                else ProposalStatus.CHANGE
            )
            proposals.append(
                FieldProposal(
                    field_name=field_name,
                    current_value=current_value,
                    proposed_value=proposed_value,
                    evidence=evidence,
                    status=status,
                    selected_by_default=current_is_empty,
                )
            )

        return tuple(proposals), tuple(notes)

    @staticmethod
    def _without_whitespace(value: str) -> str:
        return re.sub(r"\s+", "", value)

    @staticmethod
    def _normalized_value(value: str) -> str:
        return re.sub(r"[\s,원]", "", value).casefold()
