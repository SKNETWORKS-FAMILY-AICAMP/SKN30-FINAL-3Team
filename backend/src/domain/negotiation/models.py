"""에이전트 실행·포지션 카드·매칭 판정 테이블 모델.

DDL 004~006 이 세워 둔 추적 사슬을 그대로 쓴다.

    상담 원문 → 모델·프롬프트 버전 → agent_run → 포지션 판단 → 후보 판정 → 판정 근거

`brokerage_id` 는 모든 테이블에 있고 복합 FK 로 테넌트를 묶는다. 조회는 반드시 함께 건다.
"""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    DateTime,
    Integer,
    Text,
    Uuid,
    func,
)
from sqlmodel import Field, SQLModel


def identity_column() -> Column[int]:
    return Column(BigInteger, primary_key=True, autoincrement=True)


def timestamp_column() -> Column[datetime]:
    return Column(DateTime(timezone=True))


def created_timestamp_column() -> Column[datetime]:
    return Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AgentRun(SQLModel, table=True):
    __tablename__: ClassVar[str] = "agent_run"  # pyright: ignore[reportIncompatibleVariableOverride]

    id: int | None = Field(default=None, sa_column=identity_column())
    brokerage_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    run_group_id: UUID = Field(sa_column=Column(Uuid, nullable=False))
    parent_run_id: int | None = Field(default=None, sa_column=Column(BigInteger))
    run_type: str = Field(max_length=30)
    agent_type: str = Field(max_length=30)
    status: str = Field(default="QUEUED", max_length=20)
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
    input_tokens: int = Field(default=0, sa_column=Column(Integer, nullable=False))
    output_tokens: int = Field(default=0, sa_column=Column(Integer, nullable=False))
    latency_ms: int | None = Field(default=None, sa_column=Column(Integer))
    failure_code: str | None = Field(default=None, max_length=80)
    failure_message: str | None = Field(default=None, sa_column=Column(Text))
    started_at: datetime | None = Field(default=None, sa_column=timestamp_column())
    completed_at: datetime | None = Field(default=None, sa_column=timestamp_column())
    retention_until: datetime | None = Field(default=None, sa_column=timestamp_column())
    purged_at: datetime | None = Field(default=None, sa_column=timestamp_column())
    created_at: datetime | None = Field(default=None, sa_column=created_timestamp_column())
    updated_at: datetime | None = Field(default=None, sa_column=created_timestamp_column())


class NegotiationPositionAnalysis(SQLModel, table=True):
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
    source_interaction_count: int = Field(default=0, sa_column=Column(Integer, nullable=False))
    last_interaction_at: datetime | None = Field(default=None, sa_column=timestamp_column())
    data_version: int = Field(sa_column=Column(BigInteger, nullable=False))
    negotiation_intent: str = Field(default="UNKNOWN", max_length=20)
    stated_price_amount: int | None = Field(default=None, sa_column=Column(BigInteger))
    estimated_price_amount: int | None = Field(default=None, sa_column=Column(BigInteger))
    price_estimation_basis: str | None = Field(default=None, sa_column=Column(Text))
    urgency: str = Field(default="UNKNOWN", max_length=20)
    preferred_timing: dict[str, object] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    flexible_conditions: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    inflexible_conditions: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    contactability_status: str = Field(default="CAUTION", max_length=20)
    contactability_note: str | None = Field(default=None, sa_column=Column(Text))
    analysis_snapshot: dict[str, object] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    generated_at: datetime | None = Field(default=None, sa_column=created_timestamp_column())
    invalidated_at: datetime | None = Field(default=None, sa_column=timestamp_column())
    invalidation_reason: str | None = Field(default=None, sa_column=Column(Text))
    created_at: datetime | None = Field(default=None, sa_column=created_timestamp_column())


class NegotiationPositionEvidence(SQLModel, table=True):
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
    display_order: int = Field(default=0, sa_column=Column(Integer, nullable=False))
    created_at: datetime | None = Field(default=None, sa_column=created_timestamp_column())


class MatchEvaluation(SQLModel, table=True):
    __tablename__: ClassVar[str] = "match_evaluation"  # pyright: ignore[reportIncompatibleVariableOverride]

    id: int | None = Field(default=None, sa_column=identity_column())
    brokerage_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    agent_run_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    anchor_position_analysis_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    candidate_count: int = Field(default=0, sa_column=Column(Integer, nullable=False))
    data_version: int = Field(sa_column=Column(BigInteger, nullable=False))
    candidate_selection_snapshot: dict[str, object] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    generated_at: datetime | None = Field(default=None, sa_column=created_timestamp_column())
    created_at: datetime | None = Field(default=None, sa_column=created_timestamp_column())


class MatchCandidateEvaluation(SQLModel, table=True):
    __tablename__: ClassVar[str] = "match_candidate_evaluation"  # pyright: ignore[reportIncompatibleVariableOverride]

    id: int | None = Field(default=None, sa_column=identity_column())
    brokerage_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    match_evaluation_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    candidate_position_analysis_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    match_grade: str = Field(max_length=20)
    match_rank: int = Field(sa_column=Column(Integer, nullable=False))
    evaluation_basis: str = Field(sa_column=Column(Text, nullable=False))
    primary_obstacle: str | None = Field(default=None, sa_column=Column(Text))
    possible_concession: str | None = Field(default=None, sa_column=Column(Text))
    recommended_action: dict[str, object] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    exclusion_reason: str | None = Field(default=None, sa_column=Column(Text))
    created_at: datetime | None = Field(default=None, sa_column=created_timestamp_column())


class MatchCandidateEvidence(SQLModel, table=True):
    __tablename__: ClassVar[str] = "match_candidate_evidence"  # pyright: ignore[reportIncompatibleVariableOverride]

    id: int | None = Field(default=None, sa_column=identity_column())
    brokerage_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    match_candidate_evaluation_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    evidence_side: str = Field(max_length=20)
    field_name: str | None = Field(default=None, max_length=100)
    evidence_type: str = Field(max_length=20)
    interaction_id: int | None = Field(default=None, sa_column=Column(BigInteger))
    quote_text: str | None = Field(default=None, sa_column=Column(Text))
    quote_start_offset: int | None = Field(default=None, sa_column=Column(Integer))
    quote_end_offset: int | None = Field(default=None, sa_column=Column(Integer))
    note: str | None = Field(default=None, sa_column=Column(Text))
    created_at: datetime | None = Field(default=None, sa_column=created_timestamp_column())
