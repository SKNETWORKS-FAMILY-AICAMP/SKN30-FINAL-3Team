from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from openai import APITimeoutError, AsyncOpenAI
from pydantic import BaseModel, Field, ValidationError, model_validator

from brokerage_ai.core.errors import (
    ProviderOutputInvalidError,
    ProviderResponseError,
    ProviderTimeoutError,
    describe_validation_error,
)
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


@pytest.mark.asyncio
async def test_contract_violating_output_is_retryable_and_keeps_its_cause() -> None:
    """모델 출력이 계약을 어긴 것과 설정이 틀린 것을 같은 등급으로 다루지 않는다.

    교차 필드 규칙은 JSON schema 로 표현할 수 없어 모델이 모른 채 어길 수 있다. 다시 부르면
    통과하는 실패이므로 재시도 대상이다. 여기서 영구 실패로 분류하면 Worker 가 첫 시도에
    `FAILED_TERMINAL` 로 끝낸다.
    """

    class Deadline(BaseModel):
        constraints: tuple[str, ...] = ()
        hard_deadline: str | None = None

        @model_validator(mode="after")
        def a_deadline_requires_a_constraint(self) -> "Deadline":
            if self.hard_deadline is not None and not self.constraints:
                raise ValueError("hard_deadline requires at least one timing constraint")
            return self

    with pytest.raises(ValidationError) as raised:
        Deadline(hard_deadline="2028-07-26")
    sdk_error = raised.value

    parse = AsyncMock(side_effect=sdk_error)
    client = cast(AsyncOpenAI, SimpleNamespace(responses=SimpleNamespace(parse=parse)))

    with pytest.raises(ProviderOutputInvalidError) as caught:
        await OpenAIAdapter(client).generate_structured(
            generation_request(ProviderKind.OPENAI), Answer
        )

    assert caught.value.retryable is True
    # 무엇이 어긋났는지 남는다. 원인을 버리면 계측을 새로 붙이기 전에는 진단할 수 없다.
    assert "hard_deadline requires at least one timing constraint" in str(caught.value)
    assert caught.value.__cause__ is sdk_error


@pytest.mark.asyncio
async def test_validation_detail_does_not_carry_model_values() -> None:
    """검증 문구에 모델이 만든 값을 싣지 않는다. 상담 내용이나 개인정보가 섞일 수 있다."""

    class Quote(BaseModel):
        note: str = Field(max_length=5)

    with pytest.raises(ValidationError) as raised:
        Quote(note="김정우 손님 연락처 010-0000-0008")
    detail = describe_validation_error(raised.value)

    assert "note" in detail
    assert "010-0000-0008" not in detail
    assert "김정우" not in detail


@pytest.mark.asyncio
async def test_truncated_response_is_retryable() -> None:
    """잘린 응답은 계약 위반이 아니라 다시 부르면 될 수 있는 실패다."""
    parse = AsyncMock(
        return_value=SimpleNamespace(
            output_parsed=None,
            output=[],
            incomplete_details=SimpleNamespace(reason="max_output_tokens"),
        )
    )
    client = cast(AsyncOpenAI, SimpleNamespace(responses=SimpleNamespace(parse=parse)))

    with pytest.raises(ProviderOutputInvalidError) as caught:
        await OpenAIAdapter(client).generate_structured(
            generation_request(ProviderKind.OPENAI), Answer
        )

    assert caught.value.retryable is True
    assert "max_output_tokens" in str(caught.value)


@pytest.mark.asyncio
async def test_wrong_schema_type_is_not_retryable() -> None:
    """선언한 schema 와 다른 타입은 다시 불러도 같다. 재시도하지 않는다."""
    parse = AsyncMock(
        return_value=SimpleNamespace(output_parsed=SimpleNamespace(value="ok"), output=[])
    )
    client = cast(AsyncOpenAI, SimpleNamespace(responses=SimpleNamespace(parse=parse)))

    with pytest.raises(ProviderResponseError) as caught:
        await OpenAIAdapter(client).generate_structured(
            generation_request(ProviderKind.OPENAI), Answer
        )

    assert caught.value.retryable is False
