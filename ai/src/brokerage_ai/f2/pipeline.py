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
        analysis, diagnostics = await self._analyzer.analyze(transcript=transcript)
        ledger_type = self._resolve_ledger_type(analysis.consultation_type)
        ledger_mismatch = self._is_ledger_mismatch(
            request.current_ledger_type,
            ledger_type,
        )
        if ledger_type is None:
            proposals, validation_notes = (), self._suppressed_fields_note(analysis)
        else:
            proposals, validation_notes = self._build_proposals(
                analysis=analysis,
                transcript=transcript,
                ledger_type=ledger_type,
                current_fields=(
                    request.current_fields if request.current_ledger_type is ledger_type else {}
                ),
                allow_fields=not ledger_mismatch,
            )

        return F2PipelineResult(
            transcript=transcript,
            transcription_model=transcription.model,
            ledger_type=ledger_type,
            consultation_type=analysis.consultation_type,
            ledger_mismatch=ledger_mismatch,
            proposals=proposals,
            uncertainties=tuple(analysis.uncertainties) + validation_notes,
            consultation_log_draft=analysis.summary,
            analysis_diagnostics=diagnostics,
        )

    @staticmethod
    def _resolve_ledger_type(consultation_type: ConsultationType) -> LedgerType | None:
        if consultation_type is ConsultationType.SELL_REQUEST:
            return LedgerType.PROPERTY
        if consultation_type is ConsultationType.BUY_REQUEST:
            return LedgerType.BUYER
        return None

    @staticmethod
    def _is_ledger_mismatch(
        current_ledger_type: LedgerType | None,
        recommended_ledger_type: LedgerType | None,
    ) -> bool:
        return (
            current_ledger_type is not None
            and recommended_ledger_type is not None
            and current_ledger_type is not recommended_ledger_type
        )

    @staticmethod
    def _suppressed_fields_note(analysis: ConsultationAnalysis) -> tuple[str, ...]:
        if not analysis.fields:
            return ()
        return ("기타상담의 필드 제안을 제외했습니다.",)

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
