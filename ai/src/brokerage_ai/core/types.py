from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProviderKind(StrEnum):
    OPENAI = "openai"
    VLLM = "vllm"


class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class ModelRoute(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: ProviderKind
    model: str = Field(min_length=1)

    @field_validator("model")
    @classmethod
    def model_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("model must not be blank")
        return normalized


class ChatMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: MessageRole
    content: str = Field(min_length=1)

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message content must not be blank")
        return value


class StructuredGenerationRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    route: ModelRoute
    messages: tuple[ChatMessage, ...] = Field(min_length=1)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_output_tokens: int | None = Field(default=None, ge=1)


class EmbeddingRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    route: ModelRoute
    inputs: tuple[str, ...] = Field(min_length=1)
    dimensions: int | None = Field(default=None, ge=1)

    @field_validator("inputs")
    @classmethod
    def inputs_must_not_contain_blanks(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError("embedding inputs must not contain blank values")
        return values


class TokenUsage(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_tokens: int = Field(ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int = Field(ge=0)


class ProviderDiagnostics(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: ProviderKind
    model: str
    request_id: str | None = None
    latency_ms: float = Field(ge=0)
    usage: TokenUsage | None = None


class StructuredGenerationResult[OutputT: BaseModel](BaseModel):
    model_config = ConfigDict(frozen=True)

    output: OutputT
    diagnostics: ProviderDiagnostics


class EmbeddingResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    vectors: tuple[tuple[float, ...], ...]
    diagnostics: ProviderDiagnostics
