"""Offline Template plan/apply contract and secret-safe diagnostics."""

import copy
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import serving_templates as module

IMAGE = (
    "ghcr.io/sknetworks-family-aicamp/skn30-final-3team/f2-serving@sha256:" + "a" * 64
)
PREVIOUS_IMAGE = IMAGE[:-64] + "b" * 64


class Aws:
    def __init__(self):
        self.settings = module.control.Settings(account_id="123456789012")
        self.record = {
            "schema_version": 2,
            "status": "ready",
            "image": PREVIOUS_IMAGE,
            "template_id": "existing-template",
            "registry_auth_id": "existing-registry",
        }
        self.endpoint_value = {"status": "offline"}
        self.writes = []
        self.version = "secret-version-1"

    def verify_identity(self):
        return "123456789012"

    def control(self):
        return copy.deepcopy(self.record)

    def endpoint(self):
        return copy.deepcopy(self.endpoint_value)

    def secret_value(self, name):
        value = "operator-private"
        if name == self.settings.secrets["ai"]:
            value = json.dumps(
                {
                    "AI_VLLM_SLLM_API_KEY": "s" * 43,
                    "AI_VLLM_STT_API_KEY": "t" * 43,
                    "AI_GENERAL_API_KEY": "g" * 43,
                }
            )
        return value, self.version

    def put_control(self, value):
        self.writes.append(value)
        self.record = copy.deepcopy(value)


class Api:
    def __init__(self):
        path = module.INFRA / "runpod/template.json"
        self.value = {
            **module.control.template_payload(
                path, PREVIOUS_IMAGE, "existing-registry", "skn30-f2-serving-v2"
            ),
            "id": "existing-template",
        }
        self.pod_values = []
        self.patches = []
        self.ignore_patch = False

    def template(self, identifier):
        return copy.deepcopy(self.value)

    def registry(self, identifier):
        return {"id": "existing-registry", "password": "registry-private"}

    def pods(self):
        return copy.deepcopy(self.pod_values)

    def request(self, method, path, payload):
        assert method == "PATCH" and path == "/templates/existing-template"
        self.patches.append(copy.deepcopy(payload))
        if not self.ignore_patch:
            self.value.update(payload)


class TemplateTests(unittest.TestCase):
    def setUp(self):
        self.aws, self.api = Aws(), Api()
        self.spec = {"cloud": "runpod", "image": IMAGE}
        serving = SimpleNamespace(
            session=object(),
            settings=self.aws.settings,
            runpod=lambda: self.api,
        )
        self.reconciler = module.TemplateReconciler(serving)
        self.addCleanup(patch.stopall)
        patch.object(module.control, "AwsStore", return_value=self.aws).start()
        patch.object(module.control, "RunpodClient", return_value=self.api).start()

    def test_review_is_read_only_redacted_and_apply_updates_only_existing_template(
        self,
    ):
        self.api.value["env"]["UNEXPECTED_TOKEN"] = "secret-that-must-not-be-printed"
        self.api.value["dockerStartCmd"] = ["python", "https://private/?token=hidden"]
        plan = self.reconciler.plan("f2", self.spec)
        serialized = json.dumps(plan)
        for secret in (
            "registry-private",
            "operator-private",
            "secret-that-must-not-be-printed",
            "https://private",
            "hidden",
        ):
            self.assertNotIn(secret, serialized)
        self.assertEqual(self.api.patches, [])
        self.assertEqual(self.aws.writes, [])
        self.assertEqual(
            {change["field"] for change in plan["changes"]},
            {"imageName", "dockerStartCmd", "env"},
        )
        with redirect_stdout(io.StringIO()):
            result = self.reconciler.apply(plan, self.spec)
        self.assertEqual(result["image"], IMAGE)
        self.assertEqual(
            set(self.api.patches[0]), {"imageName", "dockerStartCmd", "env"}
        )
        self.assertEqual(len(self.aws.writes), 1)
        unchanged = self.reconciler.plan("f2", self.spec)
        self.assertEqual(unchanged["changes"], [])
        self.assertFalse(unchanged["registration_changed"])
        with redirect_stdout(io.StringIO()):
            self.reconciler.apply(unchanged, self.spec)
        self.assertEqual(len(self.api.patches), 1)
        self.assertEqual(len(self.aws.writes), 1)

    def test_stale_template_registration_or_secret_blocks_before_patch(self):
        for target in ("template", "registration", "secret"):
            with self.subTest(target=target):
                plan = self.reconciler.plan("f2", self.spec)
                if target == "template":
                    self.api.value["containerDiskInGb"] += 1
                elif target == "registration":
                    self.aws.record["updated_at"] = "changed"
                else:
                    self.aws.version = "secret-version-2"
                with self.assertRaisesRegex(module.control.ToolError, "stale"):
                    self.reconciler.apply(plan, self.spec)
        self.assertEqual(self.api.patches, [])
        self.assertEqual(self.aws.writes, [])

    def test_unrelated_named_pod_using_template_blocks(self):
        self.api.pod_values = [
            {"name": "another-team-test", "templateId": "existing-template"}
        ]
        with self.assertRaisesRegex(module.control.ToolError, "referenced"):
            self.reconciler.plan("f2", self.spec)

    def test_endpoint_reactivation_blocks_apply(self):
        plan = self.reconciler.plan("f2", self.spec)
        self.aws.endpoint_value["status"] = "active"
        with self.assertRaisesRegex(module.control.ToolError, "offline"):
            self.reconciler.apply(plan, self.spec)
        self.assertEqual(self.api.patches, [])

    def prepared_pod(self):
        self.api.value["imageName"] = IMAGE
        self.aws.record["image"] = IMAGE
        self.aws.endpoint_value = {
            "status": "active",
            "pod_id": "prepared-pod",
            "sllm_release_id": "consultation-v3",
        }
        self.api.pod_values = [
            {
                "id": "prepared-pod",
                "name": "skn30-f2-serving-dev",
                "templateId": "existing-template",
                "imageName": IMAGE,
                "desiredStatus": "RUNNING",
            }
        ]
        self.spec["release_id"] = "consultation-v3"

    def test_prepared_matching_pod_resumes_without_patch_or_registration(self):
        self.prepared_pod()
        plan = self.reconciler.plan("f2", self.spec)
        self.assertTrue(plan["read_only_resume"])
        with patch.object(module.control, "Registrar") as registrar:
            result = self.reconciler.apply(plan, self.spec)
        registrar.assert_not_called()
        self.assertEqual(result["image"], IMAGE)
        self.assertEqual(self.api.patches, [])
        self.assertEqual(self.aws.writes, [])

    def test_active_resume_refuses_template_drift_or_wrong_pod(self):
        self.prepared_pod()
        self.api.value["dockerStartCmd"] = [
            "python3",
            "/opt/f2-runtime/scripts/supervisor.py",
        ]
        with self.assertRaisesRegex(module.control.ToolError, "offline"):
            self.reconciler.plan("f2", self.spec)
        self.api.value["dockerStartCmd"] = [
            "python",
            "/opt/f2-runtime/scripts/supervisor.py",
        ]
        self.api.pod_values[0]["imageName"] = PREVIOUS_IMAGE
        with self.assertRaisesRegex(module.control.ToolError, "offline"):
            self.reconciler.plan("f2", self.spec)

    def test_prepared_pod_snapshot_change_invalidates_resume(self):
        self.prepared_pod()
        plan = self.reconciler.plan("f2", self.spec)
        self.api.pod_values[0]["env"] = {"NEW_CONFIG": "hidden-value"}
        with self.assertRaisesRegex(module.control.ToolError, "stale"):
            self.reconciler.apply(plan, self.spec)
        self.assertEqual(self.api.patches, [])

    def test_failed_patch_verification_preserves_registration(self):
        plan = self.reconciler.plan("f2", self.spec)
        self.api.ignore_patch = True
        with self.assertRaisesRegex(module.control.ToolError, "differs"):
            self.reconciler.apply(plan, self.spec)
        self.assertEqual(self.aws.writes, [])

    def test_registration_changed_during_patch_is_not_overwritten(self):
        plan = self.reconciler.plan("f2", self.spec)
        original = self.api.request

        def concurrent_change(*args):
            original(*args)
            self.aws.record["updated_at"] = "concurrent-registration"

        with (
            patch.object(self.api, "request", side_effect=concurrent_change),
            self.assertRaisesRegex(
                module.control.ToolError, "SSM registration changed"
            ),
        ):
            self.reconciler.apply(plan, self.spec)
        self.assertEqual(self.aws.writes, [])

    def test_general_uses_its_own_template_and_registration(self):
        self.aws.settings = module.control.Settings(
            account_id="123456789012", workload="general"
        )
        image = IMAGE.replace("/f2-serving@", "/general-serving@")
        self.api.value = {
            **module.control.template_payload(
                module.INFRA / "serving/general-template.json",
                image,
                "existing-registry",
                "skn30-general-serving-v1",
            ),
            "id": "existing-template",
        }
        self.api.value["dockerStartCmd"][0] = "python"
        spec = {"cloud": "runpod", "image": image}
        plan = self.reconciler.plan("general", spec)
        with redirect_stdout(io.StringIO()):
            result = self.reconciler.apply(plan, spec)
        self.assertEqual(result["image"], image)
        self.assertEqual(
            self.api.patches,
            [{"dockerStartCmd": ["python3", "/opt/general/general_runtime.py"]}],
        )

    def test_plan_cannot_substitute_workload_image_or_resource_ids(self):
        for image in (
            "ghcr.io/other/image@sha256:" + "a" * 64,
            "https://private/?secret=token",
        ):
            with self.subTest(image=image), self.assertRaises(module.control.ToolError):
                self.reconciler.plan("f2", {**self.spec, "image": image})
        self.aws.record["template_id"] = None
        with self.assertRaisesRegex(module.control.ToolError, "register existing"):
            self.reconciler.plan("f2", self.spec)


if __name__ == "__main__":
    unittest.main()
