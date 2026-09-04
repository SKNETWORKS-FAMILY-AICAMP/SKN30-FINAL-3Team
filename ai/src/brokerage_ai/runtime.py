from __future__ import annotations

from collections.abc import Callable
from types import TracebackType
from typing import Any

import httpx
from openai import AsyncOpenAI

from brokerage_ai.core.config import (
    AiConfig,
    BedrockLlmEndpointConfig,
    OpenAIConfig,
    ProviderEndpointConfig,
    SelfHostedLlmEndpointConfig,
)
from brokerage_ai.core.types import ProviderKind
from brokerage_ai.providers.bedrock import (
    AwsCredentialLoader,
    BedrockAdapter,
    create_default_aws_credential_loader,
)
from brokerage_ai.providers.llama_cpp import LlamaCppAdapter
from brokerage_ai.providers.openai import OpenAIAdapter
from brokerage_ai.providers.ports import EmbeddingProvider, LlmProvider
from brokerage_ai.providers.registry import ProviderRegistry
from brokerage_ai.providers.vllm import VllmAdapter

ClientFactory = Callable[..., AsyncOpenAI]
HttpClientFactory = Callable[..., httpx.AsyncClient]


class AiRuntime:
    def __init__(
        self,
        *,
        providers: ProviderRegistry,
        clients: tuple[AsyncOpenAI, ...],
        http_clients: tuple[httpx.AsyncClient, ...] = (),
    ) -> None:
        self.providers = providers
        self._clients = clients
        self._http_clients = http_clients
        self._closed = False

    async def close(self) -> None:
        if self._closed:
            return
        for client in self._clients:
            await client.close()
        for client in self._http_clients:
            await client.aclose()
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
    http_client_factory: HttpClientFactory = httpx.AsyncClient,
    aws_credential_loader: AwsCredentialLoader | None = None,
) -> AiRuntime:
    clients_by_endpoint: dict[tuple[str, str], AsyncOpenAI] = {}

    def client_for(
        endpoint: OpenAIConfig | ProviderEndpointConfig | SelfHostedLlmEndpointConfig,
    ) -> AsyncOpenAI:
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
    llm_endpoint_providers: list[tuple[str, LlmProvider]] = []
    embedding_providers: list[EmbeddingProvider] = []
    bedrock_client: httpx.AsyncClient | None = None
    resolved_credential_loader = aws_credential_loader

    if config.openai is not None:
        openai_adapter = OpenAIAdapter(client_for(config.openai))
        llm_providers.append(openai_adapter)
        embedding_providers.append(openai_adapter)

    vllm_llm_client = client_for(config.vllm.sllm) if config.vllm.sllm is not None else None
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

    for endpoint in config.llm_endpoints:
        if isinstance(endpoint, BedrockLlmEndpointConfig):
            if bedrock_client is None:
                bedrock_client = http_client_factory(
                    timeout=config.request_timeout_seconds,
                    follow_redirects=False,
                )
            if resolved_credential_loader is None:
                resolved_credential_loader = create_default_aws_credential_loader()
            llm_endpoint_providers.append(
                (
                    endpoint.alias,
                    BedrockAdapter(
                        bedrock_client,
                        base_url=endpoint.base_url,
                        aws_region=endpoint.aws_region,
                        credential_loader=resolved_credential_loader,
                    ),
                )
            )
            continue
        client = client_for(endpoint)
        if endpoint.provider is ProviderKind.VLLM:
            provider: LlmProvider = VllmAdapter(llm_client=client, embedding_client=None)
        elif endpoint.provider is ProviderKind.LLAMA_CPP:
            provider = LlamaCppAdapter(client)
        else:
            raise AssertionError("validated LLM endpoint provider is unsupported")
        llm_endpoint_providers.append((endpoint.alias, provider))

    return AiRuntime(
        providers=ProviderRegistry(
            llm_providers=llm_providers,
            llm_endpoint_providers=llm_endpoint_providers,
            embedding_providers=embedding_providers,
        ),
        clients=tuple(clients_by_endpoint.values()),
        http_clients=(bedrock_client,) if bedrock_client is not None else (),
    )
