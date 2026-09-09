"""Shared selection migration, quiescence and optimistic stale-write regressions."""

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "scripts"),
    str(ROOT / "serving"),
    str(ROOT / "deploy/scripts"),
]
from manage_dev_power import ToolError
from serving_plan import desired_inputs, validate_intent
from serving_selection import document, require_stopped, save


def legacy():
    return {
        "f2": {
            "cloud": "runpod",
            "gpu_id": "NVIDIA RTX A5000",
            "release_id": "consultation-v3",
            "bucket": "private-models",
            "allow_dev_release": False,
        },
        "general": {
            "cloud": "runpod",
            "gpu_id": "NVIDIA L40S",
            "model_profile": "qwen38-27b-fp8",
        },
    }


class Selection(unittest.TestCase):
    def fixture(self):
        c = Mock()
        c.power.describe_asg.return_value = {"DesiredCapacity": 0, "Instances": []}
        c.endpoint.return_value = {"status": "offline"}
        c.instances.return_value = []
        c.managed_pods.return_value = []
        c.selection_document.return_value = document(legacy())
        c.session.client.return_value.get_caller_identity.return_value = {
            "Arn": "arn:aws:sts::123456789012:assumed-role/operator/user"
        }
        return c

    def test_migration_preserves_model_and_stable_identity_without_write(self):
        before = legacy()
        value = document(before)
        self.assertEqual(before, legacy())
        self.assertEqual(value, document(before))
        self.assertEqual(value["general"]["model_profile"], "qwen38-27b-fp8")
        self.assertEqual(value["f2"]["release_id"], "consultation-v3")
        self.assertEqual(document(value), value)

    def test_save_updates_only_selected_workload_and_never_starts(self):
        c = self.fixture()
        before = c.selection_document.return_value
        with patch("serving_selection.emit"):
            save(
                c,
                {"general": {"cloud": "aws", "model_profile": "qwen38-27b-fp8"}},
                apply=True,
            )
        value = c.write.call_args.args[1]
        self.assertEqual(value["f2"], before["f2"])
        self.assertEqual(value["general"]["hardware_profile"], "aws-g6e-2xlarge")
        self.assertNotIn("gpu_id", value["general"])
        self.assertNotEqual(value["selection_id"], before["selection_id"])
        c.power.start.assert_not_called()
        c.prepare.assert_not_called()

    def test_preview_never_writes(self):
        c = self.fixture()
        with patch("serving_selection.emit"):
            save(c, {"general": legacy()["general"]}, apply=False)
        c.write.assert_not_called()

    def test_running_resources_each_block_selection(self):
        for condition in ("host", "endpoint", "gpu", "pod"):
            with self.subTest(condition=condition):
                c = self.fixture()
                if condition == "host":
                    c.power.describe_asg.return_value["DesiredCapacity"] = 1
                if condition == "endpoint":
                    c.endpoint.return_value["status"] = "active"
                if condition == "gpu":
                    c.instances.return_value = [{"State": {"Name": "running"}}]
                if condition == "pod":
                    c.managed_pods.return_value = [{"id": "owned"}]
                with self.assertRaises(ToolError):
                    require_stopped(c)
                c.write.assert_not_called()

    def test_concurrent_selection_change_rejects_write(self):
        c = self.fixture()
        before = c.selection_document.return_value
        changed = {**before, "selection_id": "another-selection"}
        c.selection_document.side_effect = [before, changed]
        with (
            patch("serving_selection.emit"),
            self.assertRaisesRegex(ToolError, "changed"),
        ):
            save(c, {"general": legacy()["general"]}, apply=True)
        c.write.assert_not_called()

    def test_invalid_provider_hardware_and_release_are_rejected(self):
        for spec in (
            {"cloud": "cpu"},
            {"cloud": "runpod", "gpu_id": "arbitrary"},
            {"cloud": "runpod", "gpu_id": "NVIDIA L40S", "model_profile": "made-up"},
        ):
            with self.subTest(spec=spec), self.assertRaises((ValueError, ToolError)):
                document({**legacy(), "general": spec})

    def test_public_model_and_capacity_derive_from_same_choice(self):
        chosen = document(legacy())
        chosen["general"]["cloud"] = "aws"
        value = desired_inputs(
            chosen,
            {"general": {"ami_id": "ami-123", "image": "old", "root_volume_gb": 160}},
            set(),
        )
        self.assertEqual(
            value["general_model_selection"]["model"], "Qwen/Qwen3.8-27B-FP8"
        )
        self.assertEqual(
            value["gpu_profiles"]["general"]["image"], chosen["general"]["image"]
        )
        self.assertEqual(value["gpu_provisioned_workloads"], ["general"])
        self.assertEqual(value["app_deployment_mode"], "maintenance")

    def test_unknown_retained_profile_cannot_be_deleted_by_missing_local_input(self):
        with self.assertRaises(ToolError):
            desired_inputs(document(legacy()), {}, {"f2"})

    def test_conflicting_terraform_override_fails_before_apply(self):
        expected = {"general_model_selection": {"provider": "vllm", "model": "desired"}}
        with self.assertRaises(ToolError):
            validate_intent(
                {
                    "variables": {
                        "general_model_selection": {
                            "value": {"provider": "vllm", "model": "old"}
                        }
                    }
                },
                expected,
            )
