from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from unittest import mock

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPOSITORY_ROOT / "infra/deploy/scripts/smoke_f2.py"
FIXTURE_PATH = REPOSITORY_ROOT / "infra/deploy/scripts/smoke_f2_audio.mp3.b64"
SPEC = importlib.util.spec_from_file_location("smoke_f2", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
smoke_f2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke_f2)


class Headers:
    def __init__(self, cookies: list[str] | None = None) -> None:
        self.cookies = cookies or []

    def get_all(self, name: str, default: list[str]) -> list[str]:
        return self.cookies if name.lower() == "set-cookie" else default


class F2SmokeTests(unittest.TestCase):
    def test_loopback_client_disables_proxies_and_redirects(self) -> None:
        handlers = smoke_f2.LOOPBACK_OPENER.handlers

        self.assertEqual(smoke_f2.NO_PROXY_HANDLER.proxies, {})
        self.assertTrue(
            any(isinstance(handler, smoke_f2.NoRedirect) for handler in handlers)
        )

    def test_repository_fixture_is_small_synthetic_mp3(self) -> None:
        audio = smoke_f2._load_audio(FIXTURE_PATH)

        self.assertTrue(audio.startswith(b"ID3"))
        self.assertGreater(len(audio), 1_000)
        self.assertLess(len(audio), 1_000_000)

    def test_run_uses_dev_session_csrf_and_validates_public_response(self) -> None:
        calls: list[tuple[str, dict[str, object]]] = []
        session_headers = Headers(
            [
                "brokerage_session=session-value; Secure; HttpOnly; Path=/",
                "brokerage_csrf=csrf-cookie-value; Secure; HttpOnly; Path=/",
            ]
        )
        analysis = {
            "consultation_type": "매수문의",
            "ledger_mismatch": False,
            "proposals": [],
            "uncertainties": [],
            "consultation_log_draft": "합성 입력 통합 검사",
            "privacy_confirmed_at": "2026-09-01T00:00:00Z",
        }

        def fake_request(url: str, **kwargs: object) -> tuple[int, Headers, bytes]:
            calls.append((url, kwargs))
            if url.endswith("/auth/development-session"):
                return (
                    200,
                    session_headers,
                    json.dumps({"csrf_token": "csrf-response-value"}).encode(),
                )
            return 200, Headers(), json.dumps(analysis, ensure_ascii=False).encode()

        with mock.patch.object(smoke_f2, "_request", side_effect=fake_request):
            smoke_f2.run("http://127.0.0.1:8000", FIXTURE_PATH)

        self.assertEqual(len(calls), 2)
        analysis_headers = calls[1][1]["headers"]
        assert isinstance(analysis_headers, dict)
        self.assertEqual(analysis_headers["X-CSRF-Token"], "csrf-response-value")
        self.assertIn("brokerage_session=session-value", analysis_headers["Cookie"])
        body = calls[1][1]["body"]
        assert isinstance(body, bytes)
        self.assertIn("구입장".encode(), body)
        self.assertIn(b"synthetic-smoke.mp3", body)

    def test_failure_message_never_copies_backend_response(self) -> None:
        private_body = b"private transcript must not be logged"
        with (
            mock.patch.object(
                smoke_f2,
                "_request",
                return_value=(503, Headers(), private_body),
            ),
            self.assertRaisesRegex(smoke_f2.SmokeFailure, "HTTP 503") as raised,
        ):
            smoke_f2.run("http://localhost:8000", FIXTURE_PATH)

        self.assertNotIn(private_body.decode(), str(raised.exception))

    def test_rejects_non_loopback_backend(self) -> None:
        with self.assertRaisesRegex(smoke_f2.SmokeFailure, "local HTTP Backend"):
            smoke_f2.run("https://example.com:443", FIXTURE_PATH)


if __name__ == "__main__":
    unittest.main()
