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
# Reuse the shared module: replacing it during discovery splits exception classes
# between the lifecycle helpers and their caller.
if SPEC.name in sys.modules:
    MODULE = sys.modules[SPEC.name]
else:
    MODULE = importlib.util.module_from_spec(SPEC)
    sys.modules[SPEC.name] = MODULE
    SPEC.loader.exec_module(MODULE)

IMAGE = (
    "ghcr.io/sknetworks-family-aicamp/skn30-final-3team/f2-serving@sha256:" + "a" * 64
)
NEW_IMAGE = IMAGE.rsplit(":", 1)[0] + ":" + "b" * 64


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
        purpose = next(
            key for key, value in self.settings.secrets.items() if value == name
        )
        return purpose not in self.missing

    def control(self):
        return dict(self.control_value)

    def put_control(self, value):
        self.control_value = dict(value)
        self.controls.append(dict(value))

    def secret_value(self, name):
        purpose = next(
            key for key, value in self.settings.secrets.items() if value == name
        )
        values = {
            "ai": json.dumps(self.ai),
            "operator": "operator-private",
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
    # Deliberately no create/update/delete methods: registration is read-only.
    def __init__(self):
        self.pod_values = []
        self.registry_value = {"id": "registry-1"}
        self.template_value = {
            **MODULE.template_payload(
                MODULE.DEFAULT_TEMPLATE, IMAGE, "registry-1", "skn30-f2-serving-v2"
            ),
            "id": "template-1",
        }

    def pods(self):
        return list(self.pod_values)

    def registry(self, _identifier):
        return dict(self.registry_value)

    def template(self, _identifier):
        return dict(self.template_value)


class RegistrationTests(unittest.TestCase):
    def test_rest_client_identifies_itself(self):
        def requester(request, _timeout):
            self.assertEqual(request.get_header("User-agent"), "skn30-infra/1.0")
            return b"[]"

        self.assertEqual(MODULE.RunpodClient("synthetic", requester=requester).pods(), [])

    def register(self, aws, runpod, *, apply=False, image=IMAGE):
        with (
            patch.object(MODULE, "RunpodClient", return_value=runpod),
            redirect_stdout(io.StringIO()),
        ):
            return MODULE.Registrar(aws).register(
                image, "template-1", "registry-1", apply=apply
            )

    def test_plan_never_writes_secrets_or_registration(self):
        aws = FakeAws()
        self.register(aws, FakeRunpod())
        self.assertEqual(aws.controls, [])
        self.assertEqual(aws.puts, [])

    def test_registration_is_one_complete_write_and_idempotent(self):
        aws = FakeAws()
        runpod = FakeRunpod()
        first = self.register(aws, runpod, apply=True)
        second = self.register(aws, runpod, apply=True)
        self.assertEqual(first, second)
        self.assertEqual(len(aws.controls), 1)
        self.assertEqual(aws.control_value["status"], "ready")
        self.assertEqual(aws.control_value["schema_version"], 2)
        self.assertNotIn("generation", aws.control_value)
        self.assertNotIn("ai_provider_secret_version_id", aws.control_value)
        self.assertEqual(aws.puts, [])

    def test_registration_rejects_active_endpoint_even_with_same_image(self):
        aws = FakeAws()
        aws.endpoint_value["status"] = "active"
        with self.assertRaisesRegex(MODULE.ToolError, "offline"):
            self.register(aws, FakeRunpod(), apply=True)
        self.assertEqual(aws.controls, [])

    def test_registration_rejects_existing_shared_pod(self):
        aws, runpod = FakeAws(), FakeRunpod()
        runpod.pod_values = [{"name": MODULE.SHARED_POD_NAME}]
        with self.assertRaisesRegex(MODULE.ToolError, "no shared RunPod Pod"):
            self.register(aws, runpod, apply=True)
        self.assertEqual(aws.controls, [])

    def test_invalid_console_template_leaves_previous_registration_intact(self):
        for field, value in (
            ("imageName", NEW_IMAGE),
            ("isPublic", True),
            ("volumeInGb", 10),
            ("ports", ["22/tcp"]),
            ("containerRegistryAuthId", "another-registry"),
        ):
            with self.subTest(field=field):
                aws, runpod = FakeAws(), FakeRunpod()
                previous = dict(aws.control_value)
                runpod.template_value[field] = value
                with self.assertRaises(MODULE.ToolError):
                    self.register(aws, runpod, apply=True)
                self.assertEqual(aws.control_value, previous)
                self.assertEqual(aws.controls, [])

    def test_unrelated_repository_rejected_before_aws_write(self):
        aws = FakeAws()
        with self.assertRaises(MODULE.ToolError):
            self.register(
                aws,
                FakeRunpod(),
                apply=True,
                image="ghcr.io/example/other@sha256:" + "a" * 64,
            )
        self.assertEqual(aws.controls, [])

    def test_registration_does_not_require_discord_secrets(self):
        aws = FakeAws(missing=("delivery_discord", "alarm_discord"))
        self.register(aws, FakeRunpod(), apply=True)
        self.assertEqual(aws.control_value["status"], "ready")

    def test_failure_can_be_retried_without_partial_control_state(self):
        aws, runpod = FakeAws(), FakeRunpod()
        with (
            patch.object(
                runpod, "template", side_effect=MODULE.ToolError("unavailable")
            ),
            self.assertRaises(MODULE.ToolError),
        ):
            self.register(aws, runpod, apply=True)
        self.assertEqual(aws.controls, [])
        self.register(aws, runpod, apply=True)
        self.assertEqual(len(aws.controls), 1)

    def test_registration_never_prints_secret_values(self):
        aws, runpod, output = FakeAws(), FakeRunpod(), io.StringIO()
        with (
            patch.object(MODULE, "RunpodClient", return_value=runpod),
            redirect_stdout(output),
        ):
            MODULE.Registrar(aws).register(
                IMAGE, "template-1", "registry-1", apply=True
            )
        for secret in (
            "operator-private",
            "monitor-private",
            "openai-private",
            "s" * 43,
            "t" * 43,
        ):
            self.assertNotIn(secret, output.getvalue())

    def test_f2_key_import_preserves_general_provider_and_has_no_remote_writes(self):
        aws = FakeAws()
        with (
            patch.object(MODULE, "RunpodClient", return_value=FakeRunpod()),
            patch.object(MODULE, "prompt_secret", side_effect=("a" * 43, "b" * 43)),
            redirect_stdout(io.StringIO()),
        ):
            MODULE.rotate_secret(aws, "f2")
        self.assertEqual(len(aws.puts), 1)
        payload = json.loads(aws.puts[0][1])
        self.assertEqual(payload["AI_OPENAI_API_KEY"], "openai-private")
        self.assertEqual(payload[MODULE.F2_SECRET_NAMES[0]], "a" * 43)
        self.assertEqual(aws.controls, [])

    def test_first_operator_key_does_not_require_existing_operator_secret(self):
        aws = FakeAws(missing=("operator",))
        with (
            patch.object(MODULE, "RunpodClient", return_value=FakeRunpod()),
            patch.object(MODULE, "prompt_secret", return_value="new-operator-key"),
            patch.object(
                aws, "secret_value", side_effect=AssertionError("must not read old key")
            ),
            redirect_stdout(io.StringIO()),
        ):
            MODULE.rotate_secret(aws, "runpod-operator")
        self.assertEqual(len(aws.puts), 1)

    def test_template_validation_accepts_omitted_default_fields(self):
        expected = MODULE.template_payload(
            MODULE.DEFAULT_TEMPLATE,
            IMAGE,
            "registry-1",
            "skn30-final-3team-dev-f2-template-g1",
        )
        actual = dict(expected)
        for field in ("dockerEntrypoint", "isPublic", "isServerless", "volumeInGb"):
            actual.pop(field)

        MODULE.validate_template(actual, expected)

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

    def test_f2_rotation_rejects_active_endpoint_before_prompt_or_secret_write(self):
        aws = FakeAws()
        aws.endpoint_value["status"] = "active"
        with (
            patch.object(MODULE, "RunpodClient", return_value=FakeRunpod()),
            patch.object(MODULE, "prompt_secret") as prompt,
            self.assertRaises(MODULE.ToolError),
        ):
            MODULE.rotate_secret(aws, "f2")
        prompt.assert_not_called()
        self.assertEqual(aws.puts, [])


if __name__ == "__main__":
    unittest.main()
