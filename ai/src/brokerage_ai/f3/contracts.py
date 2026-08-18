"""F3 포지션 카드와 중개 판정의 프레임워크 중립 계약.

Backend 는 이 DTO 만 주고받는다. LangGraph 상태, 프롬프트 원문과 Provider 응답 타입은
`ai/` 안에 가둔다. 카드 항목의 어휘(있음·불명·급함 …)는 판정 규칙 문서의 업무 표기를 따른다.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Side = Literal["매물", "손님"]
IntentValue = Literal["있음", "없음", "불명", "철회"]
UrgencyValue = Literal["급함", "보통", "여유", "불명"]
ContactStatus = Literal["양호", "주의", "불가"]
DealType = Literal["매매", "임대", "불명"]


class PositionCardInput(BaseModel):
    """대리 1회 호출의 입력.

    대리 격리는 프롬프트가 아니라 이 입력으로 한다 — 반대편을 담을 필드가 아예 없다.
    `logs` 는 `[YY-MM-DD HH:MM 구분]인덱스본문` 형식의 상담 로그 원문이다.
    """

    model_config = ConfigDict(frozen=True)

    side: Side
    label: str = Field(min_length=1)
    pyeong: float | None = None
    deal_type_book: str | None = None
    book_amount: float | None = Field(
        default=None,
        description="장부 표기 금액(억). 매물이면 호가, 손님이면 예산이다.",
    )
    note: str | None = None
    logs: tuple[str, ...] = ()


class IntentSection(BaseModel):
    value: IntentValue
    evidence: str | None
    speaker: str | None
    note: str | None


class PriceSection(BaseModel):
    estimated: float | None
    basis: str | None
    concession: float | None
    speaker: str | None
    conflict: str | None
    stated_by_tenant: bool | None


class UrgencySection(BaseModel):
    value: UrgencyValue
    evidence: str | None


class ContactabilitySection(BaseModel):
    status: ContactStatus
    note: str | None
    route: str | None


class SpeakerSection(BaseModel):
    key: str
    n: int
    last: str
    contact: str | None
    last_stmt: str | None


class DealTypeSection(BaseModel):
    value: DealType
    ref: str | None


class PositionCard(BaseModel):
    """대리가 세운 당사자 1인의 입장. 등급은 여기 없다 — 코드가 계산한다."""

    intent: IntentSection
    price: PriceSection
    urgency: UrgencySection
    flexible: list[str]
    inflexible: list[str]
    contactability: ContactabilitySection
    speakers: list[SpeakerSection]
    deal_type_now: DealTypeSection


class CandidateCardInput(BaseModel):
    """중개 판정에 넘기는 후보 축약본.

    근거 원문은 화면 표시용이고 판정에는 값만 있으면 된다. 후보 N 건이 한 프롬프트에
    들어가므로 축약하지 않으면 토큰이 후보 수에 비례해 터진다.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    label: str
    card: PositionCard


class MatchVerdict(BaseModel):
    """후보 1건에 대한 중개 판정의 서술. 등급·점수는 담지 않는다."""

    id: str
    blocker: str
    concession: str
    action: str


class MatchVerdictList(BaseModel):
    verdicts: list[MatchVerdict]


class AgentCallTrace(BaseModel):
    """추적 사슬용 실행 메타데이터. 프롬프트 원문은 담지 않는다."""

    model_config = ConfigDict(frozen=True)

    agent: str
    prompt_version: str
    provider: str
    model: str
    latency_ms: float
    input_tokens: int | None = None
    output_tokens: int | None = None
    request_id: str | None = None


class PositionCardResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    card: PositionCard
    trace: AgentCallTrace


class MatchJudgementResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    verdicts: tuple[MatchVerdict, ...]
    trace: AgentCallTrace
