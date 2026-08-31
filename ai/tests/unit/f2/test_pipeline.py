from __future__ import annotations

from pathlib import Path

import pytest

from brokerage_ai.f2.errors import EmptyTranscriptionError
from brokerage_ai.f2.pipeline import F2Pipeline
from brokerage_ai.f2.types import (
    ConsultationAnalysis,
    ConsultationType,
    F2PipelineRequest,
    LedgerType,
    ProposalStatus,
    Transcription,
)


class FakeTranscriber:
    def __init__(self, text: str) -> None:
        self.text = text

    def transcribe(self, audio_path: Path) -> Transcription:
        return Transcription(text=self.text, model="fake-whisper")


class FakeAnalyzer:
    def __init__(self, analysis: ConsultationAnalysis) -> None:
        self.analysis = analysis
        self.calls: list[tuple[str, LedgerType]] = []

    async def analyze(self, *, transcript: str, ledger_type: LedgerType):
        self.calls.append((transcript, ledger_type))
        return self.analysis, None


@pytest.mark.asyncio
async def test_connects_stt_to_analysis_and_builds_review_proposals() -> None:
    transcript = "한강아파트 101동 1203호를 12억에 매도하려고 합니다."
    analyzer = FakeAnalyzer(
        ConsultationAnalysis(
            consultation_type=ConsultationType.SELL_REQUEST,
            fields={"단지": "한강아파트", "동": "101", "호": "1203", "매매가": "12억"},
            evidence={
                "단지": "한강아파트",
                "동": "101동",
                "호": "1203호",
                "매매가": "12억",
            },
            summary="한강아파트 101동 1203호를 12억에 매도 의뢰함.",
        )
    )
    pipeline = F2Pipeline(transcriber=FakeTranscriber(transcript), analyzer=analyzer)

    result = await pipeline.run(
        F2PipelineRequest(
            audio_path=Path("memo.wav"),
            ledger_type=LedgerType.PROPERTY,
            current_fields={"단지": None, "동": "101", "호": "999", "매매가": ""},
        )
    )

    assert analyzer.calls == [(transcript, LedgerType.PROPERTY)]
    assert result.transcript == transcript
    assert result.ledger_mismatch is False
    assert [proposal.field_name for proposal in result.proposals] == ["단지", "동", "호", "매매가"]
    assert result.proposals[0].selected_by_default is True
    assert result.proposals[1].status is ProposalStatus.CONFIRMED
    assert result.proposals[1].selected_by_default is False
    assert result.proposals[2].status is ProposalStatus.CHANGE
    assert result.proposals[2].selected_by_default is False


@pytest.mark.asyncio
async def test_ledger_mismatch_suppresses_all_field_proposals() -> None:
    analyzer = FakeAnalyzer(
        ConsultationAnalysis(
            consultation_type=ConsultationType.BUY_REQUEST,
            ledger_mismatch=False,
            fields={"단지": "한강아파트"},
            evidence={"단지": "한강아파트"},
            summary="한강아파트 매수 문의.",
        )
    )
    pipeline = F2Pipeline(
        transcriber=FakeTranscriber("한강아파트를 사고 싶어요."),
        analyzer=analyzer,
    )

    result = await pipeline.run(
        F2PipelineRequest(audio_path=Path("memo.wav"), ledger_type=LedgerType.PROPERTY)
    )

    assert result.ledger_mismatch is True
    assert result.proposals == ()


@pytest.mark.asyncio
async def test_filters_unknown_fields_and_evidence_not_found_in_transcript() -> None:
    analyzer = FakeAnalyzer(
        ConsultationAnalysis(
            consultation_type=ConsultationType.SELL_REQUEST,
            fields={"단지": "한강아파트", "호": "1203", "법률 판단": "안전"},
            evidence={"단지": "한강아파트", "호": "1203호", "법률 판단": "안전"},
            summary="한강아파트 매도 의뢰이며 호수는 추가 확인 필요.",
        )
    )
    pipeline = F2Pipeline(
        transcriber=FakeTranscriber("한강아파트를 매도하려고 합니다."),
        analyzer=analyzer,
    )

    result = await pipeline.run(
        F2PipelineRequest(audio_path=Path("memo.wav"), ledger_type=LedgerType.PROPERTY)
    )

    assert [proposal.field_name for proposal in result.proposals] == ["단지"]
    assert "STT 원문 근거가 없는 필드 제안을 제외했습니다: 호" in result.uncertainties
    assert "허용되지 않은 필드 제안을 제외했습니다: 법률 판단" in result.uncertainties


@pytest.mark.asyncio
async def test_other_consultation_keeps_only_the_log_draft() -> None:
    analyzer = FakeAnalyzer(
        ConsultationAnalysis(
            consultation_type=ConsultationType.OTHER,
            fields={"단지": "한강아파트"},
            evidence={"단지": "한강아파트"},
            summary="단순 시세 문의에 답변함.",
        )
    )
    pipeline = F2Pipeline(
        transcriber=FakeTranscriber("한강아파트 시세만 알려주세요."),
        analyzer=analyzer,
    )

    result = await pipeline.run(
        F2PipelineRequest(audio_path=Path("memo.wav"), ledger_type=LedgerType.PROPERTY)
    )

    assert result.consultation_type is ConsultationType.OTHER
    assert result.ledger_mismatch is False
    assert result.proposals == ()
    assert result.consultation_log_draft == "단순 시세 문의에 답변함."


@pytest.mark.asyncio
async def test_stops_before_analysis_when_transcript_is_empty() -> None:
    analysis = ConsultationAnalysis(
        consultation_type=ConsultationType.OTHER,
        summary="호출되지 않아야 함.",
    )
    analyzer = FakeAnalyzer(analysis)

    class EmptyTextTranscriber:
        def transcribe(self, audio_path: Path) -> Transcription:
            # Pydantic 검증을 우회해 외부 STT 구현이 잘못된 값을 반환하는 상황을 재현한다.
            return Transcription.model_construct(text="   ", model="fake-whisper")

    pipeline = F2Pipeline(transcriber=EmptyTextTranscriber(), analyzer=analyzer)

    with pytest.raises(EmptyTranscriptionError):
        await pipeline.run(
            F2PipelineRequest(audio_path=Path("memo.wav"), ledger_type=LedgerType.BUYER)
        )
    assert analyzer.calls == []
