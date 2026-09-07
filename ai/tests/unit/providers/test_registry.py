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


def test_registry_selects_exact_provider_and_endpoint_alias() -> None:
    bedrock = FakeProvider(ProviderKind.BEDROCK)
    other_bedrock = FakeProvider(ProviderKind.BEDROCK)
    default_vllm = FakeProvider(ProviderKind.VLLM)
    aliased_vllm = FakeProvider(ProviderKind.VLLM)
    registry = ProviderRegistry(
        llm_providers=[default_vllm],
        llm_endpoint_providers=[
            ("general-dev-bedrock", bedrock),
            ("general-staging-bedrock", other_bedrock),
            ("general-dev-gpu", aliased_vllm),
        ],
    )

    assert registry.get_llm(ProviderKind.BEDROCK, "general-dev-bedrock") is bedrock
    assert registry.get_llm(ProviderKind.BEDROCK, "general-staging-bedrock") is other_bedrock
    assert registry.get_llm(ProviderKind.VLLM) is default_vllm
    assert registry.get_llm(ProviderKind.VLLM, "general-dev-gpu") is aliased_vllm


def test_registry_never_falls_back_from_unregistered_alias() -> None:
    default_vllm = FakeProvider(ProviderKind.VLLM)
    bedrock = FakeProvider(ProviderKind.BEDROCK)
    registry = ProviderRegistry(
        llm_providers=[default_vllm],
        llm_endpoint_providers=[("general-dev", bedrock)],
    )

    with pytest.raises(ProviderConfigurationError, match="vllm LLM endpoint general-dev"):
        registry.get_llm(ProviderKind.VLLM, "general-dev")
    with pytest.raises(ProviderConfigurationError, match="bedrock LLM provider"):
        registry.get_llm(ProviderKind.BEDROCK)


def test_duplicate_provider_alias_pair_is_rejected() -> None:
    first = FakeProvider(ProviderKind.BEDROCK)
    second = FakeProvider(ProviderKind.BEDROCK)

    with pytest.raises(ProviderConfigurationError, match="duplicate bedrock LLM endpoint"):
        ProviderRegistry(llm_endpoint_providers=[("general-dev", first), ("general-dev", second)])
