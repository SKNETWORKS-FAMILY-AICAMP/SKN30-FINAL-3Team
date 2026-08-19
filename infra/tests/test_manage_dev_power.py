from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "manage_dev_power.py"
SPEC = importlib.util.spec_from_file_location("manage_dev_power", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load manage_dev_power.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ManageDevPowerTest(unittest.TestCase):
    def settings(self):
        return MODULE.Settings(
            account_id="123456789012",
            profile="skn30-session",
            region="ap-northeast-2",
            project="skn30-final-3team",
            operator_role="TerraformOperatorRole",
            timeout_seconds=MODULE.DEFAULT_TIMEOUT_SECONDS,
        )

    def test_identity_rejects_wrong_account_and_root(self) -> None:
        MODULE.validate_identity(
            {
                "Account": "123456789012",
                "Arn": "arn:aws:iam::123456789012:user/infra",
            },
            "123456789012",
        )
        with self.assertRaises(MODULE.ToolError):
            MODULE.validate_identity(
                {
                    "Account": "999999999999",
                    "Arn": "arn:aws:iam::999999999999:user/infra",
                },
                "123456789012",
            )
        with self.assertRaises(MODULE.ToolError):
            MODULE.validate_identity(
                {
                    "Account": "123456789012",
                    "Arn": "arn:aws:iam::123456789012:root",
                },
                "123456789012",
            )

    def test_expected_tags_are_required(self) -> None:
        tags = [
            {"Key": "Project", "Value": "skn30-final-3team"},
            {"Key": "Environment", "Value": "dev"},
            {"Key": "ManagedBy", "Value": "Terraform"},
        ]
        MODULE.validate_tags(tags, self.settings(), "resource")

        with self.assertRaises(MODULE.ToolError):
            MODULE.validate_tags(tags[:-1], self.settings(), "resource")

    def test_asg_power_config_requires_zero_to_one_range(self) -> None:
        MODULE.validate_asg_power_config(
            {"MinSize": 0, "DesiredCapacity": 1, "MaxSize": 1}
        )
        MODULE.validate_asg_power_config(
            {"MinSize": 0, "DesiredCapacity": 0, "MaxSize": 1}
        )

        with self.assertRaises(MODULE.ToolError):
            MODULE.validate_asg_power_config(
                {"MinSize": 1, "DesiredCapacity": 1, "MaxSize": 1}
            )
        with self.assertRaises(MODULE.ToolError):
            MODULE.validate_asg_power_config(
                {"MinSize": 0, "DesiredCapacity": 2, "MaxSize": 2}
            )

    def test_rds_transition_actions_are_restricted(self) -> None:
        self.assertEqual(MODULE.rds_start_action("stopped"), "start")
        self.assertEqual(MODULE.rds_start_action("stopping"), "wait-stopped")
        self.assertEqual(MODULE.rds_stop_action("available"), "stop")
        self.assertEqual(MODULE.rds_stop_action("starting"), "wait-available")

        with self.assertRaises(MODULE.ToolError):
            MODULE.rds_start_action("failed")
        with self.assertRaises(MODULE.ToolError):
            MODULE.rds_stop_action("modifying")

    def test_state_changes_require_explicit_confirmation(self) -> None:
        with self.assertRaises(MODULE.ToolError):
            MODULE.require_apply(False, "start")
        MODULE.require_apply(True, "start")

        with self.assertRaises(MODULE.ToolError):
            MODULE.require_stop_confirmation(False)
        MODULE.require_stop_confirmation(True)

    def test_settings_reject_invalid_account_region_and_timeout(self) -> None:
        command_parser = MODULE.parser()
        wrong_account = command_parser.parse_args(
            ["--account-id", "123", "status"]
        )
        with self.assertRaises(MODULE.ToolError):
            MODULE.settings_from(wrong_account)

        wrong_region = command_parser.parse_args(
            [
                "--account-id",
                "123456789012",
                "--region",
                "us-east-1",
                "status",
            ]
        )
        with self.assertRaises(MODULE.ToolError):
            MODULE.settings_from(wrong_region)

        wrong_timeout = command_parser.parse_args(
            [
                "--account-id",
                "123456789012",
                "--timeout-seconds",
                "30",
                "status",
            ]
        )
        with self.assertRaises(MODULE.ToolError):
            MODULE.settings_from(wrong_timeout)

        expired_role_timeout = command_parser.parse_args(
            [
                "--account-id",
                "123456789012",
                "--timeout-seconds",
                str(MODULE.ROLE_SESSION_SECONDS),
                "status",
            ]
        )
        with self.assertRaises(MODULE.ToolError):
            MODULE.settings_from(expired_role_timeout)


if __name__ == "__main__":
    unittest.main()
