import importlib.util
import io
import json
import sys
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "infra/scripts"
sys.path.insert(0, str(SCRIPTS))
PATH = SCRIPTS / "manage_runpod.py"
SPEC = importlib.util.spec_from_file_location("manage_runpod", PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

TEMPLATE = ROOT / "infra/runpod/template.json"
IMAGE = "ghcr.io/example/f2-serving@sha256:" + "a" * 64
POD_ID = "abc123def4567"
SLLM_KEY = "l" * 43
STT_KEY = "s" * 43


def template_payload() -> dict:
    payload = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    payload["image"] = IMAGE
    return payload


def load_spec():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "template.json"
        path.write_text(json.dumps(template_payload()), encoding="utf-8")
        return MODULE.load_template_spec(path)


class FakeRequester:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request, _timeout):
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class TemplateTests(unittest.TestCase):
    def test_repository_template_is_ephemeral_and_task_named(self) -> None:
        spec = MODULE.load_template_spec(TEMPLATE, allow_placeholder=True)
        self.assertEqual(spec.name, "skn30-f2-serving-v2")
        self.assertEqual(set(spec.ports), {"8001/http", "8002/http"})
        self.assertNotIn("22/tcp", spec.ports)
        payload = json.loads(TEMPLATE.read_text(encoding="utf-8"))
        self.assertNotIn("volume_disk_gb", payload)
        self.assertNotIn("F2_SLLM_MODEL_ID", payload["env"])
        self.assertIn("AI_VLLM_SLLM_API_KEY", payload["env"])

    def test_template_rejects_volume_and_hardcoded_release(self) -> None:
        for key, value in (
            ("volume_disk_gb", 40),
            ("F2_SLLM_BUNDLE_URL", "https://signed.example"),
        ):
            payload = template_payload()
            if key.startswith("F2_"):
                payload["env"][key] = value
            else:
                payload[key] = value
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "template.json"
                path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(MODULE.ToolError):
                    MODULE.load_template_spec(path)

    def test_only_create_delete_lifecycle_is_exposed(self) -> None:
        option_strings = {
            option
            for action in MODULE.parser()._actions
            for option in action.option_strings
        }
        self.assertNotIn("--workspace-id", option_strings)
        self.assertNotIn("--template-id", option_strings)
        self.assertNotIn("--registry-auth-id", option_strings)
        subparsers = next(
            action
            for action in MODULE.parser()._actions
            if isinstance(action, MODULE.argparse._SubParsersAction)
        )
        self.assertEqual(
            set(subparsers.choices),
            {
                "doctor",
                "pod-create",
                "pod-status",
                "pod-smoke",
                "pod-delete",
                "pod-reconcile",
            },
        )

    def test_endpoint_values_are_atomic_active_or_offline(self) -> None:
        previous = {"revision": 2}
        active = MODULE.endpoint_value(
            previous=previous,
            status="active",
            pod_id=POD_ID,
            release_id="consultation-v1",
        )
        self.assertEqual(active["revision"], 3)
        self.assertEqual(active["sllm_release_id"], "consultation-v1")
        self.assertIn(POD_ID, active["sllm_base_url"])
        offline = MODULE.endpoint_value(previous=active, status="offline")
        self.assertEqual(offline["revision"], 4)
        self.assertIsNone(offline["pod_id"])
        self.assertIsNone(offline["sllm_base_url"])


class RunpodApiTests(unittest.TestCase):
    def test_create_is_secure_single_gpu_without_secret_argv_or_volume(self) -> None:
        requester = FakeRequester([json.dumps({"id": POD_ID}).encode()])
        client = MODULE.RunpodApi("runpod-private", requester=requester)
        result = client.create(
            template_id="template-1",
            gpu_id="NVIDIA RTX 4090",
            environment={"F2_SLLM_RELEASE_ID": "consultation-v1"},
            terminate_after=None,
        )
        request = requester.requests[0]
        payload = json.loads(request.data)
        self.assertEqual(result["id"], POD_ID)
        self.assertEqual(payload["cloudType"], "SECURE")
        self.assertEqual(payload["gpuCount"], 1)
        self.assertEqual(payload["gpuTypeIds"], ["NVIDIA RTX 4090"])
        self.assertEqual(payload["volumeInGb"], 0)
        self.assertNotIn("networkVolumeId", payload)
        self.assertNotIn("ssh", json.dumps(payload).lower())

    def test_delete_uses_exact_pod_id(self) -> None:
        requester = FakeRequester([b""])
        MODULE.RunpodApi("runpod-private", requester=requester).delete(POD_ID)
        self.assertEqual(requester.requests[0].method, "DELETE")
        self.assertTrue(requester.requests[0].full_url.endswith(f"/pods/{POD_ID}"))

    def test_failure_does_not_copy_response_or_api_key(self) -> None:
        failure = urllib.error.HTTPError(
            "https://rest.runpod.io/v1/pods",
            401,
            "X-Amz-Signature=private-signature runpod-private",
            {},
            None,
        )
        client = MODULE.RunpodApi("runpod-private", requester=FakeRequester([failure]))
        with self.assertRaises(MODULE.ToolError) as raised:
            client.pods()
        self.assertNotIn("private-signature", str(raised.exception))
        self.assertNotIn("runpod-private", str(raised.exception))


class FakeRunpod:
    def __init__(self, *, present: bool = False):
        self.present = present
        self.deleted: list[str] = []
        self.created = False

    def pods(self):
        if not self.present:
            return []
        return [{"id": POD_ID, "name": MODULE.SHARED_POD_NAME, "status": "RUNNING"}]

    def create(self, **_kwargs):
        self.present = True
        self.created = True
        return {"id": POD_ID}

    def pod(self, pod_id):
        assert pod_id == POD_ID
        return {"id": POD_ID, "status": "RUNNING"}

    def delete(self, pod_id):
        self.deleted.append(pod_id)
        self.present = False


class FakeAws:
    bucket = "private-models"

    def __init__(self):
        self.endpoint = {
            "revision": 0,
            "status": "offline",
            "pod_id": None,
            "sllm_release_id": None,
            "sllm_base_url": None,
            "stt_base_url": None,
            "updated_at": "1970-01-01T00:00:00Z",
        }
        self.writes: list[dict] = []
        self.refreshes = 0
        self.smokes = 0

    def release(self, release_id):
        return (
            {
                "release_id": release_id,
                "base_model": {"id": "Qwen/Qwen3-4B", "revision": "a" * 40},
            },
            "b" * 64,
            "https://private.s3.example/signed?X-Amz-Signature=secret",
        )

    def current_endpoint(self):
        return dict(self.endpoint)

    def write_endpoint(self, value):
        self.endpoint = dict(value)
        self.writes.append(dict(value))

    def refresh(self):
        self.refreshes += 1

    def smoke(self):
        self.smokes += 1


def healthy(_url, _key):
    return {"ok": True, "status": 200, "latency_ms": 1}


class ControllerTests(unittest.TestCase):
    def controller(self, runpod, aws):
        return MODULE.Controller(
            runpod=runpod,
            aws=aws,
            spec=load_spec(),
            template_id="template-1",
            requester=healthy,
            sleeper=lambda _seconds: None,
        )

    def test_create_dry_run_does_not_create_pod(self) -> None:
        runpod = FakeRunpod()
        output = io.StringIO()
        with redirect_stdout(output):
            self.controller(runpod, FakeAws()).create(
                release_id="consultation-v1",
                gpu_id="NVIDIA RTX 4090",
                terminate_after=None,
                apply=False,
                keys=(SLLM_KEY, STT_KEY),
            )
        self.assertFalse(runpod.created)
        self.assertNotIn("Signature=secret", output.getvalue())

    def test_create_activates_endpoint_after_health(self) -> None:
        runpod = FakeRunpod()
        aws = FakeAws()
        with redirect_stdout(io.StringIO()):
            self.controller(runpod, aws).create(
                release_id="consultation-v1",
                gpu_id="NVIDIA RTX 4090",
                terminate_after=None,
                apply=True,
                keys=(SLLM_KEY, STT_KEY),
            )
        self.assertTrue(runpod.created)
        self.assertEqual(aws.endpoint["status"], "active")
        self.assertEqual(aws.endpoint["pod_id"], POD_ID)
        self.assertEqual(aws.refreshes, 1)
        self.assertEqual(aws.smokes, 1)

    def test_delete_requires_exact_id_and_sets_offline_first(self) -> None:
        runpod = FakeRunpod(present=True)
        aws = FakeAws()
        aws.endpoint = MODULE.endpoint_value(
            previous=aws.endpoint,
            status="active",
            pod_id=POD_ID,
            release_id="consultation-v1",
        )
        controller = self.controller(runpod, aws)
        with self.assertRaises(MODULE.ToolError):
            controller.delete(pod_id="wrongpod", confirmed=True, apply=True)
        with redirect_stdout(io.StringIO()):
            controller.delete(pod_id=POD_ID, confirmed=True, apply=True)
        self.assertEqual(aws.endpoint["status"], "offline")
        self.assertEqual(runpod.deleted, [POD_ID])

    def test_reconcile_active_missing_pod_is_dry_run_by_default(self) -> None:
        runpod = FakeRunpod()
        aws = FakeAws()
        aws.endpoint = MODULE.endpoint_value(
            previous=aws.endpoint,
            status="active",
            pod_id=POD_ID,
            release_id="consultation-v1",
        )
        with redirect_stdout(io.StringIO()):
            self.controller(runpod, aws).reconcile(
                keys=(SLLM_KEY, STT_KEY),
                apply=False,
                endpoint_offline_confirmed=False,
            )
        self.assertEqual(aws.endpoint["status"], "active")
        self.assertEqual(aws.refreshes, 0)

    def test_reconcile_active_missing_pod_apply_requires_guard(self) -> None:
        runpod = FakeRunpod()
        aws = FakeAws()
        aws.endpoint = MODULE.endpoint_value(
            previous=aws.endpoint,
            status="active",
            pod_id=POD_ID,
            release_id="consultation-v1",
        )
        with self.assertRaises(MODULE.ToolError):
            self.controller(runpod, aws).reconcile(
                keys=(SLLM_KEY, STT_KEY),
                apply=True,
                endpoint_offline_confirmed=False,
            )
        with redirect_stdout(io.StringIO()):
            self.controller(runpod, aws).reconcile(
                keys=(SLLM_KEY, STT_KEY),
                apply=True,
                endpoint_offline_confirmed=True,
            )
        self.assertEqual(aws.endpoint["status"], "offline")
        self.assertEqual(aws.refreshes, 1)

    def test_reconcile_offline_orphan_only_prints_exact_delete_command(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            self.controller(FakeRunpod(present=True), FakeAws()).reconcile(
                keys=(SLLM_KEY, STT_KEY),
                apply=False,
                endpoint_offline_confirmed=False,
            )
        self.assertIn(f"runpod-delete {POD_ID}", output.getvalue())


if __name__ == "__main__":
    unittest.main()
