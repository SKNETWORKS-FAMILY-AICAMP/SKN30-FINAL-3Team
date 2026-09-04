import json
from typing import Any, cast
from unittest.mock import AsyncMock

import httpx
import pytest
from botocore.credentials import Credentials, ReadOnlyCredentials
from openai import AsyncOpenAI

from brokerage_ai.core.config import AiProfile, bind_ai_config
from brokerage_ai.core.types import ProviderKind
from brokerage_ai.runtime import ClientFactory, HttpClientFactory, create_ai_runtime


class FakeClient:
    def __init__(self, options: dict[str, Any]) -> None:
        self.options = options
        self.close = AsyncMock()


class FakeHttpClient:
    def __init__(self, options: dict[str, Any]) -> None:
        self.options = options
        self.aclose = AsyncMock()


@pytest.mark.asyncio
async def test_runtime_reuses_client_for_equal_vllm_endpoints_and_closes_once() -> None:
    created: list[FakeClient] = []

    def client_factory(**options: Any) -> AsyncOpenAI:
        client = FakeClient(options)
        created.append(client)
        return cast(AsyncOpenAI, client)

    config = bind_ai_config(
        {
            "AI_REQUEST_TIMEOUT_SECONDS": "12.5",
            "AI_F2_PROVIDER_STATUS": "active",
            "AI_VLLM_SLLM_BASE_URL": "http://localhost:8000/v1",
            "AI_VLLM_STT_BASE_URL": "http://localhost:8002/v1",
            "AI_VLLM_EMBEDDING_BASE_URL": "http://localhost:8000/v1",
        },
        AiProfile.LOCAL,
    )

    runtime = create_ai_runtime(config, client_factory=cast(ClientFactory, client_factory))

    assert len(created) == 1
    assert created[0].options["max_retries"] == 0
    assert created[0].options["timeout"] == 12.5
    assert runtime.providers.get_llm(ProviderKind.VLLM) is runtime.providers.get_embedding(
        ProviderKind.VLLM
    )

    await runtime.close()
    await runtime.close()

    created[0].close.assert_awaited_once()


@pytest.mark.asyncio
async def test_runtime_context_manager_closes_clients() -> None:
    created: list[FakeClient] = []

    def client_factory(**options: Any) -> AsyncOpenAI:
        client = FakeClient(options)
        created.append(client)
        return cast(AsyncOpenAI, client)

    config = bind_ai_config({"AI_OPENAI_API_KEY": "test-key"}, AiProfile.TEST)

    async with create_ai_runtime(
        config, client_factory=cast(ClientFactory, client_factory)
    ) as runtime:
        assert runtime.providers.get_llm(ProviderKind.OPENAI)

    created[0].close.assert_awaited_once()


@pytest.mark.asyncio
async def test_runtime_keeps_default_and_aliased_vllm_routes_separate() -> None:
    created: list[FakeClient] = []

    def client_factory(**options: Any) -> AsyncOpenAI:
        client = FakeClient(options)
        created.append(client)
        return cast(AsyncOpenAI, client)

    address_book = [
        {
            "alias": "general-dev-gpu",
            "provider": "vllm",
            "base_url": "https://pod.example/v1",
            "api_key_env": "AI_GENERAL_DEV_GPU_API_KEY",
        }
    ]
    config = bind_ai_config(
        {
            "AI_F2_PROVIDER_STATUS": "active",
            "AI_VLLM_SLLM_BASE_URL": "https://pod.example/v1",
            "AI_VLLM_SLLM_API_KEY": "shared-key",
            "AI_VLLM_STT_BASE_URL": "https://pod.example/stt/v1",
            "AI_LLM_ENDPOINTS": json.dumps(address_book),
            "AI_GENERAL_DEV_GPU_API_KEY": "shared-key",
        },
        AiProfile.DEV,
    )

    runtime = create_ai_runtime(config, client_factory=cast(ClientFactory, client_factory))

    default = runtime.providers.get_llm(ProviderKind.VLLM)
    aliased = runtime.providers.get_llm(ProviderKind.VLLM, "general-dev-gpu")
    assert default is not aliased
    assert len(created) == 1
    await runtime.close()


@pytest.mark.asyncio
async def test_runtime_reuses_and_closes_bedrock_http_client_once() -> None:
    created: list[FakeHttpClient] = []

    def http_client_factory(**options: Any) -> httpx.AsyncClient:
        client = FakeHttpClient(options)
        created.append(client)
        return cast(httpx.AsyncClient, client)

    def credentials() -> ReadOnlyCredentials:
        return Credentials("access", "secret", "token").get_frozen_credentials()

    config = bind_ai_config(
        {
            "AI_REQUEST_TIMEOUT_SECONDS": "15",
            "AI_LLM_ENDPOINTS": json.dumps(
                [
                    {
                        "alias": "general-dev-bedrock",
                        "provider": "bedrock",
                        "aws_region": "ap-northeast-2",
                    },
                    {
                        "alias": "general-staging-bedrock",
                        "provider": "bedrock",
                        "aws_region": "us-east-1",
                    },
                ]
            ),
        },
        AiProfile.DEV,
    )

    runtime = create_ai_runtime(
        config,
        http_client_factory=cast(HttpClientFactory, http_client_factory),
        aws_credential_loader=credentials,
    )

    assert len(created) == 1
    assert created[0].options == {"timeout": 15.0, "follow_redirects": False}
    dev = runtime.providers.get_llm(ProviderKind.BEDROCK, "general-dev-bedrock")
    staging = runtime.providers.get_llm(ProviderKind.BEDROCK, "general-staging-bedrock")
    assert dev is not staging

    await runtime.close()
    await runtime.close()

    created[0].aclose.assert_awaited_once()
