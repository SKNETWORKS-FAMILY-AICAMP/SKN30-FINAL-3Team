"""Only a smoke-attested, immutable app revision may be restored automatically."""

import copy
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

INFRA = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(INFRA / part) for part in ("scripts", "serving", "deploy/scripts")]
import serving_app_revision as module


class RevisionTests(unittest.TestCase):
    def setUp(self):
        self.serving = Mock()
        self.serving.settings = SimpleNamespace(
            name_prefix="project-dev",
            project="project",
            environment="dev",
            account_id="123456789012",
            region="ap-northeast-2",
            timeout_seconds=60,
        )
        self.serving.app_id.return_value = "i-testedhost"
        self.client = Mock()
        sts = Mock()
        sts.get_caller_identity.return_value = {"Account": "123456789012"}
        self.serving.session.client.side_effect = lambda name: (
            sts if name == "sts" else self.client
        )
        self.revision = {
            "revisionType": "S3",
            "s3Location": {
                "bucket": "private-artifacts",
                "key": "revision.zip",
                "version": "immutable-version",
                "bundleType": "zip",
            },
        }
        self.info = {
            "status": "Succeeded",
            "applicationName": "project-dev-backend",
            "deploymentGroupName": "project-dev-backend",
            "revision": self.revision,
        }
        self.client.get_deployment.side_effect = lambda **kwargs: {
            "deploymentInfo": copy.deepcopy(self.info)
        }
        self.group = {
            "lastSuccessfulDeployment": {"deploymentId": "d-ATTESTED1"},
            "autoScalingGroups": [],
            "ec2TagSet": {
                "ec2TagSetList": [
                    [{"Key": key, "Value": value, "Type": "KEY_AND_VALUE"}]
                    for key, value in (
                        ("Project", "project"),
                        ("Environment", "dev"),
                        ("Name", "project-dev-app-asg"),
                    )
                ]
            },
        }
        self.client.get_deployment_group.return_value = {
            "deploymentGroupInfo": self.group
        }
        self.client.get_deployment_instance.return_value = {
            "instanceSummary": {"status": "Succeeded"}
        }
        self.client.create_deployment.return_value = {"deploymentId": "d-RESTORED1"}
        self.attestation = module.capture(self.serving)

    def test_exact_attested_revision_restores_with_maintenance_marker_before_create(
        self,
    ):
        events = []
        self.serving.command.side_effect = lambda *args, **kwargs: events.append(
            "marker"
        )
        self.client.create_deployment.side_effect = lambda **kwargs: (
            events.append("create") or {"deploymentId": "d-RESTORED1"}
        )
        with redirect_stdout(io.StringIO()):
            self.assertTrue(module.restore(self.serving, self.attestation))
        self.assertEqual(events, ["marker", "create"])
        self.assertEqual(
            self.client.create_deployment.call_args.kwargs["revision"], self.revision
        )
        self.assertEqual(
            self.client.create_deployment.call_args.kwargs["autoRollbackConfiguration"],
            {"enabled": False},
        )
        self.assertIn(
            "cloud-init status --wait", self.serving.command.call_args.args[1]
        )
        self.assertIn(
            "test -f /opt/brokerage/serving-maintenance",
            self.serving.command.call_args.args[1],
        )
        self.assertEqual(set(self.attestation), {"deployment_id", "revision_sha256"})
        self.assertNotIn("private-artifacts", str(self.attestation))

    def test_missing_attestation_never_chooses_latest_deployment(self):
        self.client.reset_mock()
        self.assertFalse(module.restore(self.serving, None))
        self.client.get_deployment.assert_not_called()
        self.client.get_deployment_group.assert_not_called()
        self.client.create_deployment.assert_not_called()

    def test_new_latest_deployment_does_not_replace_attested_source(self):
        self.group["lastSuccessfulDeployment"] = {"deploymentId": "d-UNTESTED1"}
        with redirect_stdout(io.StringIO()):
            module.restore(self.serving, self.attestation)
        self.assertEqual(
            self.client.get_deployment.call_args_list[-2].kwargs["deploymentId"],
            "d-ATTESTED1",
        )
        self.assertEqual(
            self.client.create_deployment.call_args.kwargs["revision"], self.revision
        )

    def test_changed_revision_is_refused_before_any_deployment(self):
        self.info["revision"] = {
            **self.revision,
            "s3Location": {**self.revision["s3Location"], "version": "other"},
        }
        with self.assertRaisesRegex(module.ToolError, "revision changed"):
            module.restore(self.serving, self.attestation)
        self.client.create_deployment.assert_not_called()

    def test_failed_or_other_application_attestation_is_refused(self):
        for field, value in (
            ("status", "Failed"),
            ("applicationName", "other-app"),
            ("deploymentGroupName", "other-group"),
        ):
            with self.subTest(field=field):
                previous = self.info[field]
                self.info[field] = value
                with self.assertRaisesRegex(module.ToolError, "successful"):
                    module.restore(self.serving, self.attestation)
                self.info[field] = previous
        self.client.create_deployment.assert_not_called()

    def test_missing_maintenance_marker_or_attached_asg_refuses_create(self):
        self.serving.command.side_effect = module.ToolError("marker absent")
        with self.assertRaisesRegex(module.ToolError, "marker"):
            module.restore(self.serving, self.attestation)
        self.serving.command.side_effect = None
        self.group["autoScalingGroups"] = [{"name": "project-dev-app"}]
        with self.assertRaisesRegex(module.ToolError, "automatic ASG"):
            module.restore(self.serving, self.attestation)
        self.client.create_deployment.assert_not_called()

    def test_capture_requires_deployment_installed_on_tested_host(self):
        self.client.get_deployment_instance.return_value = {
            "instanceSummary": {"status": "Pending"}
        }
        with self.assertRaisesRegex(module.ToolError, "tested app host"):
            module.capture(self.serving)

    def test_unversioned_unhashed_artifact_cannot_be_attested(self):
        self.revision["s3Location"].pop("version")
        with self.assertRaisesRegex(module.ToolError, "version or eTag"):
            module.capture(self.serving)
        self.revision["s3Location"]["eTag"] = "fixture-object-checksum"
        self.assertIn("revision_sha256", module.capture(self.serving))

    def test_timeout_stops_only_restore_deployment_without_rollback(self):
        def deployment(**kwargs):
            return {
                "deploymentInfo": self.info
                if kwargs["deploymentId"] == "d-ATTESTED1"
                else {"status": "InProgress"}
            }

        self.client.get_deployment.side_effect = deployment
        with (
            patch.object(module.time, "monotonic", side_effect=[0, 61]),
            redirect_stdout(io.StringIO()),
            self.assertRaisesRegex(module.ToolError, "timed out"),
        ):
            module.restore(self.serving, self.attestation)
        self.client.stop_deployment.assert_called_once_with(
            deploymentId="d-RESTORED1", autoRollbackEnabled=False
        )


if __name__ == "__main__":
    unittest.main()
