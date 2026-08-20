from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from brokerage_ai.core.types import ProviderDiagnostics


class LedgerType(StrEnum):
    """F2가 제안값을 만들 수 있는 현재 장부 종류."""

    PROPERTY = "매물장"
    BUYER = "구입장"


class ConsultationType(StrEnum):
    """음성메모에서 분류하는 상담 유형."""

    SELL_REQUEST = "매도의뢰"
    BUY_REQUEST = "매수문의"
    CO_BROKERAGE = "공동중개"
    SIMPLE_INQUIRY = "단순문의"


class ProposalStatus(StrEnum):
    """사용자 검토표에 표시할 제안 상태."""

    CONFIRMED = "확인됨"
    NEEDS_REVIEW = "확인 필요"
    CHANGE = "변경"


class Transcription(BaseModel):
    """STT 구현체가 반환하는 텍스트와 실행 모델 정보."""

    model_config = ConfigDict(frozen=True)

    text: str = Field(min_length=1)
    model: str = Field(min_length=1)

    @field_validator("text", "model")
    @classmethod
    def values_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized


class ConsultationAnalysis(BaseModel):
    """sLLM이 생성해야 하는 구조화 출력 계약.

    금액과 날짜를 AI 단계에서 임의 정규화하지 않도록 필드 값은 원문 기반 문자열로
    유지한다. Backend는 사용자 승인 후 실제 장부 타입에 맞게 다시 검증한다.
    """

    model_config = ConfigDict(frozen=True)

    consultation_type: ConsultationType
    ledger_mismatch: bool = False
    fields: dict[str, str] = Field(default_factory=dict)
    evidence: dict[str, str] = Field(default_factory=dict)
    uncertainties: tuple[str, ...] = ()
    summary: str = Field(min_length=1)

    @field_validator("summary")
    @classmethod
    def summary_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("summary must not be blank")
        return value.strip()


class F2PipelineRequest(BaseModel):
    """Backend가 F2 파이프라인에 전달하는 프레임워크 중립 요청."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    audio_path: Path
    ledger_type: LedgerType
    current_fields: dict[str, str | None] = Field(default_factory=dict)


class FieldProposal(BaseModel):
    """장부에 저장하기 전 사용자에게 보여줄 필드별 제안."""

    model_config = ConfigDict(frozen=True)

    field_name: str
    current_value: str | None = None
    proposed_value: str
    evidence: str
    status: ProposalStatus
    selected_by_default: bool


class F2PipelineResult(BaseModel):
    """DB를 수정하지 않고 Backend에 반환하는 F2 분석 결과."""

    model_config = ConfigDict(frozen=True)

    transcript: str
    transcription_model: str
    ledger_type: LedgerType
    consultation_type: ConsultationType
    ledger_mismatch: bool
    proposals: tuple[FieldProposal, ...]
    uncertainties: tuple[str, ...]
    consultation_log_draft: str
    analysis_diagnostics: ProviderDiagnostics | None = None
