from typing import Any

import pytest

from brokerage_ai.core.errors import ProviderConfigurationError
from brokerage_ai.core.types import ProviderKind
from brokerage_ai.providers.registry import ProviderRegistry


class FakeProvider:
    def __init__(self, kind: ProviderKind) -> None:
        self.kind = kind

    async def generate_structured(self, request: Any, output_schema: Any) -> Any:
        return request, output_schema

    async def embed(self, request: Any) -> Any:
        return request


def test_registry_selects_provider_by_kind() -> None:
    openai = FakeProvider(ProviderKind.OPENAI)
    vllm = FakeProvider(ProviderKind.VLLM)
    registry = ProviderRegistry(
        llm_providers=[openai, vllm],
        embedding_providers=[vllm],
    )

    assert registry.get_llm(ProviderKind.OPENAI) is openai
    assert registry.get_embedding(ProviderKind.VLLM) is vllm


def test_unconfigured_capability_fails_explicitly() -> None:
    registry = ProviderRegistry()

    with pytest.raises(ProviderConfigurationError, match="openai LLM provider"):
        registry.get_llm(ProviderKind.OPENAI)


def test_duplicate_provider_is_rejected() -> None:
    provider = FakeProvider(ProviderKind.OPENAI)

    with pytest.raises(ProviderConfigurationError, match="duplicate openai"):
        ProviderRegistry(llm_providers=[provider, provider])
