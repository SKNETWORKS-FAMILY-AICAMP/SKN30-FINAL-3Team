from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "manage_db_access.py"
SPEC = importlib.util.spec_from_file_location("manage_db_access", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load manage_db_access.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ManageDbAccessTest(unittest.TestCase):
    def target(self):
        return MODULE.DatabaseTarget(
            identifier="project-dev-postgres",
            resource_id="db-RESOURCE",
            endpoint="project.cluster.example.rds.amazonaws.com",
            port=5432,
            database="brokerage",
            master_secret_arn="arn:aws:secretsmanager:region:account:secret:rds",
        )

    def test_runtime_secret_payload_is_structured(self) -> None:
        payload = MODULE.runtime_secret_payload(self.target(), "generated-password")

        self.assertEqual(payload["engine"], "postgres")
        self.assertEqual(payload["username"], "app_runtime")
        self.assertEqual(payload["dbname"], "brokerage")
        self.assertEqual(payload["password"], "generated-password")
        self.assertNotIn("url", payload)

    def test_migration_url_encodes_token_and_uses_local_tunnel(self) -> None:
        token = "signed/token?with=special&characters"
        url = MODULE.migration_url(
            self.target(),
            15432,
            Path("/tmp/rds ca.pem"),
            "team-user",
            token,
        )

        self.assertNotIn(token, url)
        parsed = urlsplit(url)
        self.assertEqual(parsed.hostname, self.target().endpoint)
        self.assertEqual(parsed.port, 15432)
        self.assertEqual(parsed.username, "team-user")
        self.assertEqual(unquote(parsed.password or ""), token)
        query = parse_qs(parsed.query)
        self.assertEqual(query["hostaddr"], ["127.0.0.1"])
        self.assertEqual(query["sslmode"], ["verify-full"])

    def test_runtime_secret_parser_rejects_invalid_values(self) -> None:
        with self.assertRaises(MODULE.ToolError):
            MODULE.parse_runtime_secret("not-json")
        with self.assertRaises(MODULE.ToolError):
            MODULE.parse_runtime_secret('{"username":"dbadmin","password":"secret"}')

    def test_caller_username_requires_direct_iam_user(self) -> None:
        self.assertEqual(
            MODULE.caller_username("arn:aws:iam::123456789012:user/team/alice"),
            "alice",
        )
        with self.assertRaises(MODULE.ToolError):
            MODULE.caller_username(
                "arn:aws:sts::123456789012:assumed-role/TerraformOperatorRole/session"
            )

    def test_state_changing_commands_require_apply(self) -> None:
        with self.assertRaises(MODULE.ToolError):
            MODULE.require_apply(False, "bootstrap")
        MODULE.require_apply(True, "bootstrap")

    def test_settings_reject_wrong_account_and_region(self) -> None:
        parser = MODULE.parser()
        wrong_account = parser.parse_args(["--account-id", "123", "bootstrap"])
        with self.assertRaises(MODULE.ToolError):
            MODULE.settings_from(wrong_account)

        wrong_region = parser.parse_args(
            [
                "--account-id",
                "123456789012",
                "--region",
                "us-east-1",
                "bootstrap",
            ]
        )
        with self.assertRaises(MODULE.ToolError):
            MODULE.settings_from(wrong_region)


if __name__ == "__main__":
    unittest.main()
