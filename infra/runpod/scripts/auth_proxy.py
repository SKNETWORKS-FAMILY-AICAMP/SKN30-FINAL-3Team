#!/usr/bin/env python3
"""Streaming, route-allowlisted Bearer authentication proxy for local vLLM."""

from __future__ import annotations

import argparse
import hmac
import logging
import os
import re
import time
from collections.abc import AsyncIterator

from aiohttp import ClientError, ClientSession, ClientTimeout, web
from multidict import CIMultiDict

LOGGER = logging.getLogger("f2_auth_proxy")
MAX_REQUEST_BYTES = 26 * 1024 * 1024
STREAM_CHUNK_BYTES = 64 * 1024
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "proxy-connection",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
ROUTE_LABELS = {
    "/v1/models": "models",
    "/v1/chat/completions": "chat_completions",
    "/v1/audio/transcriptions": "audio_transcriptions",
}
ALLOWED_ROUTES = {
    "sllm": {
        ("GET", "/v1/models"),
        ("POST", "/v1/chat/completions"),
    },
    "stt": {
        ("GET", "/v1/models"),
        ("POST", "/v1/audio/transcriptions"),
    },
}
API_KEY_PATTERN = re.compile(r"[A-Za-z0-9_-]{43,128}\Z")
REQUEST_STRIP_HEADERS = HOP_BY_HOP_HEADERS | {
    "content-length",
    "host",
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-proto",
}
UPSTREAM_SESSION_KEY = web.AppKey("upstream_session", ClientSession)


class RequestBodyTooLarge(Exception):
    """Internal marker preserved through aiohttp's streaming client error chain."""

    def __init__(self, actual_size: int) -> None:
        self.actual_size = actual_size
        super().__init__("request body exceeded the configured limit")


def _body_limit_error(error: BaseException) -> RequestBodyTooLarge | None:
    current: BaseException | None = error
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        if isinstance(current, RequestBodyTooLarge):
            return current
        current = current.__cause__ or current.__context__
    return None


def _safe_headers(
    raw_headers: tuple[tuple[bytes, bytes], ...], blocked: set[str]
) -> CIMultiDict[str]:
    effective_blocked = set(blocked)
    for raw_name, raw_value in raw_headers:
        if raw_name.decode("latin-1").lower() == "connection":
            effective_blocked.update(
                token.strip().lower()
                for token in raw_value.decode("latin-1").split(",")
                if token.strip()
            )
    headers: CIMultiDict[str] = CIMultiDict()
    for raw_name, raw_value in raw_headers:
        name = raw_name.decode("latin-1")
        if name.lower() not in effective_blocked:
            headers.add(name, raw_value.decode("latin-1"))
    return headers


def create_application(
    *,
    upstream_port: int,
    api_key: str,
    service: str,
    max_request_bytes: int = MAX_REQUEST_BYTES,
) -> web.Application:
    if service not in ALLOWED_ROUTES:
        raise ValueError("service must be sllm or stt")
    if (
        api_key.startswith("{{ RUNPOD_SECRET_")
        or API_KEY_PATTERN.fullmatch(api_key) is None
    ):
        raise ValueError(
            "F2_PROXY_API_KEY must resolve to a 43-128 character URL-safe RunPod Secret"
        )
    expected_authorization = f"Bearer {api_key}".encode("ascii")
    upstream_origin = f"http://127.0.0.1:{upstream_port}"

    @web.middleware
    async def authenticate_and_log(
        request: web.Request,
        handler: web.RequestHandler,
    ) -> web.StreamResponse:
        started = time.monotonic()
        status = 500
        try:
            authorizations = request.headers.getall("Authorization", [])
            authorized = len(authorizations) == 1 and hmac.compare_digest(
                authorizations[0].encode("latin-1"), expected_authorization
            )
            if not authorized:
                response: web.StreamResponse = web.Response(
                    status=401,
                    headers={"WWW-Authenticate": "Bearer"},
                    text="unauthorized\n",
                )
            else:
                response = await handler(request)
            status = response.status
            return response
        except web.HTTPException as error:
            status = error.status
            raise
        finally:
            elapsed_ms = round((time.monotonic() - started) * 1000)
            LOGGER.info(
                "proxy_access service=%s method=%s route=%s status=%d duration_ms=%d",
                service,
                request.method,
                ROUTE_LABELS.get(request.path, "other"),
                status,
                elapsed_ms,
            )

    application = web.Application(
        middlewares=[authenticate_and_log],
        client_max_size=max_request_bytes,
    )

    async def start_session(app: web.Application) -> None:
        timeout = ClientTimeout(total=None, connect=10, sock_connect=10, sock_read=None)
        app[UPSTREAM_SESSION_KEY] = ClientSession(
            auto_decompress=False,
            timeout=timeout,
            skip_auto_headers={"Accept-Encoding"},
        )

    async def close_session(app: web.Application) -> None:
        await app[UPSTREAM_SESSION_KEY].close()

    async def request_body(request: web.Request) -> AsyncIterator[bytes]:
        received = 0
        async for chunk in request.content.iter_chunked(STREAM_CHUNK_BYTES):
            received += len(chunk)
            if received > max_request_bytes:
                raise RequestBodyTooLarge(received)
            yield chunk

    async def proxy(request: web.Request) -> web.StreamResponse:
        if (
            request.content_length is not None
            and request.content_length > max_request_bytes
        ):
            raise web.HTTPRequestEntityTooLarge(
                max_size=max_request_bytes,
                actual_size=request.content_length,
            )
        request_headers = _safe_headers(request.raw_headers, REQUEST_STRIP_HEADERS)
        request_data = request_body(request) if request.can_read_body else None
        session = request.app[UPSTREAM_SESSION_KEY]
        upstream_url = f"{upstream_origin}{request.rel_url.raw_path_qs}"
        response: web.StreamResponse | None = None
        try:
            async with session.request(
                request.method,
                upstream_url,
                headers=request_headers,
                data=request_data,
                allow_redirects=False,
            ) as upstream:
                response_headers = _safe_headers(
                    upstream.raw_headers,
                    HOP_BY_HOP_HEADERS,
                )
                response = web.StreamResponse(
                    status=upstream.status,
                    reason=upstream.reason,
                    headers=response_headers,
                )
                await response.prepare(request)
                async for chunk in upstream.content.iter_chunked(STREAM_CHUNK_BYTES):
                    await response.write(chunk)
                await response.write_eof()
                return response
        except RequestBodyTooLarge as error:
            raise web.HTTPRequestEntityTooLarge(
                max_size=max_request_bytes,
                actual_size=error.actual_size,
            ) from error
        except web.HTTPException:
            raise
        except ConnectionResetError:
            if response is not None and response.prepared:
                return response
            return web.Response(status=502, text="upstream unavailable\n")
        except ClientError as error:
            body_error = _body_limit_error(error)
            if body_error is not None:
                raise web.HTTPRequestEntityTooLarge(
                    max_size=max_request_bytes,
                    actual_size=body_error.actual_size,
                ) from error
            if response is not None and response.prepared:
                LOGGER.warning(
                    "proxy_stream_error service=%s error=%s",
                    service,
                    type(error).__name__,
                )
                if request.transport is not None:
                    request.transport.close()
                return response
            return web.Response(status=502, text="upstream unavailable\n")

    async def deny_unapproved_route(_request: web.Request) -> web.Response:
        return web.Response(status=404, text="not found\n")

    application.on_startup.append(start_session)
    application.on_cleanup.append(close_session)
    for method, path in sorted(ALLOWED_ROUTES[service]):
        application.router.add_route(method, path, proxy)
    application.router.add_route("*", "/{path:.*}", deny_unapproved_route)
    return application


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen-port", required=True, type=int, choices=(8001, 8002))
    parser.add_argument(
        "--upstream-port", required=True, type=int, choices=(18001, 18002)
    )
    parser.add_argument("--service", required=True, choices=("sllm", "stt"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    application = create_application(
        upstream_port=args.upstream_port,
        api_key=os.environ.get("F2_PROXY_API_KEY", ""),
        service=args.service,
    )
    web.run_app(
        application,
        host="0.0.0.0",
        port=args.listen_port,
        access_log=None,
        print=None,
        handler_cancellation=True,
    )


if __name__ == "__main__":
    main()
