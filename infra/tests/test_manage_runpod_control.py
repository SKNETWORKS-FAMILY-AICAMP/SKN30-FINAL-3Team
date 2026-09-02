import importlib.util
import io
import json
import sys
import unittest
import urllib.error
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "infra/scripts/manage_runpod_control.py"
SPEC = importlib.util.spec_from_file_location("manage_runpod_control", PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

IMAGE = (
    "ghcr.io/sknetworks-family-aicamp/skn30-final-3team/f2-serving@sha256:"
    + "a" * 64
)


class FakeAws:
    def __init__(self, *, missing=()):
        self.settings = MODULE.Settings()
        self.missing = set(missing)
        self.control_value = {
            "schema_version": 1,
            "status": "uninitialized",
            "generation": 0,
            "registry_auth_id": None,
            "template_id": None,
            "image": None,
            "ai_provider_secret_version_id": None,
        }
        self.controls = []
        self.puts = []
        self.endpoint_value = {"status": "offline"}
        self.ai = {
            "AI_OPENAI_API_KEY": "openai-private",
            "AI_VLLM_SLLM_API_KEY": "s" * 43,
            "AI_VLLM_STT_API_KEY": "t" * 43,
        }

    def verify_identity(self):
        return "123456789012"

    def has_current(self, name):
        purpose = next(key for key, value in self.settings.secrets.items() if value == name)
        return purpose not in self.missing

    def control(self):
        return dict(self.control_value)

    def put_control(self, value):
        self.control_value = dict(value)
        self.controls.append(dict(value))

    def secret_value(self, name):
        purpose = next(key for key, value in self.settings.secrets.items() if value == name)
        values = {
            "ai": json.dumps(self.ai),
            "operator": "operator-private",
            "monitor": "monitor-private",
            "ghcr": json.dumps({"username": "octocat", "password": "pat-private"}),
            "delivery_discord": "https://discord.com/api/webhooks/1/private",
            "alarm_discord": "https://discord.com/api/webhooks/2/private",
        }
        return values[purpose], f"version-{purpose}"

    def put_secret(self, name, value):
        self.puts.append((name, value))
        return "version-new"

    def endpoint(self):
        return dict(self.endpoint_value)


class FakeRunpod:
    def __init__(self):
        self.pod_values = []
        self.secret_values = set()
        self.registry_values = []
        self.template_values = []
        self.registry_creates = 0
        self.template_creates = 0
        self.fail_template_once = False

    def pods(self):
        return list(self.pod_values)

    def secret_names(self):
        return set(self.secret_values)

    def create_secret(self, name, _value):
        self.secret_values.add(name)

    def delete_secret(self, name):
        self.secret_values.remove(name)

    def registries(self):
        return list(self.registry_values)

    def create_registry(self, name, _username, _password):
        self.registry_creates += 1
        value = {"id": "registry-1", "name": name}
        self.registry_values.append(value)
        return value

    def templates(self):
        return list(self.template_values)

    def create_template(self, payload):
        if self.fail_template_once:
            self.fail_template_once = False
            raise MODULE.ToolError("template fixture failure")
        self.template_creates += 1
        value = {**payload, "id": "template-1"}
        self.template_values.append(value)
        return value


class BootstrapTests(unittest.TestCase):
    def test_plan_is_read_only(self):
        aws = FakeAws()
        runpod = FakeRunpod()
        output = io.StringIO()
        with patch.object(
            MODULE, "RunpodClient", return_value=runpod
        ), redirect_stdout(output):
            result = MODULE.Bootstrapper(aws).plan(IMAGE)
        self.assertFalse(result["mutates"])
        self.assertEqual(aws.controls, [])
        self.assertEqual(aws.puts, [])
        self.assertNotIn("private", output.getvalue())

    def test_plan_rejects_digest_from_another_repository(self):
        with self.assertRaises(MODULE.ToolError):
            MODULE.Bootstrapper(FakeAws()).plan(
                "ghcr.io/example/f2-serving@sha256:" + "a" * 64
            )

    def test_apply_is_idempotent(self):
        aws = FakeAws()
        runpod = FakeRunpod()
        with patch.object(
            MODULE, "RunpodClient", return_value=runpod
        ), redirect_stdout(io.StringIO()):
            first = MODULE.Bootstrapper(aws).apply(IMAGE)
            second = MODULE.Bootstrapper(aws).apply(IMAGE)
        self.assertEqual(first, second)
        self.assertEqual(runpod.registry_creates, 1)
        self.assertEqual(runpod.template_creates, 1)
        self.assertEqual(runpod.secret_values, set(MODULE.F2_SECRET_NAMES))
        self.assertEqual(aws.control_value["status"], "ready")

    def test_apply_never_prints_secret_values(self):
        aws = FakeAws()
        runpod = FakeRunpod()
        output = io.StringIO()
        with patch.object(
            MODULE, "RunpodClient", return_value=runpod
        ), redirect_stdout(output):
            MODULE.Bootstrapper(aws).apply(IMAGE)
        for secret in (
            "operator-private",
            "monitor-private",
            "pat-private",
            "openai-private",
            "s" * 43,
            "t" * 43,
        ):
            self.assertNotIn(secret, output.getvalue())
        self.assertNotIn("subprocess", PATH.read_text(encoding="utf-8"))

    def test_partial_failure_resumes_from_control_document(self):
        aws = FakeAws()
        runpod = FakeRunpod()
        runpod.fail_template_once = True
        with patch.object(
            MODULE, "RunpodClient", return_value=runpod
        ), self.assertRaises(MODULE.ToolError):
            MODULE.Bootstrapper(aws).apply(IMAGE)
        self.assertEqual(aws.control_value["status"], "provisioning")
        with patch.object(
            MODULE, "RunpodClient", return_value=runpod
        ), redirect_stdout(io.StringIO()):
            MODULE.Bootstrapper(aws).apply(IMAGE)
        self.assertEqual(runpod.registry_creates, 1)
        self.assertEqual(runpod.template_creates, 1)
        self.assertEqual(aws.control_value["status"], "ready")

    def test_duplicate_registry_name_is_rejected(self):
        aws = FakeAws()
        runpod = FakeRunpod()
        runpod.registry_values = [
            {"id": "one", "name": "skn30-final-3team-dev-ghcr-g1"},
            {"id": "two", "name": "skn30-final-3team-dev-ghcr-g1"},
        ]
        with patch.object(
            MODULE, "RunpodClient", return_value=runpod
        ), self.assertRaises(MODULE.ToolError):
            MODULE.Bootstrapper(aws).apply(IMAGE)

    def test_http_failure_does_not_expose_key_or_response_body(self):
        secret = "runpod-private-key"

        def failure(_request, _timeout):
            raise urllib.error.HTTPError(
                MODULE.RUNPOD_REST_URL + "/pods",
                401,
                "response contains runpod-private-key",
                {},
                None,
            )

        client = MODULE.RunpodClient(secret, requester=failure)
        with self.assertRaises(MODULE.ToolError) as raised:
            client.pods()
        self.assertNotIn(secret, str(raised.exception))

    def test_f2_and_ghcr_rotation_reject_active_endpoint_before_secret_write(self):
        for target in ("f2", "ghcr"):
            with self.subTest(target=target):
                aws = FakeAws()
                aws.endpoint_value = {"status": "active", "pod_id": "pod-1"}
                with patch.object(
                    MODULE, "RunpodClient", return_value=FakeRunpod()
                ), self.assertRaises(MODULE.ToolError):
                    MODULE.rotate_secret(aws, target, MODULE.DEFAULT_TEMPLATE)
                self.assertEqual(aws.puts, [])


if __name__ == "__main__":
    unittest.main()
