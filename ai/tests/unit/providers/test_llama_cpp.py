from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from httpx2 import Request, Response
from openai import APIStatusError, APITimeoutError, AsyncOpenAI

from brokerage_ai.core.errors import (
    ProviderOutputInvalidError,
    ProviderRefusalError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from brokerage_ai.core.types import ModelRoute, ProviderKind, StructuredGenerationRequest
from brokerage_ai.providers.llama_cpp import LlamaCppAdapter
from brokerage_ai.providers.repair import generate_with_repair
from conftest import Answer, generation_request


def _request() -> StructuredGenerationRequest:
    return generation_request(ProviderKind.VLLM).model_copy(
        update={
            "route": ModelRoute(
                provider=ProviderKind.LLAMA_CPP,
                model="test-model",
                endpoint_alias="general-dev-gpu",
            )
        }
    )


def _response(content: str, *, choices: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        choices=(
            [SimpleNamespace(message=SimpleNamespace(content=content, refusal=None))]
            if choices
            else []
        ),
        usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2, total_tokens=5),
        model="served-gguf",
        id="chatcmpl_llama",
    )


@pytest.mark.asyncio
async def test_llama_cpp_sends_json_schema_and_locally_validates_output() -> None:
    create = AsyncMock(return_value=_response('{"value":"ok"}'))
    client = cast(
        AsyncOpenAI,
        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
    )

    result = await LlamaCppAdapter(client).generate_structured(_request(), Answer)

    assert result.output == Answer(value="ok")
    assert result.diagnostics.provider is ProviderKind.LLAMA_CPP
    assert result.diagnostics.model == "served-gguf"
    assert result.diagnostics.request_id == "chatcmpl_llama"
    await_args = create.await_args
    assert await_args is not None
    assert await_args.kwargs["response_format"] == {
        "type": "json_schema",
        "schema": Answer.model_json_schema(),
    }
    assert await_args.kwargs["max_tokens"] == 64


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["", "not-json", "{}"])
async def test_llama_cpp_invalid_output_is_retryable(content: str) -> None:
    create = AsyncMock(return_value=_response(content))
    client = cast(
        AsyncOpenAI,
        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
    )

    with pytest.raises(ProviderOutputInvalidError) as caught:
        await LlamaCppAdapter(client).generate_structured(_request(), Answer)

    assert caught.value.retryable is True


@pytest.mark.asyncio
async def test_llama_cpp_invalid_output_uses_existing_repair_limit() -> None:
    create = AsyncMock(return_value=_response("not-json"))
    client = cast(
        AsyncOpenAI,
        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
    )
    adapter = LlamaCppAdapter(client)

    with pytest.raises(ProviderOutputInvalidError):
        await generate_with_repair(
            provider=adapter,
            request=_request(),
            output_schema=Answer,
            finalize=lambda produced: produced.output,
        )

    assert create.await_count == 3


@pytest.mark.asyncio
async def test_llama_cpp_empty_choices_is_a_non_retryable_response_error() -> None:
    create = AsyncMock(return_value=_response("", choices=False))
    client = cast(
        AsyncOpenAI,
        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
    )

    with pytest.raises(ProviderResponseError) as caught:
        await LlamaCppAdapter(client).generate_structured(_request(), Answer)

    assert caught.value.retryable is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        SimpleNamespace(),
        SimpleNamespace(choices=[SimpleNamespace()]),
        SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace())]),
    ],
)
async def test_llama_cpp_malformed_response_structure_is_rejected(response: object) -> None:
    create = AsyncMock(return_value=response)
    client = cast(
        AsyncOpenAI,
        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
    )

    with pytest.raises(ProviderResponseError):
        await LlamaCppAdapter(client).generate_structured(_request(), Answer)


@pytest.mark.asyncio
async def test_llama_cpp_sdk_timeout_uses_shared_error_translation() -> None:
    create = AsyncMock(side_effect=APITimeoutError(request=cast(Any, object())))
    client = cast(
        AsyncOpenAI,
        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
    )

    with pytest.raises(ProviderTimeoutError):
        await LlamaCppAdapter(client).generate_structured(_request(), Answer)


@pytest.mark.asyncio
async def test_llama_cpp_authentication_status_uses_shared_error_translation() -> None:
    response = Response(401, request=Request("POST", "https://gpu.internal/v1/chat/completions"))
    create = AsyncMock(
        side_effect=APIStatusError("sensitive provider detail", response=response, body=None)
    )
    client = cast(
        AsyncOpenAI,
        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
    )

    with pytest.raises(ProviderRefusalError) as caught:
        await LlamaCppAdapter(client).generate_structured(_request(), Answer)

    assert "sensitive provider detail" not in str(caught.value)
