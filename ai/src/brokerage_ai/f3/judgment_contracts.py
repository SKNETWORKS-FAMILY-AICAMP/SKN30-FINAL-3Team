"""F3 중개 판정의 Backend–AI 공개 계약.

앵커 포지션 카드 1장과 반대편 후보 카드 N장을 **한 번의 호출**로 받아 후보별 등급·순위·
근거·행동을 낸다 (F3-BR-01, F3-BR-02). 이 모듈은 DTO 와 어휘만 소유한다. 프롬프트, 모델
호출과 저장은 다른 곳에 있다.

정본 문서는 `.agents/skills/project-wiki/references/contracts/f3-ai.md` 다.

## 왜 brokerage_id 와 run_id 가 없는가

승인된 개인정보 경계가 실행 제어 값(`run_id`, `brokerage_id`, `requested_by`, lease)을 AI
공개 계약에 넣지 않는다. 그래서 요청·결과 대조는 tenant 식별자가 아니라 **카드 ID** 로 한다.
결과의 앵커 카드 ID 와 후보 카드 ID 집합이 요청과 정확히 같아야 하며, 그것이 "이 결과가 이
요청에 대한 것인가"를 판정하는 기준이다. tenant 격리와 lease 확인은 Backend 가 저장 직전에
DB 현재 상태로 따로 한다.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from brokerage_ai.core.types import ProviderDiagnostics
from brokerage_ai.f3.contracts import (
    Evidence,
    InputPrivacyMode,
    NegotiationSide,
    PositionCardAnalysis,
)

BROKERAGE_JUDGMENT_CONTRACT_VERSION = "brokerage-judgment:v1"

JudgmentContractVersion = Literal["brokerage-judgment:v1"]

# 자유 문자열의 상한. 화면에 접어서 보여줄 문장이지 보고서가 아니다. 상한을 두면 모델이
# 근거 대신 장문을 만들어 저장 비용과 개인정보 노출면을 키우는 것을 막는다.
TEXT_MAX_LENGTH = 500


class MatchGrade(StrEnum):
    """중개 판정 등급 (F3-BR-03).

    강함·약함·기각 셋뿐이다. 같은 의미에 동의어를 두지 않는다. 화면 한국어 표기는 별도
    표시 매핑이며 저장 어휘로 되돌리지 않는다.
    """

    STRONG = "STRONG"
    WEAK = "WEAK"
    REJECTED = "REJECTED"


class ContactChannel(StrEnum):
    """행동 제안의 접촉 경로 (F3-BR-07).

    F3 판정 어휘이며 F1 의 `client_interaction.interaction_channel` 과 다른 축이다. F1 은
    아직 채널 값 목록을 확정하지 않았고, 여기서 필요한 것은 "어떻게 먼저 접촉할지"의 최소
    구분이다. 카드의 `contactability` 판정을 따른다.
    """

    CALL = "CALL"
    MESSAGE = "MESSAGE"
    IN_PERSON = "IN_PERSON"


class _Frozen(BaseModel):
    """공개 계약의 공통 규칙. 불변이고 선언하지 않은 필드를 받지 않는다."""

    model_config = ConfigDict(frozen=True, extra="forbid")


def _reject_blank(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        raise ValueError("value must not be blank")
    return normalized


class JudgmentCard(_Frozen):
    """중개 판정에 넣는 포지션 카드 1장.

    카드 본문은 포지션 카드 계약의 `PositionCardAnalysis` 를 그대로 쓴다. 판정 입력은 곧
    두 대리의 출력이므로 별도 표현을 만들면 두 규격이 갈라진다 (F3-PC-01).

    `card_id` 는 Backend 의 `negotiation_position_analysis.id` 다. 성명·연락처가 아닌 내부
    식별자이며 결과 대조의 기준이 된다.
    """

    card_id: int = Field(ge=1)
    negotiation_side: NegotiationSide
    target_label: str = Field(min_length=1, max_length=200)
    analysis: PositionCardAnalysis

    @field_validator("target_label")
    @classmethod
    def label_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("target_label must not be blank")
        return value.strip()

    def quoted(self) -> frozenset[tuple[int, str]]:
        """이 카드가 실제로 인용한 `(interaction_id, quote_text)` 쌍.

        판정은 카드가 이미 들고 있는 인용만 다시 쓸 수 있다. 판정 단계에는 상담 원문이
        없으므로 여기 없는 인용은 모델이 만들어 낸 것이다.
        """
        pairs: set[tuple[int, str]] = set()
        for evidence in _card_evidence(self.analysis):
            if evidence.interaction_id is not None and evidence.quote_text is not None:
                pairs.add((evidence.interaction_id, evidence.quote_text))
        return frozenset(pairs)


def _card_evidence(analysis: PositionCardAnalysis) -> tuple[Evidence, ...]:
    """카드 안의 모든 근거. 포지션 카드 검증과 같은 순회 규칙을 쓴다."""
    collected: list[Evidence] = [
        *analysis.intent.evidence,
        *analysis.urgency.evidence,
        *analysis.contactability.evidence,
    ]
    for assessment in analysis.price:
        collected.extend(assessment.basis)
    for condition in (*analysis.timing.constraints, *analysis.flexible, *analysis.inflexible):
        collected.extend(condition.evidence)
    return tuple(collected)


class JudgmentEvidence(_Frozen):
    """판정 근거 1건. 어느 카드에서 나온 근거인지 함께 밝힌다.

    근거 자체의 규칙은 포지션 카드와 같다. `Evidence` 를 합성으로 재사용해 두 곳의 규칙이
    갈라지지 않게 한다. 인용이면 그 카드가 이미 갖고 있던 인용이어야 하고, 정황 판단이면
    `INFERENCE` 로 명시한다 (F3-TR-01).
    """

    evidence_side: NegotiationSide
    field_name: str | None = Field(default=None, max_length=100)
    source: Evidence

    @field_validator("field_name")
    @classmethod
    def field_name_must_not_be_blank(cls, value: str | None) -> str | None:
        return _reject_blank(value)


class RecommendedAction(_Frozen):
    """누구에게 먼저 · 무슨 말을 · 어떤 경로로 접촉할지 (F3-BR-07).

    경로는 대상 카드의 `contactability` 판정을 따른다. 문안 자체를 여기서 만들지 않는다.
    실제 발송 문안은 사용자가 [문자 보내기]를 누를 때 생성한다 (F3-CR-07).
    """

    contact_side: NegotiationSide
    channel: ContactChannel
    message: str = Field(min_length=1, max_length=TEXT_MAX_LENGTH)

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be blank")
        return value.strip()


class CandidateJudgment(_Frozen):
    """후보 1건의 판정.

    기각도 결과에 남는다. 조용히 사라지는 후보를 만들지 않으며 기각에는 사유가 반드시 있어야
    한다 (F3-BR-10, F3-TR-04).
    """

    card_id: int = Field(ge=1)
    grade: MatchGrade
    rank: int = Field(ge=1)
    comparison_basis: str = Field(min_length=1, max_length=TEXT_MAX_LENGTH)
    primary_obstacle: str | None = Field(default=None, max_length=TEXT_MAX_LENGTH)
    possible_concession: str | None = Field(default=None, max_length=TEXT_MAX_LENGTH)
    recommended_action: RecommendedAction | None = None
    rejection_reason: str | None = Field(default=None, max_length=TEXT_MAX_LENGTH)
    evidence: tuple[JudgmentEvidence, ...] = Field(min_length=1)

    @field_validator("comparison_basis", "primary_obstacle", "possible_concession")
    @classmethod
    def text_must_not_be_blank(cls, value: str | None) -> str | None:
        return _reject_blank(value)

    @field_validator("rejection_reason")
    @classmethod
    def reason_must_not_be_blank(cls, value: str | None) -> str | None:
        return _reject_blank(value)

    @model_validator(mode="after")
    def a_rejection_requires_its_reason(self) -> Self:
        if self.grade is MatchGrade.REJECTED and self.rejection_reason is None:
            raise ValueError("a REJECTED candidate requires a rejection_reason")
        if self.grade is not MatchGrade.REJECTED and self.rejection_reason is not None:
            raise ValueError("only a REJECTED candidate may carry a rejection_reason")
        return self


class BrokerageJudgmentTarget(_Frozen):
    """무엇을 판정했는지. 요청에서 결정적으로 복사하며 모델 출력으로 받지 않는다."""

    anchor_card_id: int = Field(ge=1)
    anchor_side: NegotiationSide
    candidate_card_ids: tuple[int, ...] = Field(min_length=1, max_length=5)

    @field_validator("candidate_card_ids")
    @classmethod
    def candidate_ids_must_be_unique(cls, values: tuple[int, ...]) -> tuple[int, ...]:
        if len(set(values)) != len(values):
            raise ValueError("candidate_card_ids must not repeat a card")
        if any(value < 1 for value in values):
            raise ValueError("candidate_card_ids must be positive")
        return values

    @classmethod
    def from_request(cls, request: BrokerageJudgmentRequest) -> BrokerageJudgmentTarget:
        return cls(
            anchor_card_id=request.anchor.card_id,
            anchor_side=request.anchor.negotiation_side,
            candidate_card_ids=tuple(card.card_id for card in request.candidates),
        )


class BrokerageJudgmentRequest(_Frozen):
    """Backend 가 AI facade 에 넘기는 중개 판정 입력.

    앵커 카드는 **한 번만** 싣는다. 후보 수만큼 반복 전송하지 않는다 (F3-BR-02).
    후보가 0건이면 이 요청 자체를 만들지 않는다. 판정할 것이 없으면 모델도 부르지 않는다.
    """

    contract_version: JudgmentContractVersion = BROKERAGE_JUDGMENT_CONTRACT_VERSION
    input_privacy_mode: InputPrivacyMode
    anchor: JudgmentCard
    candidates: tuple[JudgmentCard, ...] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def candidates_must_be_the_opposite_side_and_distinct(self) -> Self:
        identifiers = [card.card_id for card in self.candidates]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("candidates must not repeat a card")
        if self.anchor.card_id in identifiers:
            raise ValueError("the anchor card must not also be a candidate")
        for card in self.candidates:
            if card.negotiation_side is self.anchor.negotiation_side:
                raise ValueError("candidates must be on the opposite negotiation side")
        return self

    def card_by_id(self) -> dict[int, JudgmentCard]:
        """앵커와 후보를 한 색인에 모은다. 근거가 어느 카드 것인지 확인할 때 쓴다."""
        return {self.anchor.card_id: self.anchor, **{c.card_id: c for c in self.candidates}}

    @property
    def candidate_side(self) -> NegotiationSide:
        return self.candidates[0].negotiation_side


class BrokerageJudgmentResult(_Frozen):
    """AI facade 가 Backend 에 돌려주는 판정 결과. DB 저장 부수 효과는 없다.

    판정한 후보를 **전부** 담는다. 컷이 없고 기각도 남는다 (F3-CR-05, F3-BR-10).
    """

    contract_version: JudgmentContractVersion = BROKERAGE_JUDGMENT_CONTRACT_VERSION
    target: BrokerageJudgmentTarget
    candidates: tuple[CandidateJudgment, ...] = Field(min_length=1)
    prompt_version: str | None = None
    workflow_version: str | None = None
    diagnostics: ProviderDiagnostics | None = None

    @field_validator("prompt_version", "workflow_version")
    @classmethod
    def version_must_not_be_blank(cls, value: str | None) -> str | None:
        return _reject_blank(value)
