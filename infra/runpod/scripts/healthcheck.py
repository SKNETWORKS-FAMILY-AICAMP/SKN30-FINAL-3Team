#!/usr/bin/env python3
"""Authenticated health check for both local OpenAI-compatible APIs."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject redirects so a health-check bearer token never changes origin."""

    def redirect_request(
        self,
        request: urllib.request.Request,
        file_pointer: object,
        code: int,
        message: str,
        headers: object,
        new_url: str,
    ) -> None:
        return None


DIRECT_PROXY_HANDLER = urllib.request.ProxyHandler({})
DIRECT_OPENER = urllib.request.build_opener(
    DIRECT_PROXY_HANDLER,
    NoRedirectHandler(),
)


def check(port: int, key_name: str, expected_model: str) -> None:
    api_key = os.environ.get(key_name, "")
    if not api_key:
        raise RuntimeError(f"{key_name} is unavailable")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/models",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    with DIRECT_OPENER.open(request, timeout=10) as response:
        if response.status != 200:
            raise RuntimeError(f"port {port} returned status {response.status}")
        payload = json.loads(response.read(1024 * 1024))
        data = payload.get("data") if isinstance(payload, dict) else None
        model_ids = {
            item.get("id")
            for item in data
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        } if isinstance(data, list) else set()
        if expected_model not in model_ids:
            raise RuntimeError(f"port {port} did not expose the expected model")


def main() -> int:
    try:
        check(8001, "AI_VLLM_SLLM_API_KEY", "sllm")
        check(8002, "AI_VLLM_STT_API_KEY", "stt")
    except (
        OSError,
        RuntimeError,
        json.JSONDecodeError,
        urllib.error.HTTPError,
        urllib.error.URLError,
    ) as error:
        print(
            f"f2-serving health check failed: {type(error).__name__}", file=sys.stderr
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
