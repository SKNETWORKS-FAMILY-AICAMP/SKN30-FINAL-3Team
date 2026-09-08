from datetime import UTC, datetime
from typing import ClassVar
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Column, DateTime, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

ACTIVE_STATUSES = ("ACCEPTED", "RUNNING")
TERMINAL_STATUSES = ("COMPLETED", "FAILED", "CANCELLED", "INTERRUPTED")


def now() -> datetime:
    return datetime.now(UTC)


def timestamp():
    return Column(DateTime(timezone=True), nullable=False)


class Conversation(SQLModel, table=True):
    __tablename__: ClassVar[str] = "chat_conversation"  # pyright: ignore[reportIncompatibleVariableOverride]
    id: UUID = Field(default_factory=uuid4, sa_column=Column(Uuid, primary_key=True))
    brokerage_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    owner_user_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    active_filters: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    state_version: int = 1
    created_at: datetime = Field(default_factory=now, sa_column=timestamp())
    updated_at: datetime = Field(default_factory=now, sa_column=timestamp())


class ChatRequest(SQLModel, table=True):
    __tablename__: ClassVar[str] = "chat_request"  # pyright: ignore[reportIncompatibleVariableOverride]
    id: UUID = Field(default_factory=uuid4, sa_column=Column(Uuid, primary_key=True))
    brokerage_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    conversation_id: UUID
    client_request_id: UUID
    fingerprint: str
    status: str = "ACCEPTED"
    stage: str = "accepted"
    revision: int = 1
    search_filters: dict | None = Field(default=None, sa_column=Column(JSONB))
    diagnostics: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    context_snapshot: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    owner_instance_id: UUID
    heartbeat_at: datetime = Field(default_factory=now, sa_column=timestamp())
    deadline_at: datetime = Field(sa_column=timestamp())
    created_at: datetime = Field(default_factory=now, sa_column=timestamp())
    started_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    completed_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    failure_code: str | None = None


class Message(SQLModel, table=True):
    __tablename__: ClassVar[str] = "chat_message"  # pyright: ignore[reportIncompatibleVariableOverride]
    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True))
    brokerage_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    conversation_id: UUID
    request_id: UUID
    sequence_no: int
    role: str
    content: str = Field(sa_column=Column(Text, nullable=False))
    payload_version: int = 1
    result_payload: dict | None = Field(default=None, sa_column=Column(JSONB))
    created_at: datetime = Field(default_factory=now, sa_column=timestamp())
