"""Behavioral regression tests for routing, maintenance, and cloud ownership."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "scripts"),
    str(ROOT / "deploy/scripts"),
    str(ROOT / "serving"),
]
import manage_serving as serving
import render_env
from connect_serving import local_environment
from serving_contract import GENERAL_KEY, aws_base_url, endpoint_urls
from serving_selection import document


class Contracts(unittest.TestCase):
    def test_f2_aws_pair_and_legacy_runpod_roundtrip(self):
        for deployment in (
            {
                "cloud": "aws",
                "resource_id": "i-1234567890abcdef0",
                "private_ip": "10.30.0.15",
            },
            {"cloud": "runpod", "resource_id": "abc12345"},
        ):
            value = serving.f2_record({"revision": 1}, deployment, "dev-example")
            result = render_env.parse_ai_vllm_endpoint_set(json.dumps(value))
            self.assertEqual(result["_f2_status"], "active")
            self.assertNotEqual(
                result["AI_VLLM_SLLM_BASE_URL"], result["AI_VLLM_STT_BASE_URL"]
            )
            self.assertEqual(
                render_env.parse_ai_vllm_endpoint_set(
                    json.dumps(serving.f2_record(value, None, None))
                ),
                {"_f2_status": "offline"},
            )

    def test_aws_does_not_accept_other_host_or_port(self):
        for url in (
            "http://10.30.0.16:8001/v1",
            "http://10.30.0.15:8002/v1",
            "http://10.30.0.15:8001/v1?key=x",
            "https://example.com/v1",
        ):
            with self.assertRaises(ValueError):
                aws_base_url(
                    url,
                    instance_id="i-1234567890abcdef0",
                    private_ip="10.30.0.15",
                    port=8001,
                )
        with self.assertRaises(ValueError):
            aws_base_url(
                "http://169.254.169.254:8001/v1",
                instance_id="i-1234567890abcdef0",
                private_ip="169.254.169.254",
                port=8001,
            )

    def test_runpod_cannot_overwrite_aws_endpoint(self):
        with self.assertRaises(serving.f2.ToolError):
            serving.f2.endpoint_value(
                previous={"cloud": "aws", "revision": 4}, status="offline"
            )

    def test_general_alias_survives_cloud_change(self):
        for url in (
            "http://127.0.0.1:8000/v1",
            endpoint_urls("runpod", "abc12345", "general")[0],
        ):
            value = local_environment("general", [url], ["a" * 43], "qwen38-27b-fp8")
            self.assertEqual(value["AI_GENERAL_PROVIDER"], "vllm")
            self.assertEqual(value["AI_GENERAL_MODEL"], "Qwen/Qwen3.8-27B-FP8")
            self.assertEqual(value["AI_GENERAL_BASE_URL"], url)
            self.assertEqual(value[GENERAL_KEY], "a" * 43)
            self.assertNotIn("MODEL_PROFILE", value)
            self.assertNotIn("AI_OPENAI_API_KEY", value)

    def test_connect_rejects_unknown_general_profile(self):
        with self.assertRaises(ValueError):
            local_environment(
                "general", ["http://127.0.0.1:18000/v1"], ["k" * 43], "unknown"
            )

    def test_general_registration_contract(self):
        source = json.loads((ROOT / "serving/general-template.json").read_text())
        payload = serving.control.template_payload(
            source, "image", "registry", source["name"]
        )
        self.assertEqual(payload["ports"], ["8000/http"])
        self.assertEqual(payload["volumeInGb"], 0)
        self.assertIn(GENERAL_KEY, payload["env"])

    def test_secret_not_in_general_endpoint_registry(self):
        f2_offline = serving.f2_record({"revision": 0}, None, None)
        public = {
            "backend": {},
            "ai": {
                "AI_VLLM_ENDPOINT_SET": json.dumps(f2_offline),
                "AI_GENERAL_ENDPOINT_SET": json.dumps(
                    {
                        "status": "active",
                        "cloud": "runpod",
                        "resource_id": "abc12345",
                        "base_url": "https://abc12345-8000.proxy.runpod.net/v1",
                        "model_profile": "qwen38-27b-fp8",
                        "model": "Qwen/Qwen3.8-27B-FP8",
                    }
                ),
                "AI_GENERAL_PROVIDER": "vllm",
                "AI_GENERAL_MODEL": "Qwen/Qwen3.8-27B-FP8",
            },
        }
        api, worker, _ = render_env.build_process_environments(
            public=public,
            runtime_url="db",
            migration_url="migration",
            ai_provider_keys={GENERAL_KEY: "g" * 43},
        )
        self.assertNotIn(GENERAL_KEY, api)
        self.assertEqual(worker[GENERAL_KEY], "g" * 43)
        self.assertNotIn("g" * 43, worker["AI_GENERAL_BASE_URL"])


class Cutover(unittest.TestCase):
    def controller(self):
        controller = serving.Serving.__new__(serving.Serving)
        controller.selection = Mock(
            return_value={
                "f2": None,
                "general": {
                    "cloud": "runpod",
                    "gpu_id": "NVIDIA L40S",
                    "model_profile": "qwen38-27b-fp8",
                },
            }
        )
        controller.no_deployment = Mock()
        controller.endpoint = Mock(return_value={"status": "offline"})
        controller.power = Mock()
        controller.power.describe_asg.return_value = {
            "DesiredCapacity": 0,
            "Instances": [],
        }
        controller.instances = Mock(return_value=[])
        controller.managed_pods = Mock(return_value=[])
        controller.selection_document = Mock(
            return_value=document(controller.selection())
        )
        controller.session = Mock()
        controller.session.client.return_value.get_caller_identity.return_value = {
            "Arn": "arn:aws:iam::123456789012:role/operator"
        }
        controller.prepare = Mock(
            return_value={
                "cloud": "aws",
                "resource_id": "i-1234567890abcdef0",
                "private_ip": "10.30.0.10",
            }
        )
        controller.app = Mock()
        controller.activate = Mock()
        controller.application_smoke = Mock()
        controller.app_id = Mock(return_value="maintenance-host")
        controller.command = Mock()
        controller.write = Mock()
        controller.stop_resources = Mock()
        return controller

    def test_plan_never_prepares_or_writes(self):
        c = self.controller()
        c.switch("general", "aws", apply=False)
        c.prepare.assert_not_called()
        c.write.assert_not_called()

    def test_active_endpoint_refuses_switch_without_drain_or_gpu_changes(self):
        c = self.controller()
        c.endpoint.return_value = {"status": "active"}
        with self.assertRaisesRegex(serving.ToolError, "offline"):
            c.switch("general", "aws", apply=True)
        c.app.assert_not_called()
        c.prepare.assert_not_called()
        c.activate.assert_not_called()
        c.write.assert_not_called()

    def test_running_app_refuses_switch(self):
        c = self.controller()
        c.power.describe_asg.return_value = {"DesiredCapacity": 1, "Instances": []}
        with self.assertRaisesRegex(serving.ToolError, "host must be stopped"):
            c.switch("general", "aws", apply=True)
        c.app.assert_not_called()
        c.write.assert_not_called()

    def test_running_aws_gpu_refuses_switch(self):
        c = self.controller()
        c.instances.return_value = [{"State": {"Name": "running"}}]
        with self.assertRaisesRegex(serving.ToolError, "GPUs stopped"):
            c.switch("general", "aws", apply=True)
        c.stop_resources.assert_not_called()
        c.write.assert_not_called()

    def test_remaining_managed_pod_refuses_switch(self):
        c = self.controller()
        c.managed_pods.return_value = [{"id": "existing-pod"}]
        with self.assertRaisesRegex(serving.ToolError, "Pods deleted"):
            c.switch("general", "aws", apply=True)
        c.stop_resources.assert_not_called()
        c.write.assert_not_called()

    def test_offline_switch_only_saves_selection_and_preserves_model(self):
        c = self.controller()
        c.switch("general", "aws", apply=True)
        c.prepare.assert_not_called()
        c.app.assert_not_called()
        c.activate.assert_not_called()
        c.stop_resources.assert_not_called()
        suffix, value = c.write.call_args.args
        self.assertEqual(suffix, "serving/SELECTION")
        self.assertEqual(value["general"]["cloud"], "aws")
        self.assertEqual(value["general"]["model_profile"], "qwen38-27b-fp8")
        self.assertIsNone(value["f2"])

    def test_same_cloud_while_active_is_still_refused(self):
        c = self.controller()
        c.endpoint.return_value = {"status": "active"}
        with self.assertRaises(serving.ToolError):
            c.switch("general", "runpod", apply=True)
        c.prepare.assert_not_called()
        c.write.assert_not_called()


class LifecycleFailures(unittest.TestCase):
    def test_deep_capacity_uses_only_selected_aws_but_switch_preserves_instances(self):
        c = Cutover().controller()
        c.selection.return_value = {
            "f2": {"cloud": "aws"},
            "general": {"cloud": "runpod"},
        }
        c.instances = Mock(return_value=[{"InstanceId": "fixture"}])
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(serving, "INFRA", Path(directory)),
        ):
            path = Path(directory) / "environments/dev"
            path.mkdir(parents=True)
            c.capacity_config()
            self.assertEqual(
                json.loads((path / "serving-capacity.auto.tfvars.json").read_text())[
                    "gpu_provisioned_workloads"
                ],
                ["f2"],
            )
            c.capacity_config("general")
            self.assertEqual(
                json.loads((path / "serving-capacity.auto.tfvars.json").read_text())[
                    "gpu_provisioned_workloads"
                ],
                ["f2", "general"],
            )

    def test_stop_continues_other_gpus_and_app_shutdown_after_failure(self):
        c = Cutover().controller()
        c.power = Mock()
        c.stop_resources.side_effect = [serving.ToolError("f2 shutdown failed"), None]
        with self.assertRaises(serving.ToolError):
            c.stop()
        self.assertEqual(
            [call.args[0] for call in c.stop_resources.call_args_list],
            ["f2", "general"],
        )
        c.power.stop.assert_called_once()

    def test_stop_aborts_every_gpu_mutation_on_failed_drain(self):
        c = Cutover().controller()
        c.power = Mock()
        c.app.side_effect = serving.ToolError("busy")
        with self.assertRaises(serving.ToolError):
            c.stop()
        c.activate.assert_not_called()
        c.stop_resources.assert_not_called()
        c.power.stop.assert_not_called()

    def test_start_delegates_failure_to_shared_lifecycle(self):
        c = Cutover().controller()
        with patch("serving_lifecycle.Lifecycle") as lifecycle:
            lifecycle.return_value.run.side_effect = serving.ToolError(
                "deployment failed"
            )
            with self.assertRaisesRegex(serving.ToolError, "deployment failed"):
                c.start(apply=True, hours=1)
        lifecycle.assert_called_once_with(c)
        lifecycle.return_value.run.assert_called_once_with(apply=True, hours=1)

    def test_operational_parameters_are_not_application_environment(self):
        payload = {
            "Parameters": [
                {"Name": "/project-dev/" + suffix, "Value": "{}"}
                for suffix in (
                    "runpod/RUNPOD_CONTROL_SET",
                    "runpod/GENERAL_CONTROL_SET",
                    "serving/SELECTION",
                )
            ]
        }
        self.assertEqual(
            render_env.parse_public_parameters(payload, "/project-dev"),
            {"ai": {}, "backend": {}},
        )

    def test_general_url_must_match_registered_resource(self):
        public = {
            "backend": {},
            "ai": {
                "AI_VLLM_ENDPOINT_SET": json.dumps(serving.f2_record({}, None, None)),
                "AI_GENERAL_ENDPOINT_SET": json.dumps(
                    {
                        "status": "active",
                        "cloud": "runpod",
                        "resource_id": "abc12345",
                        "base_url": "https://different-8000.proxy.runpod.net/v1",
                    }
                ),
            },
        }
        with self.assertRaises(SystemExit):
            render_env.expand_ai_vllm_endpoint_set(public)


class PreparationFailures(unittest.TestCase):
    def test_timeout_deletes_only_new_runpod_candidate(self):
        c = Cutover().controller()
        del c.prepare
        candidate = {"cloud": "runpod", "resource_id": "new12345"}

        def fail(*args):
            c.started_candidate = candidate
            raise serving.ToolError("model readiness timed out")

        c._prepare = fail
        c.runpod = Mock()
        with self.assertRaises(serving.ToolError):
            c.prepare("general", {"cloud": "runpod"})
        c.runpod.return_value.delete.assert_called_once_with("new12345")
        c.activate.assert_not_called()

    def test_preexisting_candidate_is_not_deleted_on_probe_failure(self):
        c = Cutover().controller()
        del c.prepare
        c._prepare = Mock(side_effect=serving.ToolError("bad inference"))
        c.runpod = Mock()
        with self.assertRaises(serving.ToolError):
            c.prepare("general", {"cloud": "runpod"})
        c.runpod.assert_not_called()

    def test_failed_selection_commit_stays_in_maintenance(self):
        c = Cutover().controller()
        c.write.side_effect = serving.ToolError("SSM unavailable")
        with self.assertRaises(serving.ToolError):
            c.switch("general", "aws", apply=True)
        c.app.assert_not_called()
        c.activate.assert_not_called()
        c.prepare.assert_not_called()
        c.stop_resources.assert_not_called()


class ExternalProbeHeaders(unittest.TestCase):
    def test_status_and_generation_keep_auth_and_explicit_user_agent(self):
        import io

        import probe as gpu_probe

        replies = [
            {"data": [{"id": "test-model"}]},
            {"disk_free_bytes": 1024},
            {"data": [{"id": "test-model"}]},
            {"choices": [{"message": {"content": '{"ok": true}'}}]},
        ]
        requests = []

        def open_request(request, timeout):
            requests.append(request)
            return io.BytesIO(json.dumps(replies.pop(0)).encode())

        opener = Mock()
        opener.open.side_effect = open_request
        with patch.object(
            gpu_probe.urllib.request, "build_opener", return_value=opener
        ):
            self.assertEqual(
                gpu_probe.read_status(
                    "https://example.invalid/v1", "synthetic", "test-model"
                ),
                {"model_ready": True, "disk_free_bytes": 1024},
            )
            gpu_probe.probe("https://example.invalid/v1", "synthetic", "test-model")
        self.assertEqual(len(requests), 4)
        for request in requests:
            self.assertEqual(request.get_header("User-agent"), "skn30-infra/1.0")
            self.assertEqual(request.get_header("Authorization"), "Bearer synthetic")


if __name__ == "__main__":
    unittest.main()
