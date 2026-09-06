from __future__ import annotations

from collections.abc import Callable
from types import TracebackType
from typing import Any

from openai import AsyncOpenAI

from brokerage_ai.core.config import AiConfig, OpenAIConfig, ProviderEndpointConfig
from brokerage_ai.core.errors import ProviderConfigurationError
from brokerage_ai.providers.openai import OpenAIAdapter
from brokerage_ai.providers.ports import EmbeddingProvider, LlmProvider
from brokerage_ai.providers.registry import ProviderRegistry
from brokerage_ai.providers.vllm import VllmAdapter

ClientFactory = Callable[..., AsyncOpenAI]


def _vllm_llm_endpoint(config: AiConfig) -> ProviderEndpointConfig | None:
    """vLLM LLM adapter 가 쓸 endpoint 하나.

    `ProviderRegistry` 는 provider 종류당 adapter 를 하나만 받는다. vLLM 서버 하나는 모델
    하나를 서빙하므로, F2 의 sLLM 과 F3 의 모델을 동시에 로컬 vLLM 으로 돌리려면 서로 다른
    endpoint 두 개가 필요한데 지금 구조는 그것을 담지 못한다. 조용히 한쪽을 고르면 F2 요청이
    F3 모델로 가므로 둘 다 설정된 상태를 구성 오류로 막는다.
    """
    sllm, f3 = config.vllm.sllm, config.vllm.f3
    if sllm is not None and f3 is not None:
        raise ProviderConfigurationError(
            "AI_VLLM_SLLM_BASE_URL and AI_VLLM_F3_BASE_URL cannot both be configured"
        )
    return f3 if f3 is not None else sllm


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

    vllm_llm_endpoint = _vllm_llm_endpoint(config)
    vllm_llm_client = client_for(vllm_llm_endpoint) if vllm_llm_endpoint is not None else None
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
