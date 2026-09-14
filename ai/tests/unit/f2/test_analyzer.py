"""Connect the real analyzer and proposal pipeline with a deterministic provider."""

from pathlib import Path

import pytest

from brokerage_ai.core.errors import ProviderTimeoutError
from brokerage_ai.core.types import (
    ModelRoute,
    ProviderDiagnostics,
    ProviderKind,
    StructuredGenerationResult,
)
from brokerage_ai.f2.analyzer import LlmConsultationAnalyzer
from brokerage_ai.f2.pipeline import F2Pipeline
from brokerage_ai.f2.types import ConsultationAnalysis, F2PipelineRequest, LedgerType, Transcription


class FakeTranscriber:
    def transcribe(self, audio_path: Path) -> Transcription:
        return Transcription(text="한강아파트를 12억에 매도하려고 합니다.", model="synthetic-stt")


class RecordingProvider:
    kind = ProviderKind.VLLM

    def __init__(self, error=None):
        self.calls = []
        self.error = error

    async def generate_structured(self, request, output_schema):
        self.calls.append((request, output_schema))
        if self.error:
            raise self.error
        return StructuredGenerationResult(
            output=output_schema.model_validate(
                {
                    "consultation_type": "매도의뢰",
                    "fields": {"단지": "한강아파트", "매매가": "12억"},
                    "evidence": {"단지": "한강아파트", "매매가": "12억"},
                    "summary": "12억 매도 의뢰",
                }
            ),
            diagnostics=ProviderDiagnostics(
                provider=self.kind, model="synthetic-llm", latency_ms=1
            ),
        )


async def test_real_analyzer_only_sends_transcript_and_returns_review_proposals():
    provider = RecordingProvider()
    analyzer = LlmConsultationAnalyzer(
        provider=provider,
        route=ModelRoute(provider=provider.kind, model="synthetic-llm"),
        max_output_tokens=512,
    )
    result = await F2Pipeline(transcriber=FakeTranscriber(), analyzer=analyzer).run(
        F2PipelineRequest(
            audio_path=Path("synthetic.wav"),
            current_ledger_type=LedgerType.PROPERTY,
            current_fields={"단지": "LEDGER_VALUE_MUST_NOT_REACH_MODEL"},
        )
    )
    assert len(provider.calls) == 1
    sent, schema = provider.calls[0]
    assert schema is ConsultationAnalysis
    assert sent.temperature == 0
    assert sent.max_output_tokens == 512
    assert result.transcript in sent.messages[-1].content
    assert all(
        "LEDGER_VALUE_MUST_NOT_REACH_MODEL" not in message.content for message in sent.messages
    )
    assert result.ledger_type is LedgerType.PROPERTY
    assert [item.field_name for item in result.proposals] == ["단지", "매매가"]
    assert result.proposals[0].selected_by_default is False
    assert result.proposals[1].selected_by_default is True
    assert result.analysis_diagnostics is not None
    assert result.analysis_diagnostics.model == "synthetic-llm"


async def test_real_analyzer_preserves_provider_failure_without_implicit_retry():
    error = ProviderTimeoutError()
    provider = RecordingProvider(error)
    analyzer = LlmConsultationAnalyzer(
        provider=provider,
        route=ModelRoute(provider=provider.kind, model="synthetic-llm"),
    )
    with pytest.raises(ProviderTimeoutError) as raised:
        await F2Pipeline(transcriber=FakeTranscriber(), analyzer=analyzer).run(
            F2PipelineRequest(audio_path=Path("synthetic.wav"))
        )
    assert raised.value is error
    assert len(provider.calls) == 1
