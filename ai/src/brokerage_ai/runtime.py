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
    clients_by_endpoint: dict[tuple[str, str, float, bool], AsyncOpenAI] = {}

    def client_for(
        endpoint: OpenAIConfig | ProviderEndpointConfig | SelfHostedLlmEndpointConfig,
        *,
        timeout_seconds: float | None = None,
        stream_transport: bool = False,
    ) -> AsyncOpenAI:
        api_key = (
            endpoint.api_key.get_secret_value() if endpoint.api_key is not None else "not-required"
        )
        timeout = timeout_seconds if timeout_seconds is not None else config.request_timeout_seconds
        key = (str(endpoint.base_url), api_key, timeout, stream_transport)
        client = clients_by_endpoint.get(key)
        if client is None:
            options: dict[str, Any] = {
                "api_key": api_key,
                "base_url": str(endpoint.base_url),
                "timeout": timeout,
                "max_retries": 0,
            }
            if stream_transport:
                # SDK 3.1 supports HTTPX alongside HTTPX2. HTTPX2 leaves nested body
                # iterators pending after SSE [DONE], which breaks Worker loop shutdown.
                options["http_client"] = http_client_factory()
            client = client_factory(**options)
            clients_by_endpoint[key] = client
        return client

    llm_providers: list[LlmProvider] = []
    llm_endpoint_providers: list[tuple[str, LlmProvider]] = []
    embedding_providers: list[EmbeddingProvider] = []
    bedrock_client: httpx.AsyncClient | None = None
    resolved_credential_loader = aws_credential_loader

    if config.openai is not None:
        general_client = client_for(config.openai, timeout_seconds=config.general_timeout_seconds)
        embedding_client = client_for(config.openai)
        openai_adapter = OpenAIAdapter(general_client)
        llm_providers.append(openai_adapter)
        embedding_providers.append(
            openai_adapter
            if general_client is embedding_client
            else OpenAIAdapter(embedding_client)
        )

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
                    timeout=config.general_timeout_seconds,
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
        client = client_for(
            endpoint,
            timeout_seconds=config.general_timeout_seconds,
            stream_transport=endpoint.provider is ProviderKind.VLLM,
        )
        if endpoint.provider is ProviderKind.VLLM:
            provider: LlmProvider = VllmAdapter(
                llm_client=client,
                embedding_client=None,
                stream_timeout_seconds=config.general_timeout_seconds,
                max_in_flight=config.general_vllm_max_in_flight,
            )
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
