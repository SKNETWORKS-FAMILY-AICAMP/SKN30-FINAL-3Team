from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel

from brokerage_ai.core.types import (
    EmbeddingRequest,
    EmbeddingResult,
    ProviderKind,
    StructuredGenerationRequest,
    StructuredGenerationResult,
)

OutputT = TypeVar("OutputT", bound=BaseModel)


class LlmProvider(Protocol):
    @property
    def kind(self) -> ProviderKind: ...

    async def generate_structured(
        self,
        request: StructuredGenerationRequest,
        output_schema: type[OutputT],
    ) -> StructuredGenerationResult[OutputT]: ...


class EmbeddingProvider(Protocol):
    @property
    def kind(self) -> ProviderKind: ...

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult: ...
