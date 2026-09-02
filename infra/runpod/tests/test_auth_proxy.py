from __future__ import annotations

import asyncio
import importlib.util
import sys
import unittest
from pathlib import Path

from aiohttp import FormData, web
from aiohttp.test_utils import TestClient, TestServer

RUNPOD_ROOT = Path(__file__).resolve().parents[1]
API_KEY = "q" * 43


def load_proxy():
    path = RUNPOD_ROOT / "scripts" / "auth_proxy.py"
    spec = importlib.util.spec_from_file_location("f2_auth_proxy", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


auth_proxy = load_proxy()


class AuthProxyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.upstream = web.Application()

        async def echo(request: web.Request) -> web.Response:
            self.calls.append((request.method, request.path_qs))
            body = await request.read()
            return web.Response(
                body=body or b"ok", content_type="application/octet-stream"
            )

        self.upstream_handler = echo

        async def dispatch(request: web.Request) -> web.StreamResponse:
            return await self.upstream_handler(request)

        self.upstream.router.add_route("*", "/{path:.*}", dispatch)
        self.upstream_server = TestServer(self.upstream)
        await self.upstream_server.start_server()
        assert self.upstream_server.port is not None
        application = auth_proxy.create_application(
            upstream_port=self.upstream_server.port,
            api_key=API_KEY,
            service="sllm",
        )
        self.client = TestClient(TestServer(application))
        await self.client.start_server()

    async def asyncTearDown(self) -> None:
        await self.client.close()
        await self.upstream_server.close()

    async def test_missing_wrong_and_duplicate_authorization_are_rejected(self) -> None:
        for headers in (
            None,
            {"Authorization": "Bearer wrong-key"},
            [
                ("Authorization", f"Bearer {API_KEY}"),
                ("Authorization", f"Bearer {API_KEY}"),
            ],
        ):
            response = await self.client.get("/v1/models", headers=headers)
            self.assertEqual(response.status, 401)
            await response.read()
        self.assertEqual(self.calls, [])

    async def test_unapproved_routes_never_contact_upstream_and_logs_are_fixed(
        self,
    ) -> None:
        raw_path = "/caller-controlled/private-transcript"
        with self.assertLogs("f2_auth_proxy", level="INFO") as captured:
            rejected = await self.client.get(f"{raw_path}?secret=also-not-logged")
            self.assertEqual(rejected.status, 401)
            await rejected.read()
            rejected_with_key = await self.client.get(
                f"{raw_path}?secret=not-logged",
                headers={"Authorization": f"Bearer {API_KEY}"},
            )
            self.assertEqual(rejected_with_key.status, 404)
            await rejected_with_key.read()

            for method, path in (
                ("POST", "/v1/completions"),
                ("POST", "/v1/audio/transcriptions"),
                ("GET", "/v1/chat/completions"),
            ):
                response = await self.client.request(
                    method,
                    path,
                    headers={"Authorization": f"Bearer {API_KEY}"},
                )
                self.assertEqual(response.status, 404)
                await response.read()
        output = "\n".join(captured.output)
        self.assertIn("route=other", output)
        self.assertNotIn("private-transcript", output)
        self.assertNotIn("not-logged", output)
        self.assertNotIn("also-not-logged", output)
        self.assertEqual(self.calls, [])

    async def test_sllm_approved_routes_are_forwarded(self) -> None:
        models = await self.client.get(
            "/v1/models?view=summary",
            headers={"Authorization": f"Bearer {API_KEY}"},
        )
        self.assertEqual(models.status, 200)
        await models.read()
        chat = await self.client.post(
            "/v1/chat/completions",
            data=b"{}",
            headers={"Authorization": f"Bearer {API_KEY}"},
        )
        self.assertEqual(chat.status, 200)
        await chat.read()
        self.assertEqual(
            self.calls,
            [
                ("GET", "/v1/models?view=summary"),
                ("POST", "/v1/chat/completions"),
            ],
        )

    async def test_proxy_requires_strong_url_safe_key(self) -> None:
        invalid_keys = (
            "",
            "short-key",
            "a" * 42,
            "a" * 129,
            "!" * 43,
            "{{ RUNPOD_SECRET_AI_VLLM_SLLM_API_KEY }}",
        )
        for key in invalid_keys:
            with self.subTest(key=key), self.assertRaises(ValueError):
                auth_proxy.create_application(
                    upstream_port=self.upstream_server.port,
                    api_key=key,
                    service="sllm",
                )

    async def test_multipart_audio_is_streamed_without_reencoding(self) -> None:
        await self.client.close()
        application = auth_proxy.create_application(
            upstream_port=self.upstream_server.port,
            api_key=API_KEY,
            service="stt",
        )
        self.client = TestClient(TestServer(application))
        await self.client.start_server()
        denied_chat = await self.client.post(
            "/v1/chat/completions",
            data=b"{}",
            headers={"Authorization": f"Bearer {API_KEY}"},
        )
        self.assertEqual(denied_chat.status, 404)
        await denied_chat.read()
        self.assertEqual(self.calls, [])
        received: dict[str, bytes | str] = {}

        async def multipart(request: web.Request) -> web.Response:
            reader = await request.multipart()
            part = await reader.next()
            assert part is not None
            received["name"] = part.name or ""
            received["filename"] = part.filename or ""
            received["body"] = await part.read()
            return web.json_response({"ok": True})

        self.upstream_handler = multipart
        form = FormData()
        form.add_field(
            "file",
            b"synthetic-mp3-bytes",
            filename="synthetic.mp3",
            content_type="audio/mpeg",
        )
        response = await self.client.post(
            "/v1/audio/transcriptions",
            data=form,
            headers={"Authorization": f"Bearer {API_KEY}"},
        )
        self.assertEqual(response.status, 200)
        await response.read()
        self.assertEqual(received["name"], "file")
        self.assertEqual(received["filename"], "synthetic.mp3")
        self.assertEqual(received["body"], b"synthetic-mp3-bytes")

    async def test_streaming_response_reaches_client_before_upstream_finishes(
        self,
    ) -> None:
        first_written = asyncio.Event()
        release_second = asyncio.Event()

        async def stream(_request: web.Request) -> web.StreamResponse:
            response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
            await response.prepare(_request)
            await response.write(b"data: first\n\n")
            first_written.set()
            await release_second.wait()
            await response.write(b"data: second\n\n")
            await response.write_eof()
            return response

        self.upstream_handler = stream
        request_task = asyncio.create_task(
            self.client.post(
                "/v1/chat/completions",
                data=b"{}",
                headers={
                    "Authorization": f"Bearer {API_KEY}",
                    "Content-Type": "application/json",
                },
            )
        )
        await asyncio.wait_for(first_written.wait(), timeout=1)
        response = await asyncio.wait_for(request_task, timeout=1)
        first = await asyncio.wait_for(response.content.readexactly(13), timeout=1)
        self.assertEqual(first, b"data: first\n\n")
        release_second.set()
        remainder = await asyncio.wait_for(response.read(), timeout=1)
        self.assertEqual(remainder, b"data: second\n\n")

    async def test_request_body_limit_is_enforced_before_upstream(self) -> None:
        await self.client.close()
        application = auth_proxy.create_application(
            upstream_port=self.upstream_server.port,
            api_key=API_KEY,
            service="sllm",
            max_request_bytes=64,
        )
        self.client = TestClient(TestServer(application))
        await self.client.start_server()
        response = await self.client.post(
            "/v1/chat/completions",
            data=b"x" * 65,
            headers={"Authorization": f"Bearer {API_KEY}"},
        )
        self.assertEqual(response.status, 413)
        await response.read()
        self.assertEqual(self.calls, [])

    async def test_chunked_request_body_limit_is_enforced(self) -> None:
        await self.client.close()
        application = auth_proxy.create_application(
            upstream_port=self.upstream_server.port,
            api_key=API_KEY,
            service="sllm",
            max_request_bytes=64,
        )
        self.client = TestClient(TestServer(application))
        await self.client.start_server()

        async def chunks():
            yield b"x" * 33
            yield b"y" * 32

        response = await self.client.post(
            "/v1/chat/completions",
            data=chunks(),
            headers={"Authorization": f"Bearer {API_KEY}"},
        )
        self.assertEqual(response.status, 413)
        await response.read()


if __name__ == "__main__":
    unittest.main()
