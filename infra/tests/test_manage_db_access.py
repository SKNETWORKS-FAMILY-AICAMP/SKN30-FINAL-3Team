from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock
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

    def test_runtime_secret_target_must_match_rds(self) -> None:
        payload = MODULE.runtime_secret_payload(self.target(), "generated-password")
        MODULE.validate_runtime_secret_target(self.target(), payload)

        payload["host"] = "stale.example.rds.amazonaws.com"
        with self.assertRaisesRegex(
            MODULE.ToolError, "database target metadata does not match RDS"
        ):
            MODULE.validate_runtime_secret_target(self.target(), payload)

    def test_fixed_role_contract_requires_iam_migrator_membership(self) -> None:
        class DummyCursor:
            def __init__(self, memberships: dict[tuple[str, str], bool]) -> None:
                self.memberships = memberships
                self.result: list[tuple[object, ...]] = []

            def execute(self, query: object, params: object = None) -> None:
                if "FROM pg_roles" in str(query):
                    self.result = [
                        ("app_owner", False),
                        ("app_rw", False),
                        ("app_runtime", True),
                        ("app_migrator", True),
                    ]
                    return
                member, granted = params
                self.result = [(self.memberships[(member, granted)],)]

            def fetchall(self) -> list[tuple[object, ...]]:
                return self.result

            def fetchone(self) -> tuple[object, ...] | None:
                return self.result[0] if self.result else None

        memberships = {
            ("app_runtime", "app_rw"): True,
            ("app_migrator", "rds_iam"): True,
            ("app_migrator", "app_owner"): True,
        }
        MODULE.verify_fixed_role_contract(DummyCursor(memberships))

        memberships[("app_migrator", "rds_iam")] = False
        with self.assertRaisesRegex(MODULE.ToolError, "rds_iam"):
            MODULE.verify_fixed_role_contract(DummyCursor(memberships))

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

    def test_create_session_account_runs_backend_manage_with_iam_tunnel(self) -> None:
        settings = MODULE.Settings(
            account_id="123456789012",
            profile="skn30-session",
            region="ap-northeast-2",
            project="skn30-final-3team",
            local_port=15432,
            operator_role="TerraformOperatorRole",
        )
        direct = mock.MagicMock()
        sts = mock.MagicMock()
        sts.get_caller_identity.return_value = {
            "Arn": "arn:aws:iam::123456789012:user/team/alice"
        }
        rds = mock.MagicMock()
        rds.generate_db_auth_token.return_value = "signed/token"
        direct.client.side_effect = lambda service: {"sts": sts, "rds": rds}[service]
        completed = mock.MagicMock(returncode=0)

        with (
            mock.patch.object(MODULE, "base_session", return_value=direct),
            mock.patch.object(MODULE, "describe_database", return_value=self.target()),
            mock.patch.object(
                MODULE, "find_app_instance", return_value="i-0123456789abcdef0"
            ),
            mock.patch.object(
                MODULE, "ensure_ca_bundle", return_value=Path("/tmp/rds-ca.pem")
            ),
            mock.patch.object(MODULE, "PortForward") as port_forward,
            mock.patch.object(MODULE.subprocess, "run", return_value=completed) as run,
        ):
            MODULE.create_session_account(
                settings,
                brokerage_name="개발 중개사무소",
                login_id="developer",
                display_name="Developer",
                role="OWNER",
                apply=True,
            )

        port_forward.assert_called_once_with(
            direct, "i-0123456789abcdef0", self.target(), 15432
        )
        command = run.call_args.args[0]
        self.assertEqual(
            command[:6],
            [
                "uv",
                "run",
                "--frozen",
                "python",
                "src/manage.py",
                "create-development-user",
            ],
        )
        self.assertIn("개발 중개사무소", command)
        environment = run.call_args.kwargs["env"]
        self.assertEqual(environment["APP_ENV"], "local")
        self.assertEqual(environment["AUTH_DEVELOPMENT_ENABLED"], "false")
        self.assertEqual(environment["DB_TARGET"], "development")
        self.assertEqual(environment["PGOPTIONS"], "-c role=app_owner")
        self.assertNotIn("signed/token", environment["DB_URL"])
        self.assertEqual(
            unquote(urlsplit(environment["DB_URL"]).password or ""), "signed/token"
        )

    def test_seed_f3_uses_fixed_files_and_private_iam_token(self) -> None:
        settings = MODULE.Settings(
            account_id="123456789012",
            profile="skn30-session",
            region="ap-northeast-2",
            project="skn30-final-3team",
            local_port=15432,
            operator_role="TerraformOperatorRole",
        )
        direct = mock.MagicMock()
        sts = mock.MagicMock()
        sts.get_caller_identity.return_value = {
            "Arn": "arn:aws:iam::123456789012:user/team/alice"
        }
        rds = mock.MagicMock()
        rds.generate_db_auth_token.return_value = "signed/token"
        direct.client.side_effect = lambda service: {"sts": sts, "rds": rds}[service]
        applied = mock.MagicMock(returncode=0)
        verified = mock.MagicMock(
            returncode=0,
            stdout="\n".join(f"check-{index}|1|1|PASS" for index in range(29))
            + "\n",
        )

        with (
            mock.patch.object(MODULE.shutil, "which", return_value="/usr/bin/psql"),
            mock.patch.object(MODULE, "base_session", return_value=direct),
            mock.patch.object(MODULE, "describe_database", return_value=self.target()),
            mock.patch.object(
                MODULE, "find_app_instance", return_value="i-0123456789abcdef0"
            ),
            mock.patch.object(
                MODULE, "ensure_ca_bundle", return_value=Path("/tmp/rds-ca.pem")
            ),
            mock.patch.object(MODULE, "PortForward") as port_forward,
            mock.patch.object(
                MODULE.subprocess, "run", side_effect=[applied, verified]
            ) as run,
        ):
            MODULE.seed_f3(settings, apply=True)

        port_forward.assert_called_once_with(
            direct, "i-0123456789abcdef0", self.target(), 15432
        )
        apply_command = run.call_args_list[0].args[0]
        verify_command = run.call_args_list[1].args[0]
        self.assertEqual(apply_command.count("-f"), 2)
        self.assertIn(str(MODULE.F3_SEED_RESET), apply_command)
        self.assertIn(str(MODULE.F3_SEED_DATA), apply_command)
        self.assertIn(str(MODULE.F3_SEED_VERIFY), verify_command)
        environment = run.call_args_list[0].kwargs["env"]
        self.assertEqual(environment["PGPASSWORD"], "signed/token")
        self.assertEqual(environment["PGHOSTADDR"], "127.0.0.1")
        self.assertEqual(environment["PGSSLMODE"], "verify-full")
        self.assertEqual(environment["PGOPTIONS"], "-c role=app_owner")
        self.assertNotIn("signed/token", " ".join(apply_command))
        self.assertNotIn("signed/token", " ".join(verify_command))

    def test_seed_f3_verification_rejects_fail_or_wrong_count(self) -> None:
        passing = "\n".join(f"check-{index}|1|1|PASS" for index in range(29))
        MODULE.verify_f3_seed_output(passing)

        with self.assertRaisesRegex(MODULE.ToolError, "reported FAIL"):
            MODULE.verify_f3_seed_output(passing.replace("|PASS", "|FAIL", 1))
        with self.assertRaisesRegex(MODULE.ToolError, "unexpected check count"):
            MODULE.verify_f3_seed_output("check|1|1|PASS")

    def test_ensure_role_formats_password_as_literal(self) -> None:
        executed: list[tuple[object, ...]] = []

        class DummyCursor:
            def execute(self, query: object, params: object = None) -> None:
                executed.append((query, params))

            def fetchone(self) -> tuple[int] | None:
                return None

        cursor = DummyCursor()
        MODULE.ensure_role(
            cursor, "app_runtime", login=True, password="secret'password"
        )
        ddl_calls = [
            (q.as_string() if hasattr(q, "as_string") else str(q), p)
            for q, p in executed
            if "ALTER ROLE" in (q.as_string() if hasattr(q, "as_string") else str(q))
        ]
        self.assertTrue(any("PASSWORD 'secret''password'" in q for q, _ in ddl_calls))
        self.assertTrue(all(p is None for _, p in ddl_calls))

    def test_client_info_prints_token_once_without_embedding_it_in_command(
        self,
    ) -> None:
        settings = MODULE.Settings(
            account_id="123456789012",
            profile="skn30-session",
            region="ap-northeast-2",
            project="skn30-final-3team",
            local_port=15432,
            operator_role="TerraformOperatorRole",
        )
        token = "signed/token?with=special&characters"

        output = MODULE.render_client_info(
            settings,
            self.target(),
            "i-0123456789abcdef0",
            "team-user",
            token,
            Path("/tmp/rds ca.pem"),
        )

        self.assertEqual(output.count(token), 1)
        self.assertNotIn("PGPASSWORD", output)
        self.assertNotIn("--set=sslmode", output)
        self.assertIn("PGHOST=project.cluster.example.rds.amazonaws.com", output)
        self.assertIn("PGHOSTADDR=127.0.0.1", output)
        self.assertIn("PGSSLMODE=verify-full", output)
        self.assertIn("PGSSLROOTCERT='/tmp/rds ca.pem'", output)
        self.assertIn("psql -W", output)
        self.assertIn("SSL Mode : verify-ca", output)


if __name__ == "__main__":
    unittest.main()
