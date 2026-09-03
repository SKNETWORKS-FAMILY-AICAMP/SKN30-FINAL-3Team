from __future__ import annotations

import importlib.util
import json
import os
import sys
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

RUNPOD_ROOT = Path(__file__).resolve().parents[1]


def load_healthcheck():
    path = RUNPOD_ROOT / "scripts" / "healthcheck.py"
    spec = importlib.util.spec_from_file_location("f2_healthcheck", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


healthcheck = load_healthcheck()


class HealthcheckTests(unittest.TestCase):
    def test_opener_explicitly_disables_proxies_and_redirects(self) -> None:
        redirect_handlers = [
            handler
            for handler in healthcheck.DIRECT_OPENER.handlers
            if isinstance(handler, healthcheck.NoRedirectHandler)
        ]
        self.assertIsInstance(
            healthcheck.DIRECT_PROXY_HANDLER,
            urllib.request.ProxyHandler,
        )
        self.assertEqual(healthcheck.DIRECT_PROXY_HANDLER.proxies, {})
        self.assertEqual(len(redirect_handlers), 1)
        self.assertIsNone(
            redirect_handlers[0].redirect_request(
                mock.Mock(),
                mock.Mock(),
                302,
                "Found",
                mock.Mock(),
                "https://attacker.invalid/steal",
            )
        )

    def test_check_uses_fixed_loopback_url_and_direct_opener(self) -> None:
        response = mock.MagicMock(status=200)
        response.read.return_value = json.dumps({"data": [{"id": "sllm"}]}).encode()
        response.__enter__.return_value = response
        with (
            mock.patch.dict(os.environ, {"TEST_API_KEY": "k" * 43}, clear=True),
            mock.patch.object(
                healthcheck.DIRECT_OPENER,
                "open",
                return_value=response,
            ) as open_request,
        ):
            healthcheck.check(8001, "TEST_API_KEY", "sllm")

        request = open_request.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:8001/v1/models")
        self.assertEqual(request.get_header("Authorization"), f"Bearer {'k' * 43}")
        self.assertEqual(open_request.call_args.kwargs, {"timeout": 10})
        response.read.assert_called_once_with(1024 * 1024)

    def test_check_rejects_unexpected_model_id(self) -> None:
        response = mock.MagicMock(status=200)
        response.read.return_value = json.dumps(
            {"data": [{"id": "wrong-model"}]}
        ).encode()
        response.__enter__.return_value = response
        with (
            mock.patch.dict(os.environ, {"TEST_API_KEY": "k" * 43}, clear=True),
            mock.patch.object(
                healthcheck.DIRECT_OPENER,
                "open",
                return_value=response,
            ),
            self.assertRaisesRegex(RuntimeError, "expected model"),
        ):
            healthcheck.check(8001, "TEST_API_KEY", "sllm")


if __name__ == "__main__":
    unittest.main()
