from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import ClassVar
from uuid import UUID

from sqlalchemy import JSON, BigInteger, Column, Integer, Text, Uuid
from sqlmodel import Field, SQLModel

from domain.property_ledger.models import (
    created_timestamp_column,
    identity_column,
    timestamp_column,
)

# agent_run 의 고정 어휘. 이 슬라이스는 F3 교차 판정 실행 1종만 만든다.
CROSS_JUDGMENT_RUN_TYPE = "CROSS_JUDGMENT"
BROKERAGE_WORKFLOW_AGENT_TYPE = "BROKERAGE_WORKFLOW"
USER_REQUEST_TRIGGER_TYPE = "USER_REQUEST"

# 이 코드가 실제로 쓰는 상태만 상수로 둔다. 나머지 상태는 아직 구현되지 않았다.
QUEUED_STATUS = "QUEUED"
RUNNING_STATUS = "RUNNING"
ANCHOR_READY_STATUS = "ANCHOR_READY"
FAILED_TERMINAL_STATUS = "FAILED_TERMINAL"

# 포지션 카드 생성에 쓸 모델 구성의 capability. 다른 용도의 설정을 끌어다 쓰지 않는다.
POSITION_CARD_CAPABILITY = "POSITION_CARD"

# migration 005 가 컬럼 기본값으로 갖고 있는 판정값. AI 계약의 같은 이름 값과 일치한다.
UNKNOWN_JUDGEMENT = "UNKNOWN"
CAUTION_CONTACTABILITY = "CAUTION"

# Backend가 직접 기록하는 실패 어휘. 개인정보와 내부 예외를 담지 않는 고정 문구를 쓴다.
LEASE_EXPIRED_FAILURE_CODE = "LEASE_EXPIRED_MAX_ATTEMPTS"
LEASE_EXPIRED_FAILURE_MESSAGE = "실행이 최대 시도 횟수를 초과해 종료되었습니다"


class AiModelConfig(SQLModel, table=True):
    """실행에 쓸 모델 구성. 비밀값은 여기에 없고 Infra가 프로세스 환경변수로 주입한다."""

    __tablename__: ClassVar[str] = "ai_model_config"  # pyright: ignore[reportIncompatibleVariableOverride]

    id: int | None = Field(default=None, sa_column=identity_column())
    brokerage_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    capability: str = Field(max_length=50)
    config_key: str = Field(max_length=100)
    config_version: int = Field(sa_column=Column(Integer, nullable=False))
    provider: str = Field(max_length=80)
    model_name: str = Field(max_length=160)
    model_version: str | None = Field(default=None, max_length=120)
    endpoint_alias: str | None = Field(default=None, max_length=160)
    is_active: bool = True


class AgentRunAnchorError(RuntimeError):
    """루트 실행에 매물·손님 앵커가 정확히 하나 있어야 한다는 불변식을 어긴 저장 데이터."""


class LeaseNotHeldError(RuntimeError):
    """Worker가 유효한 lease 소유자가 아니다. 다른 Worker가 이미 회수했을 수 있다."""


class InputVersionChangedError(RuntimeError):
    """선점 이후 앵커 장부가 바뀌었다. 이전 입력으로 만든 카드는 재사용할 수 없다."""


class AnchorType(StrEnum):
    """교차 판정의 앵커. 매물 앵커는 반대편 손님을, 손님 앵커는 반대편 매물을 찾는다."""

    LISTING = "LISTING"
    REQUIREMENT = "REQUIREMENT"


class AgentRun(SQLModel, table=True):
    __tablename__: ClassVar[str] = "agent_run"  # pyright: ignore[reportIncompatibleVariableOverride]

    id: int | None = Field(default=None, sa_column=identity_column())
    brokerage_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    run_group_id: UUID = Field(sa_column=Column(Uuid, nullable=False))
    parent_run_id: int | None = Field(default=None, sa_column=Column(BigInteger))
    run_type: str = Field(max_length=30)
    agent_type: str = Field(max_length=30)
    status: str = Field(default=QUEUED_STATUS, max_length=30)
    trigger_type: str = Field(max_length=50)
    model_config_id: int | None = Field(default=None, sa_column=Column(BigInteger))
    model_snapshot: dict[str, object] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    prompt_version: str | None = Field(default=None, max_length=100)
    workflow_version: str | None = Field(default=None, max_length=100)
    experiment_key: str | None = Field(default=None, max_length=120)
    case_key: str | None = Field(default=None, max_length=120)
    evaluation_variant: str | None = Field(default=None, max_length=40)
    requested_by: int = Field(sa_column=Column(BigInteger, nullable=False))
    target_unit_id: int | None = Field(default=None, sa_column=Column(BigInteger))
    target_listing_id: int | None = Field(default=None, sa_column=Column(BigInteger))
    target_requirement_id: int | None = Field(default=None, sa_column=Column(BigInteger))
    input_data_version: int = Field(default=1, sa_column=Column(BigInteger, nullable=False))
    last_interaction_at: datetime | None = Field(default=None, sa_column=timestamp_column())
    redacted_input_snapshot: dict[str, object] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    redacted_output_snapshot: dict[str, object] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    input_tokens: int = Field(default=0, sa_column=Column(Integer, nullable=False, default=0))
    output_tokens: int = Field(default=0, sa_column=Column(Integer, nullable=False, default=0))
    latency_ms: int | None = Field(default=None, sa_column=Column(Integer))
    failure_code: str | None = Field(default=None, max_length=80)
    failure_message: str | None = Field(default=None, sa_column=Column(Text))
    started_at: datetime | None = Field(default=None, sa_column=timestamp_column())
    completed_at: datetime | None = Field(default=None, sa_column=timestamp_column())
    lease_owner: str | None = Field(default=None, max_length=64)
    lease_expires_at: datetime | None = Field(default=None, sa_column=timestamp_column())
    attempt_count: int = Field(default=0, sa_column=Column(Integer, nullable=False, default=0))
    retention_until: datetime | None = Field(default=None, sa_column=timestamp_column())
    purged_at: datetime | None = Field(default=None, sa_column=timestamp_column())
    created_at: datetime | None = Field(default=None, sa_column=created_timestamp_column())
    updated_at: datetime | None = Field(default=None, sa_column=created_timestamp_column())


def anchor_of(run: AgentRun) -> tuple[AnchorType, int]:
    """실행 대상 컬럼에서 앵커를 되돌린다.

    DB에는 둘 중 하나만 채우라는 CHECK 제약이 없다. 어느 쪽도 없거나 양쪽이 다 있는 행을
    억지로 변환하면 존재하지 않는 앵커를 정상 결과로 내보내므로 여기서 멈춘다.
    """
    listing_id = run.target_listing_id
    requirement_id = run.target_requirement_id
    if listing_id is not None and requirement_id is None:
        return AnchorType.LISTING, listing_id
    if requirement_id is not None and listing_id is None:
        return AnchorType.REQUIREMENT, requirement_id
    raise AgentRunAnchorError("agent run must target exactly one of a listing or a requirement")


class NegotiationPositionAnalysis(SQLModel, table=True):
    """포지션 카드. 캐시 단위이자 검증된 카드 본문의 정본이다.

    다중 거래 가격은 `negotiation_position_price`, 근거는 `negotiation_position_evidence`가
    소유한다. `analysis_snapshot`에는 검증을 통과한 공개 계약 결과 전체를 JSON으로 둔다.
    """

    __tablename__: ClassVar[str] = "negotiation_position_analysis"  # pyright: ignore[reportIncompatibleVariableOverride]

    id: int | None = Field(default=None, sa_column=identity_column())
    brokerage_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    agent_run_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    negotiation_side: str = Field(max_length=20)
    unit_id: int | None = Field(default=None, sa_column=Column(BigInteger))
    listing_id: int | None = Field(default=None, sa_column=Column(BigInteger))
    requirement_id: int | None = Field(default=None, sa_column=Column(BigInteger))
    target_label: str | None = Field(default=None, max_length=200)
    cache_key: str = Field(max_length=500)
    source_interaction_count: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, default=0)
    )
    last_interaction_at: datetime | None = Field(default=None, sa_column=timestamp_column())
    data_version: int = Field(sa_column=Column(BigInteger, nullable=False))
    negotiation_intent: str = Field(default=UNKNOWN_JUDGEMENT, max_length=20)
    stated_price_amount: int | None = Field(default=None, sa_column=Column(BigInteger))
    estimated_price_amount: int | None = Field(default=None, sa_column=Column(BigInteger))
    price_estimation_basis: str | None = Field(default=None, sa_column=Column(Text))
    urgency: str = Field(default=UNKNOWN_JUDGEMENT, max_length=20)
    preferred_timing: dict[str, object] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    flexible_conditions: list[object] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    inflexible_conditions: list[object] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    contactability_status: str = Field(default=CAUTION_CONTACTABILITY, max_length=20)
    contactability_note: str | None = Field(default=None, sa_column=Column(Text))
    analysis_snapshot: dict[str, object] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    generated_at: datetime | None = Field(default=None, sa_column=created_timestamp_column())
    invalidated_at: datetime | None = Field(default=None, sa_column=timestamp_column())
    invalidation_reason: str | None = Field(default=None, sa_column=Column(Text))
    created_at: datetime | None = Field(default=None, sa_column=created_timestamp_column())


class NegotiationPositionPrice(SQLModel, table=True):
    """카드의 거래 유형별 금액. 여러 유형 중 하나를 대표로 고르지 않기 위해 분리했다."""

    __tablename__: ClassVar[str] = "negotiation_position_price"  # pyright: ignore[reportIncompatibleVariableOverride]

    id: int | None = Field(default=None, sa_column=identity_column())
    brokerage_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    position_analysis_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    price_kind: str = Field(max_length=20)
    stated_amount: int | None = Field(default=None, sa_column=Column(BigInteger))
    stated_monthly_amount: int | None = Field(default=None, sa_column=Column(BigInteger))
    estimated_amount: int | None = Field(default=None, sa_column=Column(BigInteger))
    estimated_monthly_amount: int | None = Field(default=None, sa_column=Column(BigInteger))
    display_order: int = Field(default=0, sa_column=Column(Integer, nullable=False, default=0))
    created_at: datetime | None = Field(default=None, sa_column=created_timestamp_column())


class NegotiationPositionEvidence(SQLModel, table=True):
    """카드 항목별 근거. 인용은 상담 로그를 가리키고 추정은 설명만 남긴다."""

    __tablename__: ClassVar[str] = "negotiation_position_evidence"  # pyright: ignore[reportIncompatibleVariableOverride]

    id: int | None = Field(default=None, sa_column=identity_column())
    brokerage_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    position_analysis_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    field_name: str = Field(max_length=100)
    evidence_type: str = Field(max_length=20)
    interaction_id: int | None = Field(default=None, sa_column=Column(BigInteger))
    quote_text: str | None = Field(default=None, sa_column=Column(Text))
    quote_start_offset: int | None = Field(default=None, sa_column=Column(Integer))
    quote_end_offset: int | None = Field(default=None, sa_column=Column(Integer))
    note: str | None = Field(default=None, sa_column=Column(Text))
    display_order: int = Field(default=0, sa_column=Column(Integer, nullable=False, default=0))
    created_at: datetime | None = Field(default=None, sa_column=created_timestamp_column())
