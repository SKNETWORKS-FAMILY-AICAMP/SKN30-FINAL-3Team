"""Offline orchestration regressions; no cloud resources or inference are started."""

import copy
import io
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

INFRA = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(INFRA / part) for part in ("scripts", "serving", "deploy/scripts")]
import plan_guard
import serving_lifecycle as lifecycle
import serving_plan
from serving_selection import fingerprint


class StartGuardTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.infra = Path(self.directory.name)
        self.root = self.infra / "environments/dev"
        self.root.mkdir(parents=True)
        self.source = self.root / "nested/policy.json"
        self.source.parent.mkdir()
        self.source.write_text('{"reviewed": true}')
        self.saved = self.root / "dev-serving.tfplan"
        self.saved.write_bytes(b"opaque saved plan")
        plan_guard.seal(self.infra, self.saved)
        self.selection = {
            "selection_id": "chosen",
            "f2": {"cloud": "runpod"},
            "general": {"cloud": "aws"},
        }
        self.plan = serving_plan.StartPlan.__new__(serving_plan.StartPlan)
        self.plan.infra, self.plan.path = self.infra, self.saved
        self.plan.serving = Mock()
        self.plan.serving.selection_document.return_value = self.selection
        self.plan.templates = Mock()
        self.template = {"workload": "f2", "snapshot_hash": "original"}
        self.plan.templates.plan.return_value = self.template
        self.data = {
            "created_at": time.time(),
            "selection": copy.deepcopy(self.selection),
            "selection_hash": fingerprint(self.selection),
            "templates": [self.template],
        }

    def test_unchanged_plan_passes_but_recursive_input_change_is_rejected(self):
        self.plan.check(self.data)
        self.source.write_text('{"reviewed": false}')
        with self.assertRaises(ValueError):
            self.plan.check(self.data)

    def test_saved_plan_byte_change_is_rejected(self):
        self.saved.write_bytes(b"different saved plan")
        with self.assertRaises(ValueError):
            self.plan.check(self.data)

    def test_shared_selection_change_is_rejected(self):
        self.plan.serving.selection_document.return_value = {
            **self.selection,
            "selection_id": "another-operator",
        }
        with self.assertRaisesRegex(lifecycle.ToolError, "selection changed"):
            self.plan.check(self.data)

    def test_template_snapshot_change_is_rejected(self):
        self.plan.templates.plan.return_value = {
            **self.template,
            "snapshot_hash": "changed",
        }
        with self.assertRaisesRegex(lifecycle.ToolError, "template changed"):
            self.plan.check(self.data)

    def test_expired_review_is_rejected(self):
        self.data["created_at"] = time.time() - plan_guard.MAX_AGE - 1
        with self.assertRaisesRegex(lifecycle.ToolError, "expired"):
            self.plan.check(self.data)


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        self.output = io.StringIO()
        # Keep structured fake events out of the test-runner output.
        self.redirect = redirect_stdout(self.output)
        self.redirect.__enter__()
        self.addCleanup(self.redirect.__exit__, None, None, None)
        self.selection = {
            "selection_id": "selection-1",
            "f2": {"cloud": "runpod"},
            "general": {"cloud": "aws"},
        }
        self.serving = Mock()
        self.serving.settings = SimpleNamespace(region="ap-northeast-2")
        self.serving.prefix = "project-dev"
        self.serving.selection_document.return_value = self.selection
        self.serving.instances.side_effect = lambda workload: (
            [{"InstanceId": "existing-general", "State": {"Name": "stopped"}}]
            if workload == "general"
            else []
        )
        self.serving.app_id.return_value = "maintenance-host"
        self.serving.read.return_value = {}
        self.serving.managed_pods.return_value = []
        self.captured_revision = {
            "deployment_id": "d-CAPTURED1",
            "revision_sha256": "a" * 64,
        }
        self.capture = patch(
            "serving_app_revision.capture", return_value=self.captured_revision
        ).start()
        self.restore = patch("serving_app_revision.restore", return_value=True).start()
        self.data = {
            "selection": self.selection,
            "selection_hash": fingerprint(self.selection),
            "inventory": {
                "f2": [],
                "general": [{"id": "existing-general", "state": "stopped"}],
            },
        }
        self.plan = Mock()
        self.plan.approved = False
        self.plan.build.return_value = self.data
        self.plan.apply.side_effect = lambda _data: setattr(self.plan, "approved", True)
        patch.object(lifecycle, "StartPlan", return_value=self.plan).start()
        patch.object(lifecycle, "require_maintenance_deployment").start()
        patch.object(lifecycle, "require_general_selection").start()
        self.targets = Mock()
        self.targets.preview.return_value = {"snapshot": "db-before"}
        self.targets.choose.return_value = [
            {"brokerage_id": 7, "capability": "CHATBOT"}
        ]
        patch.object(lifecycle, "ModelTargets", return_value=self.targets).start()
        self.existing = set()
        self.prepare_failure = None

        def prepare(workload, spec):
            if workload == self.prepare_failure:
                raise lifecycle.ToolError("GPU capacity unavailable")
            resource_id = "new-f2-pod" if workload == "f2" else "existing-general"
            deployment = {"cloud": spec["cloud"], "resource_id": resource_id}
            self.serving.started_candidate = (
                None if workload in self.existing else deployment
            )
            self.existing.add(workload)
            return deployment

        self.serving.prepare.side_effect = prepare

    def test_second_gpu_failure_cleans_first_attempt_resource_only(self):
        self.prepare_failure = "general"
        operation = lifecycle.Lifecycle(self.serving)
        with self.assertRaisesRegex(lifecycle.ToolError, "capacity"):
            operation.run(apply=True)
        self.serving.runpod.return_value.delete.assert_called_once_with("new-f2-pod")
        self.serving.ec2.stop_instances.assert_not_called()
        self.targets.apply.assert_not_called()
        self.assertEqual(self.serving.write.call_args.args[1]["status"], "failed")
        self.assertEqual(self.serving.app.call_args.args, ("stop",))

    def test_app_smoke_failure_stops_aws_started_this_attempt_and_new_runpod(self):
        self.serving.application_smoke.side_effect = lifecycle.ToolError(
            "invalid inference"
        )
        with self.assertRaisesRegex(lifecycle.ToolError, "inference"):
            lifecycle.Lifecycle(self.serving).run(apply=True)
        self.serving.runpod.return_value.delete.assert_called_once_with("new-f2-pod")
        self.serving.ec2.stop_instances.assert_called_once_with(
            InstanceIds=["existing-general"]
        )
        self.serving.ec2.get_waiter.return_value.wait.assert_called_once_with(
            InstanceIds=["existing-general"]
        )
        self.assertEqual(self.serving.app.call_args.args, ("stop",))
        self.assertEqual(self.serving.write.call_args.args[1]["status"], "failed")

    def test_app_failure_preserves_already_running_gpu(self):
        self.existing.add("general")
        self.data["inventory"]["general"][0]["state"] = "running"
        self.serving.application_smoke.side_effect = lifecycle.ToolError("bad output")
        with self.assertRaises(lifecycle.ToolError):
            lifecycle.Lifecycle(self.serving).run(apply=True)
        self.serving.ec2.stop_instances.assert_not_called()
        self.serving.runpod.return_value.delete.assert_called_once_with("new-f2-pod")

    def test_declined_plan_does_not_run_cleanup_or_record_a_failed_attempt(self):
        self.plan.apply.side_effect = lifecycle.ToolError("confirmation not supplied")
        with self.assertRaisesRegex(lifecycle.ToolError, "confirmation"):
            lifecycle.Lifecycle(self.serving).run(apply=True)
        self.serving.power.start.assert_not_called()
        self.serving.activate.assert_not_called()
        self.serving.app.assert_not_called()
        self.serving.write.assert_not_called()
        self.serving.runpod.assert_not_called()
        self.serving.ec2.stop_instances.assert_not_called()

    def test_plan_only_never_starts_resources(self):
        lifecycle.Lifecycle(self.serving).run(apply=False)
        self.plan.apply.assert_not_called()
        self.serving.prepare.assert_not_called()
        self.serving.power.start.assert_not_called()
        self.serving.write.assert_not_called()

    def test_partial_terraform_failure_stops_only_instances_added_by_attempt(self):
        def partial_apply(_data):
            self.plan.approved = True
            self.serving.instances.side_effect = lambda name: (
                [{"InstanceId": "created-by-terraform", "State": {"Name": "running"}}]
                if name == "f2"
                else [{"InstanceId": "existing-general", "State": {"Name": "stopped"}}]
            )
            raise lifecycle.ToolError("partial Terraform apply")

        self.plan.apply.side_effect = partial_apply
        with self.assertRaisesRegex(lifecycle.ToolError, "partial Terraform"):
            lifecycle.Lifecycle(self.serving).run(apply=True)
        self.serving.ec2.stop_instances.assert_called_once_with(
            InstanceIds=["created-by-terraform"]
        )
        self.serving.prepare.assert_not_called()
        self.serving.runpod.return_value.delete.assert_not_called()

    def test_cleanup_continues_aws_stop_when_runpod_delete_fails(self):
        self.serving.application_smoke.side_effect = lifecycle.ToolError("bad output")
        self.serving.runpod.return_value.delete.side_effect = lifecycle.ToolError(
            "delete unavailable"
        )
        with self.assertRaisesRegex(lifecycle.ToolError, "bad output"):
            lifecycle.Lifecycle(self.serving).run(apply=True)
        self.serving.ec2.stop_instances.assert_called_once_with(
            InstanceIds=["existing-general"]
        )
        self.assertIn("gpu-cleanup-incomplete", self.output.getvalue())

    def test_first_prepare_waits_for_app_deploy_then_resumes_without_new_gpus(self):
        self.targets.require_host.side_effect = lifecycle.AppDeploymentRequired(
            "new app required"
        )
        first = lifecycle.Lifecycle(self.serving)
        first.run(prepare_only=True, apply=True)
        self.assertEqual(first.stage, "awaiting-app-deploy")
        self.assertEqual(self.serving.write.call_args.args[1]["status"], "prepared")
        self.serving.application_smoke.assert_not_called()
        self.targets.apply.assert_not_called()
        self.serving.runpod.return_value.delete.assert_not_called()
        self.targets.require_host.side_effect = None
        resumed = lifecycle.Lifecycle(self.serving)
        resumed.run(apply=True)
        self.assertEqual(resumed.receipts, [])
        self.assertEqual(self.serving.write.call_args.args[1]["status"], "applied")
        self.assertEqual(self.serving.application_smoke.call_count, 2)
        self.targets.apply.assert_called_once_with(
            self.selection, self.targets.choose.return_value, "db-before"
        )

    def test_selection_change_during_db_preview_blocks_gpu_preparation(self):
        def change(_selected):
            self.serving.selection_document.return_value = {
                **self.selection,
                "selection_id": "new",
            }
            return {"snapshot": "db-before"}

        self.targets.preview.side_effect = change
        with self.assertRaisesRegex(lifecycle.ToolError, "selection changed"):
            lifecycle.Lifecycle(self.serving).run(apply=True)
        self.serving.prepare.assert_not_called()
        self.targets.apply.assert_not_called()

    def test_stopped_host_restores_prior_attestation_and_updates_after_smoke(self):
        previous = {"deployment_id": "d-PREVIOUS1", "revision_sha256": "b" * 64}
        self.serving.read.return_value = {"application_revision": previous}
        self.targets.require_host.side_effect = [
            lifecycle.AppDeploymentRequired("fresh host"),
            "maintenance-host",
        ]
        operation = lifecycle.Lifecycle(self.serving)
        operation.run(apply=True)
        self.restore.assert_called_once_with(self.serving, previous)
        applying = [
            call.args[1]
            for call in self.serving.write.call_args_list
            if call.args[1]["status"] == "applying"
        ]
        self.assertTrue(applying)
        self.assertTrue(
            all(record["application_revision"] == previous for record in applying)
        )
        self.assertEqual(
            self.serving.write.call_args.args[1]["application_revision"],
            self.captured_revision,
        )
        self.capture.assert_called_once_with(self.serving)

    def test_failed_restore_preserves_previous_attestation_for_retry(self):
        previous = {"deployment_id": "d-PREVIOUS1", "revision_sha256": "b" * 64}
        self.serving.read.return_value = {"application_revision": previous}
        self.targets.require_host.side_effect = lifecycle.AppDeploymentRequired(
            "fresh host"
        )
        self.restore.side_effect = lifecycle.ToolError("restore unavailable")
        with self.assertRaisesRegex(lifecycle.ToolError, "restore unavailable"):
            lifecycle.Lifecycle(self.serving).run(apply=True)
        self.capture.assert_not_called()
        self.assertEqual(
            self.serving.write.call_args.args[1]["application_revision"], previous
        )
        self.assertEqual(self.serving.write.call_args.args[1]["status"], "failed")

    def test_new_dev_without_attestation_requires_explicit_app_deploy(self):
        self.targets.require_host.side_effect = lifecycle.AppDeploymentRequired(
            "fresh host"
        )
        self.restore.return_value = False
        with self.assertRaisesRegex(
            lifecycle.AppDeploymentRequired, "first deployment"
        ):
            lifecycle.Lifecycle(self.serving).run(apply=True)
        self.restore.assert_called_once_with(self.serving, None)
        self.serving.prepare.assert_not_called()
        self.capture.assert_not_called()

    def test_lost_create_response_adopts_only_matching_attempt_token(self):
        operation = lifecycle.Lifecycle(self.serving)
        self.serving.managed_pods.return_value = [
            {"id": "created-but-response-lost"},
            {"id": "previous-attempt"},
        ]
        self.serving.runpod.return_value.pod.side_effect = lambda identifier: {
            "env": {
                "SERVING_ATTEMPT_ID": operation.attempt_id
                if identifier == "created-but-response-lost"
                else "another-attempt"
            }
        }
        self.serving.prepare.side_effect = lifecycle.ToolError("POST response lost")
        with self.assertRaisesRegex(lifecycle.ToolError, "response lost"):
            operation.run(apply=True)
        self.serving.runpod.return_value.delete.assert_called_once_with(
            "created-but-response-lost"
        )

    def test_keyboard_interrupt_after_create_preserves_receipt_for_cleanup(self):
        def interrupted(*args):
            self.serving.started_candidate = {
                "cloud": "runpod",
                "resource_id": "interrupted-pod",
            }
            raise KeyboardInterrupt

        self.serving.prepare.side_effect = interrupted
        with self.assertRaises(KeyboardInterrupt):
            lifecycle.Lifecycle(self.serving).run(apply=True)
        self.serving.runpod.return_value.delete.assert_called_once_with(
            "interrupted-pod"
        )


if __name__ == "__main__":
    unittest.main()
