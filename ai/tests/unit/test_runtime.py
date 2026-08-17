from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from openai import AsyncOpenAI

from brokerage_ai.core.config import AiProfile, bind_ai_config
from brokerage_ai.core.types import ProviderKind
from brokerage_ai.runtime import ClientFactory, create_ai_runtime


class FakeClient:
    def __init__(self, options: dict[str, Any]) -> None:
        self.options = options
        self.close = AsyncMock()


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
            "AI_VLLM_LLM_BASE_URL": "http://localhost:8000/v1",
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
