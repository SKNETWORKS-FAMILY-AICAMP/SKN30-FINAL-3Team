"""F4's framework-neutral interpretation and read capability contract."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date, datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from brokerage_ai.core.types import ProviderDiagnostics

ChatTool = Literal[
    "properties",
    "buyers",
    "agenda",
    "open_f2",
    "help",
    "clarification",
    "unsupported",
    "open_result",
]
AgendaCategory = Literal[
    "TENANCY_EXPIRY",
    "CLIENT_TENANCY_EXPIRY",
    "REQUEST_EXPIRY",
    "MOVE_IN",
    "LISTING_RECONTACT",
    "CLIENT_RECONTACT",
    "LISTING_REVALIDATION",
    "CALENDAR",
]


class ChatModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ChatFilters(ChatModel):
    # Source expressions are interpreted and normalized by Backend, never by the model.
    complex_name: str | None = Field(default=None, max_length=100)
    transaction_type: Literal["SALE", "JEONSE", "RENT"] | None = None
    status: str | None = Field(default=None, max_length=40)
    price_expression: str | None = Field(default=None, max_length=100)
    deposit_expression: str | None = Field(default=None, max_length=100)
    rent_expression: str | None = Field(default=None, max_length=100)
    area_expression: str | None = Field(default=None, max_length=100)
    area_basis: Literal["exclusive", "supply"] | None = None
    date_expression: str | None = Field(default=None, max_length=100)
    categories: tuple[AgendaCategory, ...] = ()
    sort: Literal["recent", "price_asc", "price_desc", "date_asc"] | None = None


class ChatIntent(ChatModel):
    tool: ChatTool
    mode: Literal["replace", "refine"] = "replace"
    filters: ChatFilters = Field(default_factory=ChatFilters)
    reference_ordinal: int | None = Field(default=None, ge=1, le=10)
    clarification_code: (
        Literal["area_basis", "missing_context", "ambiguous_condition", "unsupported_condition"]
        | None
    ) = None


class ChatAction(ChatModel):
    type: Literal["open_f2", "open_property", "open_buyer", "open_calendar"]
    target_id: int | None = None
    label: str


class ChatField(ChatModel):
    label: str
    value: str


class ChatResultItem(ChatModel):
    id: str
    title: str
    subtitle: str = ""
    fields: tuple[ChatField, ...] = ()
    action: ChatAction | None = None


class ChatResult(ChatModel):
    kind: Literal[
        "properties", "buyers", "agenda", "help", "clarification", "unsupported", "action"
    ]
    text: str
    filters: dict[str, Any] = Field(default_factory=dict)
    items: tuple[ChatResultItem, ...] = Field(default=(), max_length=10)
    total: int = Field(default=0, ge=0)
    offset: int = Field(default=0, ge=0)
    limit: Literal[10] = 10
    as_of: datetime
    actions: tuple[ChatAction, ...] = ()


class CompletedTurn(ChatModel):
    question: str = Field(max_length=2000)
    # A server-built summary of result kind/count, never a free-form answer or full rows.
    answer_summary: str = Field(max_length=200)


class ResultReference(ChatModel):
    kind: Literal["properties", "buyers", "agenda"]
    items: tuple[ChatResultItem, ...] = Field(max_length=10)


class ChatInput(ChatModel):
    question: str = Field(min_length=1, max_length=2000)
    active_filters: dict[str, Any] = Field(default_factory=dict)
    history: tuple[CompletedTurn, ...] = Field(default=(), max_length=2)
    reference: ResultReference | None = None
    as_of: date


class ChatExecution(ChatModel):
    result: ChatResult
    intent: ChatIntent
    diagnostics: ProviderDiagnostics | None = None
    model_calls: int = Field(default=0, ge=0, le=3)
    prompt_version: str = "chatbot-prompt:v2"
    workflow_version: str = "chatbot-workflow:v4"


class ChatReadPort(Protocol):
    async def execute(self, intent: ChatIntent, request: ChatInput) -> ChatResult:
        """Revalidate scope and source expressions and perform one bounded read/action."""
        ...


ProgressCallback = Callable[[Literal["interpreting", "searching"]], Awaitable[None]]
