from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from openai import APITimeoutError, AsyncOpenAI

from brokerage_ai.core.errors import ProviderResponseError, ProviderTimeoutError
from brokerage_ai.core.types import ProviderKind
from brokerage_ai.providers.openai import OpenAIAdapter
from conftest import Answer, embedding_request, generation_request


@pytest.mark.asyncio
async def test_structured_response_and_diagnostics_are_normalized() -> None:
    parse = AsyncMock(
        return_value=SimpleNamespace(
            output_parsed=Answer(value="ok"),
            output=[],
            usage=SimpleNamespace(input_tokens=4, output_tokens=2, total_tokens=6),
            model="resolved-model",
            id="resp_123",
        )
    )
    client = cast(AsyncOpenAI, SimpleNamespace(responses=SimpleNamespace(parse=parse)))

    result = await OpenAIAdapter(client).generate_structured(
        generation_request(ProviderKind.OPENAI), Answer
    )

    assert result.output == Answer(value="ok")
    assert result.diagnostics.provider is ProviderKind.OPENAI
    assert result.diagnostics.model == "resolved-model"
    assert result.diagnostics.request_id == "resp_123"
    assert result.diagnostics.usage is not None
    assert result.diagnostics.usage.total_tokens == 6
    parse.assert_awaited_once()
    await_args = parse.await_args
    assert await_args is not None
    call = await_args.kwargs
    assert call["text_format"] is Answer
    assert call["store"] is False
    assert call["max_output_tokens"] == 64


@pytest.mark.asyncio
async def test_embeddings_preserve_input_order() -> None:
    create = AsyncMock(
        return_value=SimpleNamespace(
            data=[
                SimpleNamespace(index=1, embedding=[3, 4]),
                SimpleNamespace(index=0, embedding=[1, 2]),
            ],
            model="embedding-model",
            usage=SimpleNamespace(prompt_tokens=2, total_tokens=2),
        )
    )
    client = cast(AsyncOpenAI, SimpleNamespace(embeddings=SimpleNamespace(create=create)))

    result = await OpenAIAdapter(client).embed(embedding_request(ProviderKind.OPENAI))

    assert result.vectors == ((1.0, 2.0), (3.0, 4.0))
    await_args = create.await_args
    assert await_args is not None
    assert await_args.kwargs["input"] == ["first", "second"]


@pytest.mark.asyncio
async def test_invalid_embedding_indices_are_rejected() -> None:
    create = AsyncMock(
        return_value=SimpleNamespace(
            data=[SimpleNamespace(index=0, embedding=[1, 2])],
            model="embedding-model",
            usage=SimpleNamespace(prompt_tokens=2, total_tokens=2),
        )
    )
    client = cast(AsyncOpenAI, SimpleNamespace(embeddings=SimpleNamespace(create=create)))

    with pytest.raises(ProviderResponseError):
        await OpenAIAdapter(client).embed(embedding_request(ProviderKind.OPENAI))


@pytest.mark.asyncio
async def test_sdk_timeout_is_mapped_without_original_message() -> None:
    sdk_error = APITimeoutError(request=cast(Any, object()))
    parse = AsyncMock(side_effect=sdk_error)
    client = cast(AsyncOpenAI, SimpleNamespace(responses=SimpleNamespace(parse=parse)))

    with pytest.raises(ProviderTimeoutError) as caught:
        await OpenAIAdapter(client).generate_structured(
            generation_request(ProviderKind.OPENAI), Answer
        )

    assert str(caught.value) == "provider request timed out"
    assert caught.value.__suppress_context__ is True
