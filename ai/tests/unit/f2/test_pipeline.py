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
        self.calls: list[str] = []

    async def analyze(self, *, transcript: str):
        self.calls.append(transcript)
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
            current_ledger_type=LedgerType.PROPERTY,
            current_fields={"단지": None, "동": "101", "호": "999", "매매가": ""},
        )
    )

    assert analyzer.calls == [transcript]
    assert result.transcript == transcript
    assert result.ledger_type is LedgerType.PROPERTY
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
            fields={"희망 단지": "한강아파트"},
            evidence={"희망 단지": "한강아파트"},
            summary="한강아파트 매수 문의.",
        )
    )
    pipeline = F2Pipeline(
        transcriber=FakeTranscriber("한강아파트를 사고 싶어요."),
        analyzer=analyzer,
    )

    result = await pipeline.run(
        F2PipelineRequest(
            audio_path=Path("memo.wav"),
            current_ledger_type=LedgerType.PROPERTY,
        )
    )

    assert result.ledger_type is LedgerType.BUYER
    assert result.ledger_mismatch is True
    assert result.proposals == ()


@pytest.mark.asyncio
async def test_new_intake_routes_buy_request_and_recommends_buyer_fields_in_one_analysis() -> None:
    transcript = "한강아파트 34평을 15억에 사고 싶어요."
    analyzer = FakeAnalyzer(
        ConsultationAnalysis(
            consultation_type=ConsultationType.BUY_REQUEST,
            fields={"희망 단지": "한강아파트", "희망 평형": "34평", "금액 원문": "15억"},
            evidence={
                "희망 단지": "한강아파트",
                "희망 평형": "34평",
                "금액 원문": "15억",
            },
            summary="한강아파트 34평 15억 매수 문의.",
        )
    )
    pipeline = F2Pipeline(transcriber=FakeTranscriber(transcript), analyzer=analyzer)

    result = await pipeline.run(F2PipelineRequest(audio_path=Path("memo.wav")))

    assert analyzer.calls == [transcript]
    assert result.ledger_type is LedgerType.BUYER
    assert result.ledger_mismatch is False
    assert [proposal.field_name for proposal in result.proposals] == [
        "희망 단지",
        "희망 평형",
        "금액 원문",
    ]


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
        F2PipelineRequest(
            audio_path=Path("memo.wav"),
            current_ledger_type=LedgerType.PROPERTY,
        )
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
        F2PipelineRequest(
            audio_path=Path("memo.wav"),
            current_ledger_type=LedgerType.PROPERTY,
        )
    )

    assert result.consultation_type is ConsultationType.OTHER
    assert result.ledger_type is None
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
            F2PipelineRequest(
                audio_path=Path("memo.wav"),
                current_ledger_type=LedgerType.BUYER,
            )
        )
    assert analyzer.calls == []


@pytest.mark.asyncio
async def test_maps_buyer_field_aliases_to_canonical_names() -> None:
    transcript = "월세 좀 알아보려고요. 이름은 홍길동이고 전화는 010-0000-0000입니다."
    analyzer = FakeAnalyzer(
        ConsultationAnalysis(
            consultation_type=ConsultationType.BUY_REQUEST,
            fields={
                "거래 구분": "월세",
                "임대인 이름": "홍길동",
                "임대인 전화": "010-0000-0000",
            },
            evidence={
                "거래 구분": "월세 좀 알아보려고요",
                "임대인 이름": "이름은 홍길동이고",
                "임대인 전화": "전화는 010-0000-0000입니다",
            },
            summary="월세 매수 문의.",
        )
    )
    pipeline = F2Pipeline(transcriber=FakeTranscriber(transcript), analyzer=analyzer)

    result = await pipeline.run(
        F2PipelineRequest(audio_path=Path("memo.wav"), current_ledger_type=LedgerType.BUYER)
    )

    assert [proposal.field_name for proposal in result.proposals] == [
        "거래 구분",
        "구입자 이름",
        "전화번호",
    ]
    assert result.proposals[2].evidence == "전화는 010-0000-0000입니다"
    assert "필드명을 정규화했습니다: 임대인 이름 → 구입자 이름" in result.uncertainties
    assert "필드명을 정규화했습니다: 임대인 전화 → 전화번호" in result.uncertainties
    assert not any(note.startswith("허용되지 않은") for note in result.uncertainties)


@pytest.mark.asyncio
async def test_alias_ignores_whitespace_and_skips_duplicate_canonical_field() -> None:
    transcript = "전세 찾습니다. 연락처는 010-1111-2222, 아니 010-3333-4444로 주세요."
    analyzer = FakeAnalyzer(
        ConsultationAnalysis(
            consultation_type=ConsultationType.BUY_REQUEST,
            fields={
                "전화번호": "010-1111-2222",
                "임차인전화": "010-3333-4444",
            },
            evidence={
                "전화번호": "연락처는 010-1111-2222",
                "임차인전화": "010-3333-4444로 주세요",
            },
            summary="전세 문의.",
        )
    )
    pipeline = F2Pipeline(transcriber=FakeTranscriber(transcript), analyzer=analyzer)

    result = await pipeline.run(
        F2PipelineRequest(audio_path=Path("memo.wav"), current_ledger_type=LedgerType.BUYER)
    )

    assert [proposal.field_name for proposal in result.proposals] == ["전화번호"]
    assert result.proposals[0].proposed_value == "010-1111-2222"
    assert (
        "같은 필드로 정규화된 중복 제안을 제외했습니다: 임차인전화 → 전화번호"
        in result.uncertainties
    )


@pytest.mark.asyncio
async def test_property_ledger_keeps_ambiguous_phone_field_excluded() -> None:
    transcript = "집 내놓으려고요. 집주인 전화는 010-5555-6666이고 전화번호는 010-7777-8888."
    analyzer = FakeAnalyzer(
        ConsultationAnalysis(
            consultation_type=ConsultationType.SELL_REQUEST,
            fields={
                "집주인 전화": "010-5555-6666",
                "전화번호": "010-7777-8888",
            },
            evidence={
                "집주인 전화": "집주인 전화는 010-5555-6666",
                "전화번호": "전화번호는 010-7777-8888",
            },
            summary="매도 의뢰.",
        )
    )
    pipeline = F2Pipeline(transcriber=FakeTranscriber(transcript), analyzer=analyzer)

    result = await pipeline.run(
        F2PipelineRequest(audio_path=Path("memo.wav"), current_ledger_type=LedgerType.PROPERTY)
    )

    assert [proposal.field_name for proposal in result.proposals] == ["임대인 전화"]
    assert "허용되지 않은 필드 제안을 제외했습니다: 전화번호" in result.uncertainties


@pytest.mark.asyncio
async def test_evidence_match_ignores_trailing_punctuation_and_phone_hyphens() -> None:
    # 실제 시연 케이스: STT 마지막 문장에는 마침표가 없는데 모델 근거에는 붙어 있었다.
    transcript = (
        "혹시 이름과 전화번호를 남겨주시겠어요 네 이름은 홍윤정이고 전화번호는 010-12345678이에요"
    )
    analyzer = FakeAnalyzer(
        ConsultationAnalysis(
            consultation_type=ConsultationType.BUY_REQUEST,
            fields={"임대인 이름": "홍윤정", "임대인 전화": "010-1234-5678"},
            evidence={
                "임대인 이름": "네 이름은 홍윤정이고 전화번호는 010-12345678이에요.",
                "임대인 전화": "전화번호는 010-1234-5678이에요.",
            },
            summary="월세 문의.",
        )
    )
    pipeline = F2Pipeline(transcriber=FakeTranscriber(transcript), analyzer=analyzer)

    result = await pipeline.run(
        F2PipelineRequest(audio_path=Path("memo.wav"), current_ledger_type=LedgerType.BUYER)
    )

    assert [(p.field_name, p.proposed_value) for p in result.proposals] == [
        ("구입자 이름", "홍윤정"),
        ("전화번호", "010-1234-5678"),
    ]
    assert not any(note.startswith("STT 원문 근거가 없는") for note in result.uncertainties)
