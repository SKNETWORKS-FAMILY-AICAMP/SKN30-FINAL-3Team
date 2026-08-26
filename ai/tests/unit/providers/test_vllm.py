from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from openai import AsyncOpenAI

from brokerage_ai.core.errors import (
    ProviderConfigurationError,
    ProviderOutputInvalidError,
    ProviderResponseError,
)
from brokerage_ai.core.types import ProviderKind
from brokerage_ai.providers.vllm import VllmAdapter
from conftest import Answer, embedding_request, generation_request


@pytest.mark.asyncio
async def test_chat_completions_uses_pydantic_response_format() -> None:
    parse = AsyncMock(
        return_value=SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(parsed=Answer(value="ok"), refusal=None))
            ],
            usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2, total_tokens=5),
            model="served-model",
            id="chatcmpl_123",
        )
    )
    llm_client = cast(
        AsyncOpenAI,
        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=parse))),
    )
    adapter = VllmAdapter(llm_client=llm_client, embedding_client=None)

    result = await adapter.generate_structured(generation_request(ProviderKind.VLLM), Answer)

    assert result.output.value == "ok"
    assert result.diagnostics.request_id == "chatcmpl_123"
    await_args = parse.await_args
    assert await_args is not None
    assert await_args.kwargs["response_format"] is Answer
    assert await_args.kwargs["max_tokens"] == 64


@pytest.mark.asyncio
async def test_missing_llm_endpoint_is_explicit() -> None:
    adapter = VllmAdapter(llm_client=None, embedding_client=None)

    with pytest.raises(ProviderConfigurationError, match="LLM endpoint"):
        await adapter.generate_structured(generation_request(ProviderKind.VLLM), Answer)


def _parsed_response(parsed: object) -> AsyncMock:
    return AsyncMock(
        return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed, refusal=None))],
            usage=None,
            model="served-model",
            id="chatcmpl_123",
        )
    )


@pytest.mark.asyncio
async def test_missing_parsed_output_is_retryable() -> None:
    """본문을 못 읽은 것은 다시 부르면 될 수 있다. 잘린 응답이 여기로 온다."""
    client = cast(
        AsyncOpenAI,
        SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(parse=_parsed_response(None)))
        ),
    )

    with pytest.raises(ProviderOutputInvalidError) as caught:
        await VllmAdapter(llm_client=client, embedding_client=None).generate_structured(
            generation_request(ProviderKind.VLLM), Answer
        )

    assert caught.value.retryable is True


@pytest.mark.asyncio
async def test_wrong_schema_type_is_not_retryable() -> None:
    """선언한 schema 와 다른 타입은 다시 불러도 같다."""
    client = cast(
        AsyncOpenAI,
        SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(parse=_parsed_response(SimpleNamespace(value="ok")))
            )
        ),
    )

    with pytest.raises(ProviderResponseError) as caught:
        await VllmAdapter(llm_client=client, embedding_client=None).generate_structured(
            generation_request(ProviderKind.VLLM), Answer
        )

    assert caught.value.retryable is False


@pytest.mark.asyncio
async def test_embedding_client_is_independent_from_llm_client() -> None:
    create = AsyncMock(
        return_value=SimpleNamespace(
            data=[
                SimpleNamespace(index=0, embedding=[1, 2]),
                SimpleNamespace(index=1, embedding=[3, 4]),
            ],
            model="embedding-model",
            usage=SimpleNamespace(prompt_tokens=2, total_tokens=2),
        )
    )
    embedding_client = cast(
        AsyncOpenAI,
        SimpleNamespace(embeddings=SimpleNamespace(create=create)),
    )
    adapter = VllmAdapter(llm_client=None, embedding_client=embedding_client)

    result = await adapter.embed(embedding_request(ProviderKind.VLLM))

    assert result.vectors == ((1.0, 2.0), (3.0, 4.0))
    create.assert_awaited_once()
