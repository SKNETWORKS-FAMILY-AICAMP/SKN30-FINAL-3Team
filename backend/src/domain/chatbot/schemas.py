from datetime import datetime
from typing import Literal
from uuid import UUID

from brokerage_ai.chatbot import ChatResult
from pydantic import BaseModel, ConfigDict, Field


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SubmitQuestion(Input):
    question: str = Field(min_length=1, max_length=2000)
    client_request_id: UUID
    expected_version: int = Field(ge=1)
    reference_message_id: int | None = Field(default=None, ge=1)


class ResetFilters(Input):
    expected_version: int = Field(ge=1)


class MessageView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    request_id: UUID
    sequence_no: int
    role: Literal["user", "assistant"]
    content: str
    result_payload: ChatResult | None
    created_at: datetime


class RequestView(BaseModel):
    id: UUID
    conversation_id: UUID
    status: Literal["ACCEPTED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED", "INTERRUPTED"]
    stage: str
    revision: int
    failure_code: str | None
    search_filters: dict | None = None
    answer: MessageView | None
    created_at: datetime
    completed_at: datetime | None


class ConversationView(BaseModel):
    id: UUID
    state_version: int
    active_filters: dict
    active_request: RequestView | None
    created_at: datetime
    updated_at: datetime


class CurrentConversation(BaseModel):
    conversation: ConversationView | None
    enabled: bool


class HistoryView(BaseModel):
    items: list[MessageView]
    next_cursor: int | None
