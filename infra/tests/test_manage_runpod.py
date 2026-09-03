import importlib.util
import io
import json
import sys
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

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
                "pod-smoke-offline",
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

    def test_model_health_requires_expected_served_model_id(self) -> None:
        response = mock.MagicMock(status=200)
        response.read.return_value = json.dumps(
            {"data": [{"id": "unexpected-model"}]}
        ).encode()
        response.__enter__.return_value = response
        opener = mock.MagicMock()
        opener.open.return_value = response
        with mock.patch.object(
            MODULE.urllib.request, "build_opener", return_value=opener
        ):
            result = MODULE.request_models(
                "https://pod-8001.proxy.runpod.net/v1", SLLM_KEY, "sllm"
            )
        self.assertFalse(result["ok"])


class FakeRunpod:
    def __init__(self, *, present: bool = False, fail_delete: bool = False):
        self.present = present
        self.fail_delete = fail_delete
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
        if self.fail_delete:
            raise MODULE.ToolError("delete fixture failure")
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
        self.presigns = 0
        self.fail_smoke = False
        self.preflights = 0
        self.fail_refresh_calls: set[int] = set()
        self.release_stage = "verified"

    def release(self, release_id):
        return (
            {
                "release_id": release_id,
                "release_stage": self.release_stage,
                "base_model": {"id": "Qwen/Qwen3-4B", "revision": "a" * 40},
            },
            "b" * 64,
        )

    def presign(self, _release_id):
        self.presigns += 1
        return "https://private.s3.example/signed?X-Amz-Signature=secret"

    def preflight_backend(self):
        self.preflights += 1
        return "i-development"

    def current_endpoint(self):
        return dict(self.endpoint)

    def write_endpoint(self, value):
        self.endpoint = dict(value)
        self.writes.append(dict(value))

    def refresh(self):
        self.refreshes += 1
        if self.refreshes in self.fail_refresh_calls:
            raise MODULE.ToolError("refresh fixture failure")

    def smoke(self):
        self.smokes += 1
        if self.fail_smoke:
            raise MODULE.ToolError("smoke fixture failure")


def healthy(_url, _key, _expected_model):
    return {"ok": True, "status": 200, "latency_ms": 1}


def published_manifest(schema_version: int) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": schema_version,
        "release_id": "consultation-v1",
        "capability": MODULE.artifact.CAPABILITY,
        "served_model_name": MODULE.artifact.SERVED_MODEL_NAME,
        "created_at": "2026-09-01T00:00:00+00:00",
        "base_model": {"id": "Qwen/Qwen3-4B", "revision": "a" * 40},
        "adapter": {
            "format": "peft-lora",
            "path": "adapter",
            "sha256": "b" * 64,
            "size_bytes": 10,
            "file_count": 2,
        },
        "training": {
            "code_revision": "c" * 40,
            "dataset_release": "f2-v1",
            "train_sha256": "d" * 64,
            "validation_sha256": "e" * 64,
        },
        "evaluation": {
            "task": "full",
            "summary_path": "evaluation-summary.json",
            "summary_sha256": "f" * 64,
            "promotion_status": "approved",
            "selected_model": "candidate",
            "approval_path": "promotion-approval.json",
            "approval_sha256": "1" * 64,
        },
    }
    if schema_version == 2:
        value["release_mode"] = "lora"
        value["training"] = {
            "code_revision": "c" * 40,
            "train_sha256": "d" * 64,
            "validation_sha256": "e" * 64,
        }
        assert isinstance(value["evaluation"], dict)
        value["evaluation"].update(
            {
                "dataset_release": "f2-v2",
                "dataset_sha256": "2" * 64,
                "source_summary_sha256": "4" * 64,
            }
        )
    return value


class FakeArtifactClient:
    def __init__(self, manifest: dict[str, object], *, cross_hashes: bool):
        self.manifest_bytes = json.dumps(manifest).encode()
        manifest_sha = MODULE.hashlib.sha256(self.manifest_bytes).hexdigest()
        bundle_sha = "3" * 64
        self.heads = {
            "release.json": {
                "Metadata": {
                    "sha256": manifest_sha,
                    **({"bundle-sha256": bundle_sha} if cross_hashes else {}),
                }
            },
            "bundle.tar.gz": {
                "Metadata": {
                    "sha256": bundle_sha,
                    **(
                        {"release-manifest-sha256": manifest_sha}
                        if cross_hashes
                        else {}
                    ),
                }
            },
        }

    def run(self, *arguments):
        if arguments[:2] == ("s3api", "get-object"):
            Path(arguments[-1]).write_bytes(self.manifest_bytes)
            return ""
        raise AssertionError(arguments)

    def object_head(self, *, bucket, key):
        del bucket
        return self.heads[key.rsplit("/", 1)[-1]]


class PublishedReleaseTests(unittest.TestCase):
    def operations(self, client):
        return MODULE.AwsOperations(
            client,
            bucket="private",
            parameter_name="/endpoint",
            project="project",
        )

    def test_legacy_v1_checksum_metadata_remains_readable(self) -> None:
        manifest, bundle_sha = self.operations(
            FakeArtifactClient(published_manifest(1), cross_hashes=False)
        ).release("consultation-v1")
        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(bundle_sha, "3" * 64)

    def test_v2_requires_bidirectional_cross_hashes(self) -> None:
        with self.assertRaisesRegex(MODULE.ToolError, "cross-hashes"):
            self.operations(
                FakeArtifactClient(published_manifest(2), cross_hashes=False)
            ).release("consultation-v1")


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
        aws = FakeAws()
        output = io.StringIO()
        with redirect_stdout(output):
            self.controller(runpod, aws).create(
                release_id="consultation-v1",
                gpu_id="NVIDIA RTX 4090",
                terminate_after=None,
                apply=False,
                keys=(SLLM_KEY, STT_KEY),
            )
        self.assertFalse(runpod.created)
        self.assertEqual(aws.presigns, 0)
        self.assertEqual(aws.preflights, 1)
        self.assertNotIn("Signature=secret", output.getvalue())

    def test_standard_create_rejects_dev_release_before_cost(self) -> None:
        runpod = FakeRunpod()
        aws = FakeAws()
        aws.release_stage = "dev"
        with self.assertRaisesRegex(MODULE.ToolError, "runpod-create-dev"):
            self.controller(runpod, aws).create(
                release_id="dev-consultation-v1",
                gpu_id="NVIDIA RTX 4090",
                terminate_after=None,
                apply=False,
                keys=(SLLM_KEY, STT_KEY),
            )
        self.assertFalse(runpod.created)
        self.assertEqual(aws.preflights, 0)
        self.assertEqual(aws.presigns, 0)

    def test_dev_create_plan_accepts_only_dev_release(self) -> None:
        runpod = FakeRunpod()
        aws = FakeAws()
        aws.release_stage = "dev"
        output = io.StringIO()
        with redirect_stdout(output):
            self.controller(runpod, aws).create(
                release_id="dev-consultation-v1",
                gpu_id="NVIDIA RTX 4090",
                terminate_after=None,
                apply=False,
                keys=(SLLM_KEY, STT_KEY),
                allow_dev_release=True,
            )
        self.assertFalse(runpod.created)
        self.assertEqual(aws.preflights, 1)
        self.assertIn('"release_stage": "dev"', output.getvalue())
        self.assertIn('"evaluation_status": "not-evaluated"', output.getvalue())

    def test_dev_create_path_rejects_verified_release(self) -> None:
        runpod = FakeRunpod()
        aws = FakeAws()
        with self.assertRaisesRegex(MODULE.ToolError, "only accepts a dev release"):
            self.controller(runpod, aws).create(
                release_id="consultation-v1",
                gpu_id="NVIDIA RTX 4090",
                terminate_after=None,
                apply=False,
                keys=(SLLM_KEY, STT_KEY),
                allow_dev_release=True,
            )

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

    def test_create_smoke_failure_restores_endpoint_and_deletes_pod(self) -> None:
        runpod = FakeRunpod()
        aws = FakeAws()
        previous = dict(aws.endpoint)
        aws.fail_smoke = True
        with self.assertRaisesRegex(MODULE.ToolError, "smoke fixture failure"):
            self.controller(runpod, aws).create(
                release_id="consultation-v1",
                gpu_id="NVIDIA RTX 4090",
                terminate_after=None,
                apply=True,
                keys=(SLLM_KEY, STT_KEY),
            )
        self.assertEqual(aws.endpoint, previous)
        self.assertEqual(aws.refreshes, 2)
        self.assertEqual(runpod.deleted, [POD_ID])

    def test_create_health_failure_deletes_pod_before_endpoint_change(self) -> None:
        runpod = FakeRunpod()
        aws = FakeAws()
        controller = self.controller(runpod, aws)
        controller.timeout_seconds = 0
        with self.assertRaisesRegex(MODULE.ToolError, "did not become ready"):
            controller.create(
                release_id="consultation-v1",
                gpu_id="NVIDIA RTX 4090",
                terminate_after=None,
                apply=True,
                keys=(SLLM_KEY, STT_KEY),
            )
        self.assertEqual(aws.writes, [])
        self.assertEqual(runpod.deleted, [POD_ID])

    def test_failed_rollback_refresh_reports_reconcile_guidance(self) -> None:
        runpod = FakeRunpod()
        aws = FakeAws()
        aws.fail_smoke = True
        aws.fail_refresh_calls = {2}
        output = io.StringIO()
        with (
            redirect_stdout(output),
            self.assertRaisesRegex(MODULE.ToolError, "reconciliation is incomplete"),
        ):
            self.controller(runpod, aws).create(
                release_id="consultation-v1",
                gpu_id="NVIDIA RTX 4090",
                terminate_after=None,
                apply=True,
                keys=(SLLM_KEY, STT_KEY),
            )
        self.assertIn("runpod-reconcile-required", output.getvalue())
        self.assertNotIn("pod-create-complete", output.getvalue())
        self.assertEqual(runpod.deleted, [POD_ID])

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

    def test_delete_failure_restores_previous_endpoint(self) -> None:
        runpod = FakeRunpod(present=True, fail_delete=True)
        aws = FakeAws()
        aws.endpoint = MODULE.endpoint_value(
            previous=aws.endpoint,
            status="active",
            pod_id=POD_ID,
            release_id="consultation-v1",
        )
        previous = dict(aws.endpoint)
        with self.assertRaisesRegex(MODULE.ToolError, "delete fixture failure"):
            self.controller(runpod, aws).delete(
                pod_id=POD_ID, confirmed=True, apply=True
            )
        self.assertEqual(aws.endpoint, previous)
        self.assertEqual(aws.refreshes, 2)

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
