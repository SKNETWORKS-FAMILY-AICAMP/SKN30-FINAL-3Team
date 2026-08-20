"""F3 포지션 카드의 Backend–AI 공개 계약.

이 모듈은 DTO와 어휘만 소유한다. 프롬프트, 모델 호출, 그래프와 저장은 다른 곳에 있다.
정본 문서는 `.agents/skills/project-wiki/references/contracts/f3-ai.md`다.

여기의 `POSITION_CARD_CONTRACT_VERSION`은 DTO와 의미 규격의 버전이다. Backend가 계산하는
cache key 버전(`position-card:v2`)과는 다른 축이며 서로 독립적으로 올라간다.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from brokerage_ai.core.types import ProviderDiagnostics

POSITION_CARD_CONTRACT_VERSION = "position-card:v1"

ContractVersion = Literal["position-card:v1"]


class NegotiationSide(StrEnum):
    """포지션 카드가 대리하는 측. Backend `AnchorType`과 값이 같아야 한다."""

    LISTING = "LISTING"
    REQUIREMENT = "REQUIREMENT"


class NegotiationIntent(StrEnum):
    """의향 판정. 판단이 불가하면 비우지 않고 `UNKNOWN`을 쓴다 (F3-PC-01)."""

    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    WITHDRAWN = "WITHDRAWN"
    UNKNOWN = "UNKNOWN"


class Urgency(StrEnum):
    """시급도 판정. `UNKNOWN`은 누락이 아니라 명시적 판정이다."""

    URGENT = "URGENT"
    NORMAL = "NORMAL"
    RELAXED = "RELAXED"
    UNKNOWN = "UNKNOWN"


class ContactabilityStatus(StrEnum):
    """접촉 가능 상태. 연락처가 아니라 접촉 이력에 대한 판정이다 (F3-PC-06)."""

    GOOD = "GOOD"
    CAUTION = "CAUTION"
    UNREACHABLE = "UNREACHABLE"
    UNKNOWN = "UNKNOWN"


class EvidenceKind(StrEnum):
    """근거 종류. 인용도 추정 표시도 없는 항목은 출력하지 않는다 (F3-CM-02)."""

    QUOTE = "QUOTE"
    INFERENCE = "INFERENCE"


class PriceKind(StrEnum):
    """어떤 장부 금액을 말하는지 고정한다. 새 금액 항목을 만들지 않는다."""

    SALE = "SALE"
    JEONSE = "JEONSE"
    MONTHLY_RENT = "MONTHLY_RENT"
    BUDGET = "BUDGET"


ALLOWED_PRICE_KINDS: dict[NegotiationSide, frozenset[PriceKind]] = {
    NegotiationSide.LISTING: frozenset({PriceKind.SALE, PriceKind.JEONSE, PriceKind.MONTHLY_RENT}),
    NegotiationSide.REQUIREMENT: frozenset({PriceKind.BUDGET}),
}


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


class SourceIdentity(_Frozen):
    """카드 입력 집합의 신원. 모델이 만드는 값이 아니라 Backend가 준 snapshot이다.

    Backend cache key와 저장 단계 fencing이 같은 네 값을 쓴다. 시각 하나만으로는 과거
    시각 로그 추가와 로그 무효화를 구분하지 못해 건수와 최대 ID를 함께 싣는다.
    """

    data_version: int = Field(ge=1)
    interaction_count: int = Field(ge=0)
    last_interaction_at: datetime | None = None
    max_interaction_id: int | None = Field(default=None, ge=1)

    @field_validator("last_interaction_at")
    @classmethod
    def moment_must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("last_interaction_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def interaction_identity_must_be_complete(self) -> Self:
        if self.interaction_count == 0 and (
            self.last_interaction_at is not None or self.max_interaction_id is not None
        ):
            raise ValueError("an empty interaction set must not carry a last interaction")
        if self.interaction_count > 0 and (
            self.last_interaction_at is None or self.max_interaction_id is None
        ):
            raise ValueError("a non-empty interaction set requires its last moment and maximum id")
        return self


class ConsultationLogInput(_Frozen):
    """AI에 전달하는 상담 로그 1건.

    `content`는 DB 원문이 아니라 Backend가 성명·연락처를 치환한 결과다. 치환 대응표는
    이 계약에 싣지 않는다.
    """

    interaction_id: int = Field(ge=1)
    interaction_at: datetime
    channel: str = Field(min_length=1)
    counterparty_role: str | None = None
    interaction_result: str | None = None
    masked_content: str = Field(min_length=1)

    @field_validator("channel", "counterparty_role", "interaction_result", "masked_content")
    @classmethod
    def text_must_not_be_blank(cls, value: str | None) -> str | None:
        return _reject_blank(value)

    @field_validator("interaction_at")
    @classmethod
    def moment_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("interaction_at must be timezone-aware")
        return value


class DateSignals(_Frozen):
    """Backend가 SQL로 산출한 날짜 신호 (F3-SQ-05).

    AI는 날짜 산수를 하지 않는다. 음수 경과일은 이미 지난 기한을 뜻하므로 허용한다.
    현재 데이터로 계산할 수 없는 신호는 null이며 필수로 강제하지 않는다.
    """

    as_of: datetime
    days_until_tenancy_expiry: int | None = None
    days_until_desired_move_in: int | None = None
    days_until_request_expiry: int | None = None
    days_since_last_contact: int | None = None
    days_since_received: int | None = None
    hard_deadline_candidate: date | None = None

    @field_validator("as_of")
    @classmethod
    def moment_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        return value


class ListingAnchorContext(_Frozen):
    """매물 측 입력만 담는다. 손님 측 값은 어떤 필드로도 들어올 수 없다 (F3-LA-02).

    자유 메모와 `custom_fields`는 성명·연락처가 섞일 수 있어 계약에 넣지 않는다.
    """

    negotiation_side: Literal[NegotiationSide.LISTING] = NegotiationSide.LISTING
    listing_id: int = Field(ge=1)
    unit_id: int = Field(ge=1)
    listing_status: str = Field(min_length=1)
    received_at: date | None = None
    is_sale_available: bool = False
    sale_price: int | None = Field(default=None, ge=0)
    is_jeonse_available: bool = False
    jeonse_deposit_amount: int | None = Field(default=None, ge=0)
    is_monthly_rent_available: bool = False
    monthly_rent_deposit_amount: int | None = Field(default=None, ge=0)
    monthly_rent_amount: int | None = Field(default=None, ge=0)
    price_raw_text: str | None = None
    handover_condition: str | None = None
    complex_name: str | None = None
    building_number: str | None = None
    unit_number: str = Field(min_length=1)
    floor_number: str | None = None
    orientation: str | None = None
    pyeong: Decimal | None = Field(default=None, ge=0)
    exclusive_area_sqm: Decimal | None = Field(default=None, ge=0)
    supply_area_sqm: Decimal | None = Field(default=None, ge=0)
    unit_type: str | None = None
    lifecycle_status: str | None = None
    tenancy_status: str | None = None
    current_deposit_amount: int | None = Field(default=None, ge=0)
    current_monthly_rent_amount: int | None = Field(default=None, ge=0)
    tenancy_expiry_date: date | None = None
    tenancy_raw_text: str | None = None

    @field_validator(
        "listing_status",
        "price_raw_text",
        "handover_condition",
        "complex_name",
        "building_number",
        "unit_number",
        "floor_number",
        "orientation",
        "unit_type",
        "lifecycle_status",
        "tenancy_status",
        "tenancy_raw_text",
    )
    @classmethod
    def text_must_not_be_blank(cls, value: str | None) -> str | None:
        return _reject_blank(value)


class RequirementAnchorContext(_Frozen):
    """손님 측 입력만 담는다. 매물 측 값은 어떤 필드로도 들어올 수 없다 (F3-CA-02).

    `demand_type`, `status`, `classification`, `workflow_stage`는 F1이 아직 값 목록을
    확정하지 않은 장부 표기값이라 문자열로 통과시킨다. 카드 판정 어휘가 아니다.
    """

    negotiation_side: Literal[NegotiationSide.REQUIREMENT] = NegotiationSide.REQUIREMENT
    requirement_id: int = Field(ge=1)
    demand_type: str = Field(min_length=1)
    status: str = Field(min_length=1)
    received_at: date | None = None
    classification: str | None = None
    workflow_stage: str | None = None
    min_budget_amount: int | None = Field(default=None, ge=0)
    max_budget_amount: int | None = Field(default=None, ge=0)
    budget_raw_text: str | None = None
    desired_pyeongs: tuple[Decimal, ...] = ()
    min_area_sqm: Decimal | None = Field(default=None, ge=0)
    max_area_sqm: Decimal | None = Field(default=None, ge=0)
    area_requirement_raw_text: str | None = None
    desired_complex_names: tuple[str, ...] = ()
    desired_move_in_date: date | None = None
    move_in_date_raw_text: str | None = None
    request_expiry_date: date | None = None
    current_tenancy_expiry_date: date | None = None

    @field_validator(
        "demand_type",
        "status",
        "classification",
        "workflow_stage",
        "budget_raw_text",
        "area_requirement_raw_text",
        "move_in_date_raw_text",
    )
    @classmethod
    def text_must_not_be_blank(cls, value: str | None) -> str | None:
        return _reject_blank(value)

    @field_validator("desired_pyeongs")
    @classmethod
    def pyeongs_must_not_be_negative(cls, values: tuple[Decimal, ...]) -> tuple[Decimal, ...]:
        if any(value < 0 for value in values):
            raise ValueError("desired_pyeongs must not contain negative values")
        return values

    @field_validator("desired_complex_names")
    @classmethod
    def names_must_not_be_blank(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError("desired_complex_names must not contain blank values")
        return values


AnchorContext = Annotated[
    ListingAnchorContext | RequirementAnchorContext,
    Field(discriminator="negotiation_side"),
]


class PositionCardGenerationRequest(_Frozen):
    """Backend가 AI facade에 넘기는 포지션 카드 생성 입력.

    실행 제어 값(run_id, lease, attempt_count, requested_by)과 DB 객체는 싣지 않는다.
    """

    contract_version: ContractVersion = POSITION_CARD_CONTRACT_VERSION
    negotiation_side: NegotiationSide
    anchor_id: int = Field(ge=1)
    source: SourceIdentity
    anchor: AnchorContext
    date_signals: DateSignals
    consultation_logs: tuple[ConsultationLogInput, ...] = ()

    @model_validator(mode="after")
    def anchor_must_match_the_declared_side_and_target(self) -> Self:
        if self.anchor.negotiation_side is not self.negotiation_side:
            raise ValueError("anchor context does not match the declared negotiation side")
        anchor_target = (
            self.anchor.listing_id
            if isinstance(self.anchor, ListingAnchorContext)
            else self.anchor.requirement_id
        )
        if anchor_target != self.anchor_id:
            raise ValueError("anchor context does not match anchor_id")
        return self

    @model_validator(mode="after")
    def consultation_logs_must_match_the_source_identity(self) -> Self:
        identifiers = [log.interaction_id for log in self.consultation_logs]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("consultation_logs must not repeat an interaction_id")
        if self.source.interaction_count != len(self.consultation_logs):
            raise ValueError("consultation_logs count does not match source identity")
        if self.consultation_logs:
            if self.source.max_interaction_id != max(identifiers):
                raise ValueError("consultation_logs maximum id does not match source identity")
            last_interaction_at = max(log.interaction_at for log in self.consultation_logs)
            if self.source.last_interaction_at != last_interaction_at:
                raise ValueError("consultation_logs last moment does not match source identity")
        return self

    def log_contents(self) -> dict[int, str]:
        """근거 검증용 색인. interaction_id에서 마스킹된 본문으로 간다."""
        return {log.interaction_id: log.masked_content for log in self.consultation_logs}


class Evidence(_Frozen):
    """판정 1건의 근거. 원문 인용이거나 명시적 추정이다.

    offset은 담지 않는다. 모델이 임의로 만든 위치는 신뢰할 수 없고, 실제 원문 기준
    offset은 Backend가 저장 전에 계산한다.
    """

    kind: EvidenceKind
    interaction_id: int | None = Field(default=None, ge=1)
    quote_text: str | None = None
    note: str | None = None

    @field_validator("quote_text", "note")
    @classmethod
    def text_must_not_be_blank(cls, value: str | None) -> str | None:
        return _reject_blank(value)

    @model_validator(mode="after")
    def evidence_must_carry_what_its_kind_requires(self) -> Self:
        if self.kind is EvidenceKind.QUOTE:
            if self.interaction_id is None:
                raise ValueError("QUOTE evidence requires interaction_id")
            if self.quote_text is None:
                raise ValueError("QUOTE evidence requires quote_text")
            return self
        if self.note is None:
            raise ValueError("INFERENCE evidence requires note")
        if self.interaction_id is not None or self.quote_text is not None:
            raise ValueError("INFERENCE evidence must not carry a quote")
        return self


class IntentAssessment(_Frozen):
    value: NegotiationIntent
    evidence: tuple[Evidence, ...] = Field(min_length=1)


class UrgencyAssessment(_Frozen):
    value: Urgency
    evidence: tuple[Evidence, ...] = Field(min_length=1)


class PriceAssessment(_Frozen):
    """장부 표기 금액 하나와 그에 대한 추정.

    `stated_*`는 Backend가 넣어준 장부값이며 AI가 바꾸지 않는다. 월세만 보증금과 차임
    두 금액을 가지므로 `*_monthly_amount`는 `MONTHLY_RENT`에서만 허용한다.
    """

    price_kind: PriceKind
    stated_amount: int | None = Field(default=None, ge=0)
    stated_monthly_amount: int | None = Field(default=None, ge=0)
    estimated_amount: int | None = Field(default=None, ge=0)
    estimated_monthly_amount: int | None = Field(default=None, ge=0)
    basis: tuple[Evidence, ...] = ()

    @model_validator(mode="after")
    def monthly_amounts_belong_to_monthly_rent_only(self) -> Self:
        monthly = (self.stated_monthly_amount, self.estimated_monthly_amount)
        if self.price_kind is not PriceKind.MONTHLY_RENT and any(
            amount is not None for amount in monthly
        ):
            raise ValueError("monthly amounts are only valid for MONTHLY_RENT")
        return self

    @model_validator(mode="after")
    def an_estimate_that_differs_requires_a_basis(self) -> Self:
        differs = (
            self.estimated_amount is not None and self.estimated_amount != self.stated_amount
        ) or (
            self.estimated_monthly_amount is not None
            and self.estimated_monthly_amount != self.stated_monthly_amount
        )
        if differs and not self.basis:
            raise ValueError("an estimate that differs from the stated price requires a basis")
        return self


class PositionCondition(_Frozen):
    """양보 조건과 시점 제약. 근거 없이 세우지 않는다 (F3-PC-05)."""

    description: str = Field(min_length=1)
    evidence: tuple[Evidence, ...] = Field(min_length=1)

    @field_validator("description")
    @classmethod
    def description_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("description must not be blank")
        return value.strip()


class TimingAssessment(_Frozen):
    """시점 제약과 실질 마감일.

    마감일은 Backend가 준 날짜 신호에서 나온다. 근거 제약이 하나도 없으면 마감일도 세우지
    않는다 (F3-PC-04).
    """

    constraints: tuple[PositionCondition, ...] = ()
    hard_deadline: date | None = None

    @model_validator(mode="after")
    def a_deadline_requires_at_least_one_constraint(self) -> Self:
        if self.hard_deadline is not None and not self.constraints:
            raise ValueError("hard_deadline requires at least one timing constraint")
        return self


class ContactabilityAssessment(_Frozen):
    """접촉 가능 상태. 전화번호와 이메일은 어떤 필드에도 담지 않는다."""

    status: ContactabilityStatus
    note: str | None = None
    evidence: tuple[Evidence, ...] = Field(min_length=1)

    @field_validator("note")
    @classmethod
    def note_must_not_be_blank(cls, value: str | None) -> str | None:
        return _reject_blank(value)


class PositionCardAnalysis(_Frozen):
    """모델이 만든 포지션 판정 내용 (F3-PC-01의 항목 전체)."""

    intent: IntentAssessment
    price: tuple[PriceAssessment, ...] = ()
    urgency: UrgencyAssessment
    timing: TimingAssessment
    flexible: tuple[PositionCondition, ...] = ()
    inflexible: tuple[PositionCondition, ...] = ()
    contactability: ContactabilityAssessment

    @model_validator(mode="after")
    def each_price_kind_appears_once(self) -> Self:
        kinds = [assessment.price_kind for assessment in self.price]
        if len(set(kinds)) != len(kinds):
            raise ValueError("price must not repeat a price_kind")
        return self


class PositionCardTarget(_Frozen):
    """대상과 입력 신원. 요청에서 그대로 복사하며 모델 출력으로 받지 않는다."""

    negotiation_side: NegotiationSide
    anchor_id: int = Field(ge=1)
    source: SourceIdentity

    @classmethod
    def from_request(cls, request: PositionCardGenerationRequest) -> PositionCardTarget:
        return cls(
            negotiation_side=request.negotiation_side,
            anchor_id=request.anchor_id,
            source=request.source,
        )


class PositionCardGenerationResult(_Frozen):
    """AI facade가 Backend에 돌려주는 결과. DB 저장 부수 효과는 없다.

    `cache_key`와 `generated_at`은 여기에 없다. cache key는 Backend가 계산하고 생성 시각은
    Backend 또는 DB가 저장 시점에 정한다.
    """

    contract_version: ContractVersion = POSITION_CARD_CONTRACT_VERSION
    target: PositionCardTarget
    analysis: PositionCardAnalysis
    prompt_version: str | None = None
    workflow_version: str | None = None
    diagnostics: ProviderDiagnostics | None = None

    @field_validator("prompt_version", "workflow_version")
    @classmethod
    def version_must_not_be_blank(cls, value: str | None) -> str | None:
        return _reject_blank(value)
