import importlib.util
import json
import stat
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPOSITORY_ROOT / "infra/deploy/scripts/render_env.py"
SPEC = importlib.util.spec_from_file_location("render_env", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
render_env = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(render_env)


class RenderEnvironmentTests(unittest.TestCase):
    LLM_KEY = "l" * 43
    STT_KEY = "s" * 43

    def endpoint_set(self, **overrides: object) -> str:
        payload: dict[str, object] = {
            "revision": 3,
            "status": "active",
            "pod_id": "abc123def4567",
            "sllm_release_id": "consultation-v1",
            "sllm_base_url": "https://abc123def4567-8001.proxy.runpod.net/v1",
            "stt_base_url": "https://abc123def4567-8002.proxy.runpod.net/v1",
            "updated_at": "2026-09-01T12:34:56+09:00",
        }
        payload.update(overrides)
        return json.dumps(payload)

    def test_public_parameters_accept_new_valid_names_without_an_allowlist(
        self,
    ) -> None:
        payload = {
            "Parameters": [
                {
                    "Name": "/project-dev/backend/NEW_BACKEND_FEATURE",
                    "Value": "enabled",
                },
                {
                    "Name": "/project-dev/ai/AI_REQUEST_TIMEOUT_SECONDS",
                    "Value": "45",
                },
            ]
        }

        result = render_env.parse_public_parameters(payload, "/project-dev")

        self.assertEqual(result["backend"], {"NEW_BACKEND_FEATURE": "enabled"})
        self.assertEqual(result["ai"], {"AI_REQUEST_TIMEOUT_SECONDS": "45"})

    def test_public_parameters_reject_invalid_reserved_and_duplicate_names(
        self,
    ) -> None:
        invalid_payloads = (
            {
                "Parameters": [
                    {"Name": "/project-dev/backend/lowercase", "Value": "value"}
                ]
            },
            {"Parameters": [{"Name": "/project-dev/backend/DB_URL", "Value": "value"}]},
            {
                "Parameters": [
                    {
                        "Name": "/project-dev/ai/AI_OPENAI_API_KEY",
                        "Value": "value",
                    }
                ]
            },
            {
                "Parameters": [
                    {"Name": "/project-dev/backend/LOG_LEVEL", "Value": "INFO"},
                    {"Name": "/project-dev/ai/LOG_LEVEL", "Value": "INFO"},
                ]
            },
        )

        for payload in invalid_payloads:
            with self.subTest(payload=payload), self.assertRaises(SystemExit):
                render_env.parse_public_parameters(payload, "/project-dev")

    def test_ai_vllm_endpoint_set_is_strict_and_expands_atomically(self) -> None:
        public = {
            "backend": {"APP_ENV": "dev"},
            "ai": {
                "AI_REQUEST_TIMEOUT_SECONDS": "60",
                "AI_VLLM_ENDPOINT_SET": self.endpoint_set(),
            },
        }

        expanded = render_env.expand_ai_vllm_endpoint_set(public)

        self.assertEqual(
            expanded["ai"]["AI_VLLM_SLLM_BASE_URL"],
            "https://abc123def4567-8001.proxy.runpod.net/v1",
        )
        self.assertEqual(
            expanded["ai"]["AI_VLLM_STT_BASE_URL"],
            "https://abc123def4567-8002.proxy.runpod.net/v1",
        )
        self.assertEqual(expanded["ai"]["AI_F2_PROVIDER_STATUS"], "active")
        self.assertNotIn("AI_VLLM_ENDPOINT_SET", expanded["ai"])
        self.assertIn("AI_VLLM_ENDPOINT_SET", public["ai"])

    def test_ai_vllm_endpoint_set_rejects_invalid_schema_and_values(self) -> None:
        invalid_values = (
            json.dumps(
                {
                    "revision": 1,
                    "status": "active",
                    "pod_id": "abc123def4567",
                    "sllm_release_id": "consultation-v1",
                    "sllm_base_url": "https://abc123def4567-8001.proxy.runpod.net/v1",
                    "stt_base_url": "https://abc123def4567-8002.proxy.runpod.net/v1",
                    "updated_at": "2026-09-01T00:00:00Z",
                    "extra": "rejected",
                }
            ),
            self.endpoint_set(revision=True),
            self.endpoint_set(revision=-1),
            self.endpoint_set(
                revision=1,
                pod_id="unconfigured",
                sllm_base_url="https://unconfigured-8001.proxy.runpod.net/v1",
                stt_base_url="https://unconfigured-8002.proxy.runpod.net/v1",
            ),
            self.endpoint_set(pod_id="UPPERCASE"),
            self.endpoint_set(updated_at="2026-09-01 00:00:00"),
            self.endpoint_set(
                sllm_base_url="http://abc123def4567-8001.proxy.runpod.net/v1"
            ),
            self.endpoint_set(
                stt_base_url="https://differentpod-8002.proxy.runpod.net/v1"
            ),
            self.endpoint_set(
                stt_base_url="https://abc123def4567-8002.proxy.runpod.net/v1?key=value"
            ),
            self.endpoint_set(
                stt_base_url="https://abc123def4567-8002.proxy.runpod.net:invalid/v1"
            ),
            (
                '{"revision":1,"revision":2,"status":"active","pod_id":"abc123def4567",'
                '"sllm_release_id":"consultation-v1",'
                '"sllm_base_url":"https://abc123def4567-8001.proxy.runpod.net/v1",'
                '"stt_base_url":"https://abc123def4567-8002.proxy.runpod.net/v1",'
                '"updated_at":"2026-09-01T00:00:00Z"}'
            ),
        )

        for raw in invalid_values:
            with self.subTest(raw=raw), self.assertRaises(SystemExit):
                render_env.parse_ai_vllm_endpoint_set(raw)

    def test_offline_endpoint_set_expands_without_urls(self) -> None:
        raw = json.dumps(
            {
                "revision": 4,
                "status": "offline",
                "pod_id": None,
                "sllm_release_id": None,
                "sllm_base_url": None,
                "stt_base_url": None,
                "updated_at": "2026-09-01T12:34:56+09:00",
            }
        )

        result = render_env.parse_ai_vllm_endpoint_set(raw)

        self.assertEqual(result, {"AI_F2_PROVIDER_STATUS": "offline"})

    def test_ai_vllm_endpoint_set_rejects_missing_and_legacy_parameters(self) -> None:
        with self.assertRaisesRegex(SystemExit, "Missing public parameter"):
            render_env.expand_ai_vllm_endpoint_set(
                {"backend": {}, "ai": {"AI_REQUEST_TIMEOUT_SECONDS": "60"}}
            )

        with self.assertRaisesRegex(SystemExit, "legacy public parameters"):
            render_env.expand_ai_vllm_endpoint_set(
                {
                    "backend": {},
                    "ai": {
                        "AI_VLLM_ENDPOINT_SET": self.endpoint_set(),
                        "AI_VLLM_SLLM_BASE_URL": "https://legacy.example/v1",
                    },
                }
            )

    def test_ai_provider_keys_require_api_and_worker_keys(self) -> None:
        provider_keys = {
            "AI_OPENAI_API_KEY": "openai-test",
            "AI_VLLM_SLLM_API_KEY": self.LLM_KEY,
            "AI_VLLM_STT_API_KEY": self.STT_KEY,
        }

        keys = render_env.parse_ai_provider_keys(json.dumps(provider_keys))

        self.assertEqual(set(keys), set(provider_keys))
        for missing_name in provider_keys:
            incomplete = {
                name: value
                for name, value in provider_keys.items()
                if name != missing_name
            }
            with (
                self.subTest(missing_name=missing_name),
                self.assertRaisesRegex(SystemExit, missing_name),
            ):
                render_env.parse_ai_provider_keys(json.dumps(incomplete))

    def test_ai_provider_keys_reject_weak_or_shared_vllm_keys(self) -> None:
        invalid_pairs = (
            ("weak", self.STT_KEY),
            (self.LLM_KEY, "contains+unsupported+characters" * 2),
            (self.LLM_KEY, self.LLM_KEY),
        )
        for llm_key, stt_key in invalid_pairs:
            with (
                self.subTest(llm_key=llm_key, stt_key=stt_key),
                self.assertRaises(SystemExit),
            ):
                render_env.parse_ai_provider_keys(
                    json.dumps(
                        {
                            "AI_OPENAI_API_KEY": "openai-test",
                            "AI_VLLM_SLLM_API_KEY": llm_key,
                            "AI_VLLM_STT_API_KEY": stt_key,
                        }
                    )
                )

    def test_process_environment_files_route_public_ai_and_isolate_secrets(
        self,
    ) -> None:
        api, worker, migration = render_env.build_process_environments(
            public={
                "backend": {"APP_ENV": "prod", "WORKER_ENABLED": "false"},
                "ai": {
                    "AI_OPENAI_BASE_URL": "https://openai.example/v1",
                    "AI_VLLM_ENDPOINT_SET": self.endpoint_set(),
                },
            },
            runtime_url="postgresql+psycopg://runtime",
            migration_url="postgresql+psycopg://migration",
            ai_provider_keys={
                "AI_OPENAI_API_KEY": "openai-test",
                "AI_VLLM_SLLM_API_KEY": self.LLM_KEY,
                "AI_VLLM_STT_API_KEY": self.STT_KEY,
            },
        )

        self.assertEqual(api["DB_URL"], "postgresql+psycopg://runtime")
        self.assertNotIn("AI_OPENAI_API_KEY", api)
        self.assertEqual(api["AI_VLLM_SLLM_API_KEY"], self.LLM_KEY)
        self.assertEqual(api["AI_VLLM_STT_API_KEY"], self.STT_KEY)
        self.assertEqual(api["AI_OPENAI_BASE_URL"], "https://openai.example/v1")
        self.assertEqual(
            api["AI_VLLM_SLLM_BASE_URL"],
            "https://abc123def4567-8001.proxy.runpod.net/v1",
        )
        self.assertEqual(
            api["AI_VLLM_STT_BASE_URL"],
            "https://abc123def4567-8002.proxy.runpod.net/v1",
        )
        self.assertNotIn("AI_VLLM_ENDPOINT_SET", api)
        self.assertEqual(worker["AI_OPENAI_API_KEY"], "openai-test")
        self.assertEqual(worker["AI_VLLM_SLLM_API_KEY"], self.LLM_KEY)
        self.assertEqual(worker["AI_VLLM_STT_API_KEY"], self.STT_KEY)
        self.assertEqual(worker["DB_URL"], "postgresql+psycopg://runtime")
        self.assertEqual(
            worker["AI_VLLM_SLLM_BASE_URL"],
            "https://abc123def4567-8001.proxy.runpod.net/v1",
        )
        self.assertEqual(
            worker["AI_VLLM_STT_BASE_URL"],
            "https://abc123def4567-8002.proxy.runpod.net/v1",
        )
        self.assertNotIn("AI_VLLM_ENDPOINT_SET", worker)
        self.assertEqual(
            migration, {"DB_MIGRATION_URL": "postgresql+psycopg://migration"}
        )

    def test_write_env_is_atomic_and_owner_only(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            output = Path(directory) / "api.env"
            output.write_text("ORIGINAL=value\n", encoding="utf-8")

            with self.assertRaises(SystemExit):
                render_env.write_env(output, {"APP_ENV": "prod\ninvalid"})
            self.assertEqual(output.read_text(encoding="utf-8"), "ORIGINAL=value\n")

            render_env.write_env(output, {"DB_URL": "secret", "APP_ENV": "prod"})

            self.assertEqual(
                output.read_text(encoding="utf-8"),
                "APP_ENV=prod\nDB_URL=secret\n",
            )
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            self.assertEqual(list(output.parent.glob(".api.env.*")), [])


if __name__ == "__main__":
    unittest.main()
