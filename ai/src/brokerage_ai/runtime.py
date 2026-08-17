from __future__ import annotations

from collections.abc import Callable
from types import TracebackType
from typing import Any

from openai import AsyncOpenAI

from brokerage_ai.core.config import AiConfig, OpenAIConfig, ProviderEndpointConfig
from brokerage_ai.providers.openai import OpenAIAdapter
from brokerage_ai.providers.ports import EmbeddingProvider, LlmProvider
from brokerage_ai.providers.registry import ProviderRegistry
from brokerage_ai.providers.vllm import VllmAdapter

ClientFactory = Callable[..., AsyncOpenAI]


class AiRuntime:
    def __init__(
        self,
        *,
        providers: ProviderRegistry,
        clients: tuple[AsyncOpenAI, ...],
    ) -> None:
        self.providers = providers
        self._clients = clients
        self._closed = False

    async def close(self) -> None:
        if self._closed:
            return
        for client in self._clients:
            await client.close()
        self._closed = True

    async def __aenter__(self) -> AiRuntime:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()


def create_ai_runtime(
    config: AiConfig,
    *,
    client_factory: ClientFactory = AsyncOpenAI,
) -> AiRuntime:
    clients_by_endpoint: dict[tuple[str, str], AsyncOpenAI] = {}

    def client_for(endpoint: OpenAIConfig | ProviderEndpointConfig) -> AsyncOpenAI:
        api_key = (
            endpoint.api_key.get_secret_value() if endpoint.api_key is not None else "not-required"
        )
        key = (str(endpoint.base_url), api_key)
        client = clients_by_endpoint.get(key)
        if client is None:
            options: dict[str, Any] = {
                "api_key": api_key,
                "base_url": str(endpoint.base_url),
                "timeout": config.request_timeout_seconds,
                "max_retries": 0,
            }
            client = client_factory(**options)
            clients_by_endpoint[key] = client
        return client

    llm_providers: list[LlmProvider] = []
    embedding_providers: list[EmbeddingProvider] = []

    if config.openai is not None:
        openai_adapter = OpenAIAdapter(client_for(config.openai))
        llm_providers.append(openai_adapter)
        embedding_providers.append(openai_adapter)

    vllm_llm_client = client_for(config.vllm.llm) if config.vllm.llm is not None else None
    vllm_embedding_client = (
        client_for(config.vllm.embedding) if config.vllm.embedding is not None else None
    )
    if vllm_llm_client is not None or vllm_embedding_client is not None:
        vllm_adapter = VllmAdapter(
            llm_client=vllm_llm_client,
            embedding_client=vllm_embedding_client,
        )
        if vllm_adapter.supports_llm:
            llm_providers.append(vllm_adapter)
        if vllm_adapter.supports_embedding:
            embedding_providers.append(vllm_adapter)

    return AiRuntime(
        providers=ProviderRegistry(
            llm_providers=llm_providers,
            embedding_providers=embedding_providers,
        ),
        clients=tuple(clients_by_endpoint.values()),
    )
