"""Saved-plan purpose and recursive dependency changes are checked at both boundaries."""

import copy
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import plan_guard


def first_deploy():
    return {
        "variables": {
            name: {"value": value}
            for name, value in {
                "app_deployment_mode": "maintenance",
                "dev_edge_enabled": True,
                "dev_gpu_enabled": True,
                "project_name": "fixture",
            }.items()
        },
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
                                            "key": key,
                                            "value": value,
                                            "type": "KEY_AND_VALUE",
                                        }
                                    ]
                                }
                                for key, value in (
                                    ("Project", "fixture"),
                                    ("Environment", "dev"),
                                    ("Name", "fixture-dev-app-asg"),
                                )
                            ],
                        },
                    }
                ]
            }
        },
        "sensitive_fixture": "SENSITIVE_OUTPUT_MUST_NOT_ESCAPE",
    }


class PlanGuardTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.infra = Path(self.directory.name)
        self.root = self.infra / "environments/dev"
        self.root.mkdir(parents=True)
        self.plan = self.root / "dev.tfplan"
        self.plan.write_bytes(b"binary saved plan fixture")

    def test_recursive_root_files_and_docker_inputs_change_invalidate_sealed_plan(self):
        for root_name, source in (
            ("bootstrap", "nested/policies/operator.policy"),
            ("bootstrap", "nested/templates/bootstrap.tpl"),
            ("environments/dev", "nested/modules/role/main.tf"),
            ("environments/dev", "nested/assets/settings.txt"),
            ("environments/dev", "nested/templates/host.tftpl"),
            ("environments/dev", "../../serving/Dockerfile"),
            ("environments/dev", "../../runpod/Dockerfile.runtime"),
            ("environments/dev", "../../deploy/.dockerignore"),
        ):
            with self.subTest(root=root_name, source=source):
                root = self.infra / root_name
                root.mkdir(parents=True, exist_ok=True)
                plan = root / "fixture.tfplan"
                plan.write_bytes(b"saved plan")
                path = root / source
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("before")
                plan_guard.seal(self.infra, plan)
                plan_guard.check(self.infra, plan)
                path.write_text("after")
                with self.assertRaises(ValueError):
                    plan_guard.check(self.infra, plan)
                path.unlink()

    def test_added_and_deleted_recursive_inputs_invalidate(self):
        source = self.root / "module/policy.json"
        source.parent.mkdir()
        plan_guard.seal(self.infra, self.plan)
        source.write_text("{}")
        with self.assertRaises(ValueError):
            plan_guard.check(self.infra, self.plan)
        plan_guard.seal(self.infra, self.plan)
        source.unlink()
        with self.assertRaises(ValueError):
            plan_guard.check(self.infra, self.plan)

    def test_private_env_cache_and_plan_sidecars_are_not_inputs(self):
        plan_guard.seal(self.infra, self.plan)
        for relative in (
            ".env",
            ".terraform/modules/example/main.tf",
            "__pycache__/generated.py",
            "other.plan-meta.json",
        ):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("private fixture")
        plan_guard.check(self.infra, self.plan)

    def test_symlink_file_and_directory_fail_closed(self):
        target = self.infra / "external"
        target.mkdir()
        (target / "policy.tpl").write_text("fixture")
        for name, destination in (
            ("linked.tpl", target / "policy.tpl"),
            ("linked_module", target),
        ):
            link = self.root / name
            link.symlink_to(destination)
            with self.assertRaises(ValueError):
                plan_guard.seal(self.infra, self.plan)
            link.unlink()

    def test_old_metadata_schema_requires_regeneration(self):
        plan_guard.seal(self.infra, self.plan)
        sidecar = self.plan.with_suffix(".plan-meta.json")
        data = json.loads(sidecar.read_text())
        data.pop("schema_version")
        sidecar.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            plan_guard.check(self.infra, self.plan)

    def test_first_deploy_seal_and_check_inspect_actual_saved_plan_without_leaking(
        self,
    ):
        plan = self.root / plan_guard.FIRST_DEPLOY_PLAN
        plan.write_bytes(b"fixture")
        response = subprocess.CompletedProcess([], 0, json.dumps(first_deploy()), "")
        output = io.StringIO()
        with (
            patch.object(plan_guard.subprocess, "run", return_value=response) as run,
            redirect_stdout(output),
        ):
            plan_guard.seal(self.infra, plan)
            plan_guard.check(self.infra, plan)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args.args[0][-3:], ["show", "-json", plan.name])
        self.assertNotIn("SENSITIVE_OUTPUT_MUST_NOT_ESCAPE", output.getvalue())
        self.assertNotIn(
            "SENSITIVE_OUTPUT_MUST_NOT_ESCAPE",
            plan.with_suffix(".plan-meta.json").read_text(),
        )

    def test_first_deploy_rejects_omitted_mode_automatic_and_wrong_targets_at_seal_and_check(
        self,
    ):
        valid = first_deploy()
        invalid = []
        for mode in (None, "automatic"):
            payload = copy.deepcopy(valid)
            if mode is None:
                payload["variables"].pop("app_deployment_mode")
            else:
                payload["variables"]["app_deployment_mode"]["value"] = mode
            invalid.append(payload)
        for change in ("asg", "wrong_name", "or_group", "edge_off"):
            payload = copy.deepcopy(valid)
            values = payload["planned_values"]["root_module"]["resources"][0]["values"]
            if change == "asg":
                values["autoscaling_groups"] = ["fixture-dev-app"]
            elif change == "wrong_name":
                values["ec2_tag_set"][2]["ec2_tag_filter"][0]["value"] = (
                    "fixture-dev-app"
                )
            elif change == "or_group":
                values["ec2_tag_set"] = [
                    {
                        "ec2_tag_filter": [
                            tag["ec2_tag_filter"][0] for tag in values["ec2_tag_set"]
                        ]
                    }
                ]
            else:
                payload["variables"]["dev_edge_enabled"]["value"] = False
            invalid.append(payload)
        plan = self.root / plan_guard.FIRST_DEPLOY_PLAN
        plan.write_bytes(b"fixture")
        with patch.object(plan_guard.subprocess, "run") as run:
            for payload in invalid:
                run.return_value = subprocess.CompletedProcess(
                    [], 0, json.dumps(payload), ""
                )
                with self.assertRaises(ValueError):
                    plan_guard.seal(self.infra, plan)
                run.return_value = subprocess.CompletedProcess(
                    [], 0, json.dumps(valid), ""
                )
                plan_guard.seal(self.infra, plan)
                run.return_value = subprocess.CompletedProcess(
                    [], 0, json.dumps(payload), ""
                )
                with self.assertRaises(ValueError):
                    plan_guard.check(self.infra, plan)

    def test_first_deploy_accepts_actual_cli_boolean_tokens_but_rejects_false_and_missing(
        self,
    ):
        payload = first_deploy()
        for name in ("dev_edge_enabled", "dev_gpu_enabled"):
            payload["variables"][name]["value"] = "true"
        plan_guard.validate_first_deploy(payload)
        for value in ("false", False, None, "TRUE", 1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                bad = copy.deepcopy(payload)
                bad["variables"]["dev_gpu_enabled"]["value"] = value
                plan_guard.validate_first_deploy(bad)

    def test_regular_plan_keeps_automatic_mode_contract_without_special_first_deploy_check(
        self,
    ):
        with patch.object(plan_guard.subprocess, "run") as run:
            plan_guard.seal(self.infra, self.plan)
            plan_guard.check(self.infra, self.plan)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
