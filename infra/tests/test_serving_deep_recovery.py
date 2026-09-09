"""Exercise the common saved-plan boundary with absent deep-stopped resources."""

import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

INFRA = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(INFRA / p) for p in ("scripts", "serving", "deploy/scripts")]
import serving_plan
from selection_catalog import normalize_spec


class DeepRecovery(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.infra = Path(folder.name)
        self.root = self.infra / "environments/dev"
        self.root.mkdir(parents=True)
        self.source = self.root / "dev.tfvars"
        self.source.write_text("dev_edge_enabled = false\ndev_gpu_enabled = false\n")
        self.selection = {
            "selection_id": "preserved-deep-selection",
            "f2": normalize_spec(
                "f2",
                {
                    "cloud": "aws",
                    "release_id": "consultation-v3",
                    "bucket": "synthetic-release-bucket",
                },
            ),
            "general": normalize_spec(
                "general",
                {
                    "cloud": "aws",
                    "model_profile": "qwen38-27b-fp8",
                },
            ),
        }
        profiles = {
            name: {"ami_id": "ami-012345", "image": spec["image"]}
            for name, spec in self.selection.items()
            if isinstance(spec, dict)
        }
        (self.root / "gpu-profiles.auto.tfvars.json").write_text(
            json.dumps({"gpu_profiles": profiles})
        )
        self.serving = Mock()
        self.serving.settings = SimpleNamespace(
            account_id="123456789012", region="ap-northeast-2", profile="test"
        )
        self.serving.session.get_credentials.return_value.get_frozen_credentials.return_value = SimpleNamespace(
            access_key="synthetic", secret_key="synthetic", token="synthetic"
        )
        self.serving.selection_document.side_effect = lambda: copy.deepcopy(
            self.selection
        )
        self.serving.power.describe_asg.return_value = {
            "DesiredCapacity": 0,
            "Instances": [],
        }
        self.serving.instances.return_value = []
        self.serving.endpoint.return_value = {"status": "offline"}
        self.plan = serving_plan.StartPlan(self.serving, infra=self.infra)
        self.plan.templates = Mock()
        self.plan.templates.plan.side_effect = lambda name, spec: {
            "workload": name,
            "image": spec["image"],
        }
        self.commands = []
        self.applied = False
        self.drift = False
        self.plan.terraform = self.terraform
        self.quiet = redirect_stdout(io.StringIO())
        self.quiet.__enter__()
        self.addCleanup(self.quiet.__exit__, None, None, None)

    def terraform(self, *args):
        self.commands.append(args)
        if args[0] == "plan":
            output = next(
                a.removeprefix("-out=") for a in args if a.startswith("-out=")
            )
            (self.root / output).write_bytes(b"synthetic Terraform plan")
        if args[0] == "apply":
            self.applied = True
        if args[0] != "show":
            return ""
        variables = json.loads(
            (self.root / "serving-selection.auto.tfvars.json").read_text()
        )
        tags = {
            "Project": "project",
            "Environment": "dev",
            "Name": "project-dev-app-asg",
        }
        changes = [{"address": "aws_lb.app[0]", "change": {"actions": ["create"]}}]
        changes.extend(
            {
                "address": f'aws_instance.gpu["{name}"]',
                "change": {"actions": ["create"]},
            }
            for name in variables["gpu_provisioned_workloads"]
        )
        return json.dumps(
            {
                "variables": {
                    key: {"value": value}
                    for key, value in {**variables, "project_name": "project"}.items()
                },
                "resource_changes": changes if not self.applied or self.drift else [],
                "planned_values": {
                    "root_module": {
                        "resources": [
                            {
                                "address": "aws_codedeploy_deployment_group.backend",
                                "values": {
                                    "autoscaling_groups": [],
                                    "ec2_tag_set": [
                                        {
                                            "ec2_tag_filter": [
                                                {
                                                    "key": k,
                                                    "value": v,
                                                    "type": "KEY_AND_VALUE",
                                                }
                                            ]
                                        }
                                        for k, v in tags.items()
                                    ],
                                },
                            }
                        ]
                    }
                },
            }
        )

    def build(self):
        with patch.object(serving_plan, "run", return_value=""):
            return self.plan.build(rates={"f2": 1, "general": 2})

    def test_absent_aws_gpus_and_edge_use_sealed_apply_and_drift(self):
        before = copy.deepcopy(self.selection)
        data = self.build()
        inputs = data["terraform_inputs"]
        self.assertTrue(inputs["dev_edge_enabled"])
        self.assertTrue(inputs["dev_gpu_enabled"])
        self.assertEqual(inputs["app_deployment_mode"], "maintenance")
        self.assertEqual(inputs["gpu_provisioned_workloads"], ["f2", "general"])
        self.plan.templates.plan.assert_not_called()
        self.assertFalse(self.applied)
        approved = []
        self.plan.apply(data, confirm_fn=approved.append)
        self.assertEqual(len(approved), 1)
        self.assertIn(("apply", "-input=false", "dev-serving.tfplan"), self.commands)
        self.assertEqual(
            self.commands[-1], ("show", "-json", "dev-serving-drift.tfplan")
        )
        self.assertEqual(before, self.selection)
        self.serving.write.assert_not_called()

    def test_mixed_cloud_restores_only_selected_aws_capacity(self):
        self.selection["f2"] = normalize_spec(
            "f2",
            {
                "cloud": "runpod",
                "release_id": "consultation-v3",
                "bucket": "synthetic-release-bucket",
            },
        )
        data = self.build()
        self.assertEqual(
            data["terraform_inputs"]["gpu_provisioned_workloads"], ["general"]
        )
        self.assertEqual([row["workload"] for row in data["templates"]], ["f2"])
        self.plan.apply(data, confirm_fn=lambda _: None)
        self.plan.templates.apply.assert_called_once()

    def test_input_change_after_review_blocks_terraform_apply(self):
        data = self.build()
        self.source.write_text("dev_edge_enabled = true\n")
        with self.assertRaises(ValueError):
            self.plan.apply(data, confirm_fn=lambda _: None)
        self.assertFalse(self.applied)
        self.plan.templates.apply.assert_not_called()

    def test_drift_prevents_success_after_restore(self):
        data = self.build()
        self.drift = True
        with self.assertRaisesRegex(serving_plan.ToolError, "drift remains"):
            self.plan.apply(data, confirm_fn=lambda _: None)
        self.assertTrue(self.applied)


if __name__ == "__main__":
    unittest.main()
