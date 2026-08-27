import importlib.util
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

    def test_ai_provider_keys_require_openai_and_allow_optional_vllm(self) -> None:
        keys = render_env.parse_ai_provider_keys(
            '{"AI_OPENAI_API_KEY":"openai-test","AI_VLLM_LLM_API_KEY":"vllm-test"}'
        )

        self.assertEqual(set(keys), {"AI_OPENAI_API_KEY", "AI_VLLM_LLM_API_KEY"})
        with self.assertRaises(SystemExit):
            render_env.parse_ai_provider_keys('{"AI_VLLM_LLM_API_KEY":"vllm-test"}')

    def test_process_environment_files_route_public_ai_and_isolate_secrets(
        self,
    ) -> None:
        api, worker, migration = render_env.build_process_environments(
            public={
                "backend": {"APP_ENV": "prod", "WORKER_ENABLED": "false"},
                "ai": {
                    "AI_OPENAI_BASE_URL": "https://openai.example/v1",
                    "AI_VLLM_LLM_BASE_URL": "https://llm.example/v1",
                    "AI_VLLM_STT_BASE_URL": "https://stt.example/v1",
                },
            },
            runtime_url="postgresql+psycopg://runtime",
            migration_url="postgresql+psycopg://migration",
            ai_provider_keys={"AI_OPENAI_API_KEY": "openai-test"},
        )

        self.assertEqual(api["DB_URL"], "postgresql+psycopg://runtime")
        self.assertNotIn("AI_OPENAI_API_KEY", api)
        self.assertEqual(api["AI_OPENAI_BASE_URL"], "https://openai.example/v1")
        self.assertEqual(api["AI_VLLM_LLM_BASE_URL"], "https://llm.example/v1")
        self.assertEqual(api["AI_VLLM_STT_BASE_URL"], "https://stt.example/v1")
        self.assertEqual(worker["AI_OPENAI_API_KEY"], "openai-test")
        self.assertEqual(worker["DB_URL"], "postgresql+psycopg://runtime")
        self.assertEqual(worker["AI_VLLM_LLM_BASE_URL"], "https://llm.example/v1")
        self.assertEqual(worker["AI_VLLM_STT_BASE_URL"], "https://stt.example/v1")
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
