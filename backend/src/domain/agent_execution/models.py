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
FAILED_TERMINAL_STATUS = "FAILED_TERMINAL"


class AgentRunAnchorError(RuntimeError):
    """루트 실행에 매물·손님 앵커가 정확히 하나 있어야 한다는 불변식을 어긴 저장 데이터."""


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
