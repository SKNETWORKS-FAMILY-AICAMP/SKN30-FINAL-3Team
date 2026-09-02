#!/usr/bin/env python3
"""Run the dev Backend F2 path with a repository-owned synthetic voice fixture."""

from __future__ import annotations

import argparse
import base64
import json
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any

EXPECTED_RESPONSE_FIELDS = {
    "consultation_type",
    "ledger_mismatch",
    "proposals",
    "uncertainties",
    "consultation_log_draft",
    "privacy_confirmed_at",
}


class SmokeFailure(RuntimeError):
    """A safe failure that never contains a response body or credential."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Reject redirects so loopback cookies and CSRF headers stay on loopback."""

    def redirect_request(
        self,
        request: urllib.request.Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> None:
        return None


NO_PROXY_HANDLER = urllib.request.ProxyHandler({})
LOOPBACK_OPENER = urllib.request.build_opener(
    NO_PROXY_HANDLER,
    NoRedirect(),
)


def _request(
    url: str,
    *,
    method: str,
    headers: Mapping[str, str] | None = None,
    body: bytes | None = None,
    timeout: int = 90,
) -> tuple[int, Any, bytes]:
    request = urllib.request.Request(
        url,
        method=method,
        headers=dict(headers or {}),
        data=body,
    )
    try:
        with LOOPBACK_OPENER.open(request, timeout=timeout) as response:
            return response.status, response.headers, response.read(1024 * 1024)
    except urllib.error.HTTPError as error:
        error.read(1024 * 1024)
        return error.code, error.headers, b""
    except urllib.error.URLError as error:
        raise SmokeFailure(
            f"Backend request failed: {type(error.reason).__name__}"
        ) from error


def _json_object(raw: bytes, operation: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SmokeFailure(f"{operation} returned invalid JSON") from error
    if not isinstance(value, dict):
        raise SmokeFailure(f"{operation} returned an unexpected JSON value")
    return value


def _cookies(headers: Any) -> str:
    cookie = SimpleCookie()
    for value in headers.get_all("Set-Cookie", []):
        cookie.load(value)
    pairs = [f"{name}={morsel.value}" for name, morsel in sorted(cookie.items())]
    if len(pairs) < 2:
        raise SmokeFailure("development session did not issue both required cookies")
    return "; ".join(pairs)


def _multipart(audio: bytes) -> tuple[bytes, str]:
    boundary = f"----skn30-f2-smoke-{secrets.token_hex(12)}"
    fields = {
        "ledger_type": "구입장",
        "current_fields": "{}",
        "privacy_confirmed": "true",
    }
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n"
            ).encode()
        )
    parts.append(
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="audio"; filename="synthetic-smoke.mp3"\r\n'
            "Content-Type: audio/mpeg\r\n\r\n"
        ).encode("ascii")
        + audio
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(parts), boundary


def _load_audio(path: Path) -> bytes:
    try:
        encoded = path.read_bytes()
        audio = base64.b64decode(b"".join(encoded.split()), validate=True)
    except (OSError, ValueError) as error:
        raise SmokeFailure(
            "synthetic smoke audio fixture is unavailable or invalid"
        ) from error
    if not audio.startswith(b"ID3") or not 1_000 <= len(audio) <= 1_000_000:
        raise SmokeFailure(
            "synthetic smoke audio fixture has an unexpected format or size"
        )
    return audio


def run(base_url: str, audio_path: Path) -> None:
    base_url = base_url.rstrip("/")
    try:
        parsed_base_url = urllib.parse.urlsplit(base_url)
        port = parsed_base_url.port
    except ValueError as error:
        raise SmokeFailure("smoke base URL is malformed") from error
    if (
        parsed_base_url.scheme != "http"
        or parsed_base_url.hostname not in {"127.0.0.1", "localhost"}
        or port is None
        or not 1 <= port <= 65535
        or parsed_base_url.path
        or parsed_base_url.query
        or parsed_base_url.fragment
        or parsed_base_url.username is not None
        or parsed_base_url.password is not None
    ):
        raise SmokeFailure(
            "smoke base URL must be a local HTTP Backend with an explicit port"
        )

    status, headers, raw = _request(
        f"{base_url}/api/v1/auth/development-session",
        method="POST",
    )
    if status != 200:
        raise SmokeFailure(f"development session failed with HTTP {status}")
    session = _json_object(raw, "development session")
    csrf_token = session.get("csrf_token")
    if not isinstance(csrf_token, str) or not csrf_token:
        raise SmokeFailure("development session response is missing a CSRF token")

    body, boundary = _multipart(_load_audio(audio_path))
    status, _, raw = _request(
        f"{base_url}/api/v1/f2/analyses",
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Cookie": _cookies(headers),
            "X-CSRF-Token": csrf_token,
        },
        body=body,
    )
    if status != 200:
        raise SmokeFailure(f"F2 analysis failed with HTTP {status}")
    result = _json_object(raw, "F2 analysis")
    if set(result) != EXPECTED_RESPONSE_FIELDS:
        raise SmokeFailure("F2 analysis response does not match the public schema")
    if (
        not isinstance(result["consultation_type"], str)
        or not result["consultation_type"]
    ):
        raise SmokeFailure("F2 analysis response is missing a consultation type")
    if not isinstance(result["ledger_mismatch"], bool):
        raise SmokeFailure("F2 analysis response has an invalid ledger mismatch flag")
    if not isinstance(result["proposals"], list) or not isinstance(
        result["uncertainties"], list
    ):
        raise SmokeFailure("F2 analysis response has invalid collection fields")
    if (
        not isinstance(result["consultation_log_draft"], str)
        or not result["consultation_log_draft"].strip()
    ):
        raise SmokeFailure("F2 analysis response is missing its consultation log draft")
    if not isinstance(result["privacy_confirmed_at"], str):
        raise SmokeFailure("F2 analysis response is missing privacy confirmation time")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--audio", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    try:
        run(arguments.base_url, arguments.audio)
    except SmokeFailure as error:
        print(f"F2 end-to-end smoke failed: {error}", file=sys.stderr)
        return 1
    print("F2 end-to-end smoke succeeded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
