from __future__ import annotations

from collections.abc import Iterable
from typing import TypeVar

from pydantic import BaseModel

from brokerage_ai.core.errors import ProviderConfigurationError
from brokerage_ai.core.types import (
    EmbeddingRequest,
    EmbeddingResult,
    ProviderKind,
    StructuredGenerationRequest,
    StructuredGenerationResult,
)
from brokerage_ai.providers.ports import EmbeddingProvider, LlmProvider

OutputT = TypeVar("OutputT", bound=BaseModel)


class ProviderRegistry:
    def __init__(
        self,
        *,
        llm_providers: Iterable[LlmProvider] = (),
        embedding_providers: Iterable[EmbeddingProvider] = (),
    ) -> None:
        self._llm_providers = self._index_llm(llm_providers)
        self._embedding_providers = self._index_embedding(embedding_providers)

    async def generate_structured(
        self,
        request: StructuredGenerationRequest,
        output_schema: type[OutputT],
    ) -> StructuredGenerationResult[OutputT]:
        provider = self.get_llm(request.route.provider)
        return await provider.generate_structured(request, output_schema)

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        provider = self.get_embedding(request.route.provider)
        return await provider.embed(request)

    def get_llm(self, kind: ProviderKind) -> LlmProvider:
        try:
            return self._llm_providers[kind]
        except KeyError as exc:
            raise ProviderConfigurationError(
                f"{kind.value} LLM provider is not configured"
            ) from exc

    def get_embedding(self, kind: ProviderKind) -> EmbeddingProvider:
        try:
            return self._embedding_providers[kind]
        except KeyError as exc:
            raise ProviderConfigurationError(
                f"{kind.value} embedding provider is not configured"
            ) from exc

    @staticmethod
    def _index_llm(providers: Iterable[LlmProvider]) -> dict[ProviderKind, LlmProvider]:
        indexed: dict[ProviderKind, LlmProvider] = {}
        for provider in providers:
            if provider.kind in indexed:
                raise ProviderConfigurationError(f"duplicate {provider.kind.value} LLM provider")
            indexed[provider.kind] = provider
        return indexed

    @staticmethod
    def _index_embedding(
        providers: Iterable[EmbeddingProvider],
    ) -> dict[ProviderKind, EmbeddingProvider]:
        indexed: dict[ProviderKind, EmbeddingProvider] = {}
        for provider in providers:
            if provider.kind in indexed:
                raise ProviderConfigurationError(
                    f"duplicate {provider.kind.value} embedding provider"
                )
            indexed[provider.kind] = provider
        return indexed
