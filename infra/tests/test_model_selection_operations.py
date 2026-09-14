"""Remote selection must never change lifecycle or call a model implicitly."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import manage_serving as serving
import serving_deployment


class RemoteSelection(unittest.TestCase):
    def test_dispatches_one_capability_without_lifecycle_or_inference(self):
        controller = Mock()
        controller.app_id.return_value = "i-fixture"
        with (
            patch.object(
                sys,
                "argv",
                [
                    "manage_serving.py",
                    "--account-id",
                    "123456789012",
                    "activate-general",
                    "7",
                    "--capability",
                    "CHATBOT",
                    "--apply",
                    "--workloads-stopped-confirmed",
                ],
            ),
            patch.object(serving.power, "base_session"),
            patch.object(serving.power, "assume_operator"),
            patch.object(serving, "Serving", return_value=controller),
            patch.object(serving, "emit"),
        ):
            self.assertEqual(serving.main(), 0)
        controller.command.assert_called_once_with(
            "i-fixture",
            "/opt/brokerage/revision/scripts/serving_maintenance.sh activate-general 7 CHATBOT",
            timeout=360,
        )
        controller.app.assert_not_called()
        controller.application_smoke.assert_not_called()
        controller.prepare.assert_not_called()
        controller.write.assert_not_called()

    def test_invalid_capability_rejected_before_cloud_access(self):
        with self.assertRaises(SystemExit), patch("sys.stderr"):
            serving.parser().parse_args(
                [
                    "activate-general",
                    "7",
                    "--capability",
                    "ANYTHING",
                ]
            )

    def run_maintenance(self, running: bool):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            common = root / "common.sh"
            common.write_text("""
require_backend_image() { :; }
compose() {
  if [[ "$1" == ps ]]; then
    [[ "$RUNNING" != true ]] || echo fixture-running
    return 0
  fi
  echo "compose $*" >> "$TRACE"
}
python3() { echo render >> "$TRACE"; }
""")
            script = root / "maintenance.sh"
            script.write_text(
                (ROOT / "deploy/scripts/serving_maintenance.sh")
                .read_text()
                .replace(
                    "source /opt/brokerage/revision/scripts/common.sh",
                    f"source {common}",
                )
            )
            trace = root / "trace"
            env = {
                **os.environ,
                "RUNNING": str(running).lower(),
                "TRACE": str(trace),
                "REVISION_DIR": str(root),
                "API_ENV_FILE": "api",
                "WORKER_ENV_FILE": "worker",
                "MIGRATION_ENV_FILE": "migration",
            }
            result = subprocess.run(
                ["bash", str(script), "activate-general", "7", "CHATBOT"],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            return result.returncode, trace.read_text() if trace.exists() else ""

    def test_remote_shell_requires_stopped_workloads(self):
        code, trace = self.run_maintenance(True)
        self.assertNotEqual(code, 0)
        self.assertEqual(trace, "")

    def test_remote_shell_refreshes_config_then_only_runs_new_selection(self):
        code, trace = self.run_maintenance(False)
        self.assertEqual(code, 0)
        self.assertEqual(
            trace.splitlines(),
            [
                "render",
                (
                    "compose run --rm --no-deps -T worker python src/model_selection.py "
                    "--brokerage-id 7 --capability CHATBOT --shared-dev --apply --workloads-stopped"
                ),
            ],
        )


class DeploymentPreparation(unittest.TestCase):
    def controller(self):
        controller = serving.Serving.__new__(serving.Serving)
        controller.prefix = "fixture-dev"
        controller.settings = serving.power.Settings(
            "123456789012", "fixture", "ap-northeast-2", "fixture", "operator", 60
        )
        controller.session = Mock()
        controller.session.client.return_value.get_deployment_group.return_value = {
            "deploymentGroupInfo": {
                "autoScalingGroups": [],
                "deploymentStyle": {
                    "deploymentType": "IN_PLACE",
                    "deploymentOption": "WITHOUT_TRAFFIC_CONTROL",
                },
                "ec2TagSet": {
                    "ec2TagSetList": [
                        [{"Key": key, "Value": value, "Type": "KEY_AND_VALUE"}]
                        for key, value in (
                            ("Project", "fixture"),
                            ("Environment", "dev"),
                            ("Name", "fixture-dev-app-asg"),
                        )
                    ]
                },
            }
        }
        controller.selection = Mock(
            return_value={
                "f2": None,
                "general": {
                    "cloud": "runpod",
                    "gpu_id": "NVIDIA L40S",
                    "model_profile": "qwen38-27b-fp8",
                },
            }
        )
        controller.ssm = Mock()
        public = {"PROVIDER": "vllm", "MODEL": "Qwen/Qwen3.8-27B-FP8"}
        controller.ssm.get_parameter.side_effect = lambda **kw: {
            "Parameter": {"Value": public[kw["Name"].rsplit("_", 1)[1]]}
        }
        events = []
        controller.no_deployment = Mock(side_effect=lambda: events.append("preflight"))
        controller.app_id = Mock(return_value="existing-app")
        controller.app = Mock(side_effect=lambda action: events.append("app-" + action))
        controller.prepare = Mock(
            side_effect=lambda *_: events.append("gpu-ready") or {"id": "fixture"}
        )
        controller.activate = Mock(side_effect=lambda *_: events.append("endpoint"))
        controller.power = Mock()
        controller.power.start.side_effect = lambda: events.append("power")
        controller.restore_application = Mock()
        controller.application_smoke = Mock()
        return controller, events

    def test_preparation_uses_shared_reviewed_lifecycle(self):
        controller, _ = self.controller()
        with patch("serving_lifecycle.Lifecycle") as lifecycle:
            controller.prepare_deployment(apply=True, hours=2, rates={"f2": 1})
        lifecycle.assert_called_once_with(controller)
        lifecycle.return_value.run.assert_called_once_with(
            prepare_only=True, apply=True, hours=2, rates={"f2": 1}
        )
        controller.restore_application.assert_not_called()
        controller.application_smoke.assert_not_called()

    def test_missing_or_mismatched_profile_blocks_every_mutation(self):
        for selected in (None, {"model_profile": "qwen3-14b-awq"}):
            controller, events = self.controller()
            controller.selection.return_value["general"] = selected
            with self.assertRaises(serving.ToolError):
                serving_deployment.require_general_selection(
                    controller.ssm, controller.prefix, controller.selection()
                )
            self.assertEqual(events, [])
            controller.power.start.assert_not_called()

    def test_automatic_launch_association_blocks_gpu_before_mutation(self):
        controller, events = self.controller()
        group = (
            controller.session.client.return_value.get_deployment_group.return_value[
                "deploymentGroupInfo"
            ]
        )
        group["autoScalingGroups"] = [{"name": "fixture-dev-app"}]
        with self.assertRaises(serving.ToolError):
            serving_deployment.require_maintenance_deployment(
                controller.session, controller.settings
            )
        self.assertEqual(events, [])
        controller.prepare.assert_not_called()
        controller.power.start.assert_not_called()

    def test_maintenance_traffic_control_is_rejected_before_start(self):
        for style in (
            {},
            {"deploymentType": "IN_PLACE", "deploymentOption": "WITH_TRAFFIC_CONTROL"},
            {
                "deploymentType": "BLUE_GREEN",
                "deploymentOption": "WITHOUT_TRAFFIC_CONTROL",
            },
        ):
            with self.subTest(style=style):
                controller, events = self.controller()
                group = controller.session.client.return_value.get_deployment_group.return_value[
                    "deploymentGroupInfo"
                ]
                group["deploymentStyle"] = style
                with self.assertRaises(serving.ToolError):
                    serving_deployment.require_maintenance_deployment(
                        controller.session, controller.settings
                    )
                self.assertEqual(events, [])
                controller.power.start.assert_not_called()

    def test_maintenance_without_traffic_control_is_accepted(self):
        controller, _ = self.controller()
        serving_deployment.require_maintenance_deployment(
            controller.session, controller.settings
        )

    def test_broad_or_wrong_maintenance_tag_sets_are_rejected(self):
        for groups in (
            [],
            [[{"Key": "Project", "Value": "fixture", "Type": "KEY_AND_VALUE"}]],
            [
                [{"Key": key, "Value": value, "Type": "KEY_AND_VALUE"}]
                for key, value in (
                    ("Project", "fixture"),
                    ("Environment", "dev"),
                    ("Name", "fixture-dev-app"),
                )
            ],
        ):
            controller, events = self.controller()
            group = controller.session.client.return_value.get_deployment_group.return_value[
                "deploymentGroupInfo"
            ]
            group["ec2TagSet"]["ec2TagSetList"] = groups
            with self.assertRaises(serving.ToolError):
                serving_deployment.require_maintenance_deployment(
                    controller.session, controller.settings
                )
            self.assertEqual(events, [])
            controller.prepare.assert_not_called()

    def test_start_uses_same_reviewed_lifecycle(self):
        controller, _ = self.controller()
        with patch("serving_lifecycle.Lifecycle") as lifecycle:
            controller.start(apply=False)
        lifecycle.return_value.run.assert_called_once_with(apply=False)
        controller.restore_application.assert_not_called()


if __name__ == "__main__":
    unittest.main()
