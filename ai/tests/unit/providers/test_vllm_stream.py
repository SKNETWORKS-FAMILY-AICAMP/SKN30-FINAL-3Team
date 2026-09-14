"""Exercise the real SDK stream parser and transport cleanup without a live provider."""

import asyncio
import json

import httpx2 as httpx
import pytest
from openai import AsyncOpenAI

from brokerage_ai.core.errors import (
    ProviderOutputInvalidError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from brokerage_ai.core.types import ProviderKind
from brokerage_ai.providers.vllm import VllmAdapter
from conftest import Answer, generation_request


class Reply(httpx.AsyncByteStream):
    def __init__(self, *, body='{"value":"ok"}', finish=True, gate=None, trickle=False, error=None):
        self.body, self.finish, self.gate, self.trickle = body, finish, gate, trickle
        self.error = error
        self.closed = asyncio.Event()

    async def __aiter__(self):
        if self.gate is not None:
            await self.gate.wait()
        if self.error is not None:
            raise self.error
        while self.trickle:
            yield b": heartbeat\n\n"
            await asyncio.sleep(0.005)
        for content, finish in [(self.body, None), (None, "stop")][: 2 if self.finish else 1]:
            chunk = {
                "id": "completion-test",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "served-model",
                "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": finish}],
            }
            yield f"data: {json.dumps(chunk)}\n\n".encode()
        yield (
            b'data: {"id":"completion-test","object":"chat.completion.chunk",'
            b'"created":1,"model":"served-model","choices":[],"usage":'
            b'{"prompt_tokens":3,"completion_tokens":2,"total_tokens":5}}\n\n'
        )
        yield b"data: [DONE]\n\n"

    async def aclose(self):
        self.closed.set()


def make_adapter(replies, *, timeout: float = 2):
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(
            200, stream=replies[len(sent) - 1], headers={"content-type": "text/event-stream"}
        )

    client = AsyncOpenAI(
        api_key="test-key",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    adapter = VllmAdapter(
        llm_client=client, embedding_client=None, stream_timeout_seconds=timeout, max_in_flight=1
    )
    return adapter, client, sent


async def generate(adapter):
    return await adapter.generate_structured(generation_request(ProviderKind.VLLM), Answer)


@pytest.mark.asyncio
async def test_stream_validates_complete_output_keeps_usage_and_request_contract():
    reply = Reply()
    adapter, client, sent = make_adapter([reply])
    async with client:
        result = await generate(adapter)
    assert result.output.value == "ok"
    assert result.diagnostics.usage.total_tokens == 5
    assert result.diagnostics.request_id == "completion-test"
    assert reply.closed.is_set()
    assert sent[0]["stream"] is True
    assert sent[0]["stream_options"] == {"include_usage": True}
    assert sent[0]["response_format"]["json_schema"]["strict"] is True
    assert sent[0]["chat_template_kwargs"] == {"enable_thinking": False}
    assert sent[0]["max_tokens"] == 64


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [Reply(body='{"unexpected":2}'), Reply(finish=False)])
async def test_invalid_or_unfinished_stream_never_returns_a_result(reply):
    adapter, client, _ = make_adapter([reply])
    async with client:
        with pytest.raises(ProviderOutputInvalidError):
            await generate(adapter)
    assert reply.closed.is_set()


@pytest.mark.asyncio
async def test_trickling_stream_still_hits_absolute_timeout_and_releases_slot():
    replies = [Reply(trickle=True), Reply()]
    adapter, client, sent = make_adapter(replies, timeout=0.08)
    async with client:
        with pytest.raises(ProviderTimeoutError):
            await generate(adapter)
        assert replies[0].closed.is_set()
        assert (await generate(adapter)).output.value == "ok"
    assert len(sent) == 2


@pytest.mark.asyncio
async def test_cancel_active_stream_closes_connection_and_starts_queued_request():
    replies = [Reply(gate=asyncio.Event()), Reply()]
    adapter, client, sent = make_adapter(replies)
    async with client:
        first = asyncio.create_task(generate(adapter))
        async with asyncio.timeout(1):
            while not sent:
                await asyncio.sleep(0)
        second = asyncio.create_task(generate(adapter))
        await asyncio.sleep(0.01)
        assert len(sent) == 1
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert (await second).output.value == "ok"
    assert all(reply.closed.is_set() for reply in replies)


@pytest.mark.asyncio
async def test_cancel_waiter_does_not_open_connection_or_consume_permit():
    gate = asyncio.Event()
    replies = [Reply(gate=gate), Reply()]
    adapter, client, sent = make_adapter(replies)
    async with client:
        first = asyncio.create_task(generate(adapter))
        async with asyncio.timeout(1):
            while not sent:
                await asyncio.sleep(0)
        waiter = asyncio.create_task(generate(adapter))
        await asyncio.sleep(0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert len(sent) == 1
        gate.set()
        await first
        assert (await generate(adapter)).output.value == "ok"
    assert len(sent) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error, expected",
    [
        (httpx.ReadTimeout("sensitive-response-sentinel"), ProviderTimeoutError),
        (httpx.ReadError("sensitive-response-sentinel"), ProviderUnavailableError),
    ],
)
async def test_stream_transport_failure_preserves_retry_class_and_sanitizes(error, expected):
    reply = Reply(error=error)
    adapter, client, sent = make_adapter([reply])
    async with client:
        with pytest.raises(expected) as caught:
            await generate(adapter)
    assert reply.closed.is_set()
    assert caught.value.retryable is True
    assert "sensitive" not in str(caught.value)
    assert len(sent) == 1  # no hidden SDK retry
