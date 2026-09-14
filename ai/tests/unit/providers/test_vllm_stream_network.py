"""A loopback TCP stream catches iterator cleanup errors hidden by MockTransport."""

import asyncio
import json

from brokerage_ai.core.config import bind_ai_config
from brokerage_ai.core.types import ProviderKind
from brokerage_ai.runtime import create_ai_runtime
from conftest import Answer, generation_request


def test_runtime_stream_finalizes_tcp_body_iterators_without_loop_errors():
    loop = asyncio.new_event_loop()
    errors = []
    loop.set_exception_handler(lambda _loop, context: errors.append(context["message"]))

    async def run():
        server_done = asyncio.Event()

        async def respond(reader, writer):
            try:
                await reader.readuntil(b"\r\n\r\n")
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
                    b"Transfer-Encoding: chunked\r\nConnection: close\r\n\r\n"
                )
                for content, reason in [('{"value":"ok"}', None), (None, "stop")]:
                    chunk = {
                        "id": "test",
                        "object": "chat.completion.chunk",
                        "created": 1,
                        "model": "test",
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": content},
                                "finish_reason": reason,
                            }
                        ],
                    }
                    payload = f"data: {json.dumps(chunk)}\n\n".encode()
                    writer.write(f"{len(payload):x}\r\n".encode() + payload + b"\r\n")
                    await writer.drain()
                    await asyncio.sleep(0)
                payload = b"data: [DONE]\n\n"
                writer.write(f"{len(payload):x}\r\n".encode() + payload + b"\r\n0\r\n\r\n")
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()
                server_done.set()

        server = await asyncio.start_server(respond, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        config = bind_ai_config(
            {
                "AI_GENERAL_PROVIDER": "vllm",
                "AI_GENERAL_MODEL": "Qwen/Qwen3.8-27B-FP8",
                "AI_GENERAL_BASE_URL": f"http://127.0.0.1:{port}/v1",
                "AI_GENERAL_API_KEY": "test-only",
            },
            "test",
        )
        try:
            async with create_ai_runtime(config) as runtime:
                adapter = runtime.providers.get_llm(
                    ProviderKind.VLLM, config.general.route.endpoint_alias
                )
                result = await adapter.generate_structured(
                    generation_request(ProviderKind.VLLM), Answer
                )
                assert result.output.value == "ok"
                await asyncio.wait_for(server_done.wait(), timeout=2)
        finally:
            server.close()
            await server.wait_closed()

    try:
        loop.run_until_complete(asyncio.wait_for(run(), timeout=5))
        loop.run_until_complete(loop.shutdown_asyncgens())
    finally:
        loop.close()
    assert errors == []
