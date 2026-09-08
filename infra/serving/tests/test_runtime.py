import asyncio
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import general_runtime
from general_middleware import ServingRoutes


class GeneralHttpSurface(unittest.TestCase):
    def request(self, method, path, headers):
        messages = []
        upstream = Mock()

        async def app(scope, receive, send):
            upstream()

        async def send(message):
            messages.append(message)

        with patch.dict("os.environ", {"VLLM_API_KEY": "k" * 43}):
            middleware = ServingRoutes(app)
        asyncio.run(
            middleware(
                {"type": "http", "method": method, "path": path, "headers": headers},
                None,
                send,
            )
        )
        return upstream, messages

    def test_native_admin_paths_are_blocked_even_with_valid_key(self):
        headers = [(b"authorization", b"Bearer " + b"k" * 43)]
        for path in ("/load_lora_adapter", "/sleep", "/metrics", "/docs"):
            upstream, messages = self.request("GET", path, headers)
            upstream.assert_not_called()
            self.assertEqual(messages[0]["status"], 404)

    def test_missing_or_duplicate_authorization_is_rejected(self):
        for headers in ([], [(b"authorization", b"Bearer " + b"k" * 43)] * 2):
            upstream, messages = self.request("POST", "/v1/chat/completions", headers)
            upstream.assert_not_called()
            self.assertEqual(messages[0]["status"], 401)

    def test_inference_is_forwarded_and_status_never_contains_credentials(self):
        headers = [(b"authorization", b"Bearer " + b"k" * 43)]
        upstream, messages = self.request("POST", "/v1/chat/completions", headers)
        upstream.assert_called_once()
        self.assertEqual(messages, [])
        with patch.dict("os.environ", {"HF_HOME": "/tmp"}):
            _, messages = self.request("GET", "/ops/status", headers)
        self.assertEqual(messages[0]["status"], 200)
        payload = json.loads(messages[1]["body"])
        self.assertEqual(set(payload), {"disk_total_bytes", "disk_free_bytes", "model"})


class GeneralStartup(unittest.TestCase):
    def test_missing_credential_fails_before_exec(self):
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(general_runtime.os, "execvp") as execute,
        ):
            with self.assertRaises(ValueError):
                general_runtime.main()
            execute.assert_not_called()

    def test_startup_keeps_key_out_of_command_and_removes_cloud_credentials(self):
        environment = {
            "AI_GENERAL_API_KEY": "k" * 43,
            "AWS_ACCESS_KEY_ID": "synthetic",
            "AWS_SECRET_ACCESS_KEY": "synthetic",
            "AWS_SESSION_TOKEN": "synthetic",
            "HF_TOKEN": "synthetic",
        }
        with (
            patch.dict("os.environ", environment, clear=True),
            patch.object(
                general_runtime, "prepare_model", return_value=("/snapshot", "a" * 64)
            ),
            patch.object(general_runtime.os, "execvp") as execute,
        ):
            general_runtime.main()
            command = execute.call_args.args[1]
            self.assertNotIn("k" * 43, " ".join(command))
            self.assertEqual(general_runtime.os.environ["VLLM_API_KEY"], "k" * 43)
            for key in environment:
                self.assertNotIn(key, general_runtime.os.environ)

    def test_missing_mounted_snapshot_fails_before_exec(self):
        with (
            patch.dict(
                "os.environ",
                {
                    "AI_GENERAL_API_KEY": "k" * 43,
                    "GENERAL_MODEL_PATH": "/models/general",
                },
                clear=True,
            ),
            patch.object(general_runtime.Path, "is_file", return_value=False),
            patch.object(general_runtime.os, "execvp") as execute,
        ):
            with self.assertRaises(ValueError):
                general_runtime.main()
            execute.assert_not_called()
