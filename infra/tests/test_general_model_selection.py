"""Explicit general profiles preserve F2 and prevent readiness for another model."""

import hashlib
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
import download_models
import gpu_host
import manage_serving as serving
from selection_catalog import published_image


class GeneralSelection(unittest.TestCase):
    def test_legacy_defaults_and_explicit_profiles(self):
        legacy = {"cloud": "runpod", "gpu_id": "NVIDIA L40S"}
        with self.assertRaises(serving.ToolError):
            serving.validate_selection("general", legacy)
        with self.assertRaises(serving.ToolError):
            serving.general_profile(legacy)
        for name in (
            "qwen3-14b-awq",
            "qwen3-32b-awq",
            "qwen38-27b-bnb",
            "qwen38-27b-fp8",
        ):
            spec = {**legacy, "model_profile": name}
            serving.validate_selection("general", spec)
            self.assertEqual(serving.general_metadata(spec)["model_profile"], name)
        with self.assertRaises(serving.ToolError):
            serving.validate_selection(
                "general", {**legacy, "model_profile": "arbitrary/model"}
            )
        with self.assertRaises(serving.ToolError):
            serving.validate_selection(
                "f2", {**legacy, "model_profile": "qwen3-14b-awq"}
            )

    def test_endpoint_records_profile_and_revision_without_credentials(self):
        controller = serving.Serving.__new__(serving.Serving)
        controller.write = Mock()
        spec = {"model_profile": "qwen3-32b-awq"}
        controller.activate(
            "general", spec, {"cloud": "runpod", "resource_id": "abc12345"}
        )
        record = controller.write.call_args.args[1]
        self.assertEqual(record["model"], "Qwen/Qwen3-32B-AWQ")
        self.assertEqual(record["revision"], serving.general_profile(spec)["revision"])
        self.assertNotIn("AI_GENERAL_API_KEY", record)
        controller.activate("general", spec, None)
        self.assertEqual(controller.write.call_args.args[1], {"status": "offline"})

    def test_readiness_requires_selected_model_in_both_clouds(self):
        controller = serving.Serving.__new__(serving.Serving)
        controller.secret = Mock(return_value={"AI_GENERAL_API_KEY": "synthetic"})
        controller.command = Mock()
        spec = {
            "cloud": "runpod",
            "resource_id": "abc12345",
            "model_profile": "qwen3-14b-awq",
        }
        with patch.object(serving, "probe") as probe:
            controller.probe("general", spec)
            self.assertEqual(probe.call_args.args[2], "Qwen/Qwen3-14B-AWQ")
        controller.probe("general", {**spec, "cloud": "aws"})
        self.assertIn(
            "--model Qwen/Qwen3-14B-AWQ", controller.command.call_args.args[1]
        )

    def test_application_smoke_follows_committed_candidate_before_selection_changes(
        self,
    ):
        controller = serving.Serving.__new__(serving.Serving)
        controller.app_id = Mock(return_value="app")
        controller.command = Mock()
        controller.endpoint = Mock(
            return_value={"status": "active", "model_profile": "qwen3-32b-awq"}
        )
        controller.selection = Mock(
            return_value={"general": {"model_profile": "qwen3-14b-awq"}}
        )
        controller.application_smoke("general")
        self.assertTrue(
            controller.command.call_args.args[1].endswith(
                "smoke_general.sh Qwen/Qwen3-32B-AWQ"
            )
        )
        controller.selection.assert_not_called()

    def runpod_controller(self, workload="general"):
        image = published_image(
            workload, "qwen3-14b-awq" if workload == "general" else None
        )
        controller = serving.Serving.__new__(serving.Serving)
        controller.read = Mock(
            return_value={
                "status": "ready",
                "image": image,
                "template_id": "template",
                "registry_auth_id": "registry",
            }
        )
        controller.runpod = Mock()
        controller.runpod.return_value.pods.return_value = []
        controller.runpod.return_value.request.return_value = {"id": "abc12345"}
        controller.probe = Mock()
        return controller

    def test_f2_create_does_not_enable_general_cuda_compatibility(self):
        controller = self.runpod_controller("f2")
        controller.release = Mock(return_value=({}, "checksum", "synthetic-url"))
        spec = {
            "cloud": "runpod",
            "gpu_id": "NVIDIA RTX A5000",
            "release_id": "consultation-v3",
            "bucket": "synthetic-bucket",
        }
        with patch.object(serving.control, "validate_template"):
            controller._prepare("f2", spec)
        environment = controller.runpod.return_value.request.call_args.args[2]["env"]
        self.assertNotIn("VLLM_ENABLE_CUDA_COMPATIBILITY", environment)
        self.assertNotIn("GENERAL_MODEL_PROFILE", environment)
        self.assertNotIn(
            "allowedCudaVersions",
            controller.runpod.return_value.request.call_args.args[2],
        )

    def test_unavailable_cuda_capacity_is_not_retried_without_constraint(self):
        controller = self.runpod_controller()
        controller.runpod.return_value.request.side_effect = serving.f2.ToolError(
            "capacity unavailable"
        )
        spec = {
            "cloud": "runpod",
            "gpu_id": "NVIDIA L40S",
            "model_profile": "qwen3-14b-awq",
        }
        with (
            patch.object(serving.control, "validate_template"),
            self.assertRaises(serving.f2.ToolError),
        ):
            controller.prepare("general", spec)
        controller.runpod.return_value.request.assert_called_once()
        controller.probe.assert_not_called()
        controller.runpod.return_value.delete.assert_not_called()

    def test_reuse_requires_explicit_disabled_cuda_compatibility(self):
        spec = {
            "cloud": "runpod",
            "gpu_id": "NVIDIA L40S",
            "model_profile": "qwen3-14b-awq",
        }
        for compatibility in ("1", None, "0"):
            with self.subTest(compatibility=compatibility):
                controller = self.runpod_controller()
                controller.runpod.return_value.pods.return_value = [
                    {"name": serving.POD_NAME["general"], "id": "abc12345"}
                ]
                environment = {"GENERAL_MODEL_PROFILE": "qwen3-14b-awq"}
                if compatibility is not None:
                    environment["VLLM_ENABLE_CUDA_COMPATIBILITY"] = compatibility
                controller.runpod.return_value.pod.return_value = {
                    "id": "abc12345",
                    "imageName": published_image("general", "qwen3-14b-awq"),
                    "templateId": "template",
                    "desiredStatus": "RUNNING",
                    "env": environment,
                }
                with patch.object(serving.control, "validate_template"):
                    if compatibility == "0":
                        deployment = controller.prepare("general", spec)
                        self.assertEqual(deployment["resource_id"], "abc12345")
                        controller.probe.assert_called_once()
                    else:
                        with self.assertRaisesRegex(
                            serving.ToolError, "disable CUDA compatibility"
                        ):
                            controller.prepare("general", spec)
                        controller.probe.assert_not_called()
                controller.runpod.return_value.request.assert_not_called()
                controller.runpod.return_value.delete.assert_not_called()

    def test_create_injects_profile_and_rejects_existing_other_profile(self):
        controller = self.runpod_controller()
        spec = {
            "cloud": "runpod",
            "gpu_id": "NVIDIA L40S",
            "model_profile": "qwen3-32b-awq",
        }
        with patch.object(serving.control, "validate_template"):
            deployment = controller._prepare("general", spec)
        self.assertEqual(deployment["model"], "Qwen/Qwen3-32B-AWQ")
        self.assertEqual(
            controller.runpod.return_value.request.call_args.args[2][
                "allowedCudaVersions"
            ],
            ["13.0"],
        )
        self.assertEqual(
            controller.runpod.return_value.request.call_args.args[2]["env"],
            {
                "GENERAL_MODEL_PROFILE": "qwen3-32b-awq",
                "VLLM_ENABLE_CUDA_COMPATIBILITY": "0",
                "SERVING_IMAGE": published_image("general", "qwen3-32b-awq"),
            },
        )
        controller.runpod.return_value.request.reset_mock()
        controller.runpod.return_value.pods.return_value = [
            {"name": serving.POD_NAME["general"], "id": "abc12345"}
        ]
        controller.runpod.return_value.pod.return_value = {
            "imageName": published_image("general", "qwen3-14b-awq"),
            "templateId": "template",
            "env": {"GENERAL_MODEL_PROFILE": "qwen3-14b-awq"},
        }
        with (
            patch.object(serving.control, "validate_template"),
            self.assertRaisesRegex(serving.ToolError, "different model profile"),
        ):
            controller._prepare("general", spec)
        controller.runpod.return_value.request.assert_not_called()


class HostProfiles(unittest.TestCase):
    def test_candidate_profile_overrides_old_aws_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "root"
            root.mkdir()
            data = Path(directory) / "data"
            (root / "config.json").write_text(
                json.dumps(
                    {
                        "workload": "general",
                        "prefix": "test",
                        "image": "image",
                        "model": "legacy",
                        "revision": "legacy",
                    }
                )
            )
            (root / "candidate.json").write_text(
                json.dumps({"cloud": "aws", "model_profile": "qwen3-14b-awq"})
            )
            replies = [
                {"Parameter": {"Value": json.dumps({"general": {"cloud": "aws"}})}},
                {"SecretString": json.dumps({"AI_GENERAL_API_KEY": "synthetic"})},
                {
                    "SecretString": json.dumps(
                        {"username": "fixture", "token": "synthetic"}
                    )
                },
            ]
            with (
                patch.object(gpu_host, "ROOT", root),
                patch.object(gpu_host, "DATA", data),
                patch.object(gpu_host, "aws", side_effect=replies),
                patch.object(gpu_host, "run"),
            ):
                gpu_host.main()
            models = json.loads((root / "models.json").read_text())
            self.assertEqual(models[0]["model"], "Qwen/Qwen3-14B-AWQ")
            self.assertTrue(models[0]["weights"])
            self.assertIn(
                "GENERAL_MODEL_PROFILE=qwen3-14b-awq",
                (root / "runtime.env").read_text(),
            )
            self.assertIn(
                "VLLM_ENABLE_CUDA_COMPATIBILITY=0", (root / "runtime.env").read_text()
            )
            self.assertFalse((root / "candidate.json").exists())

    def test_corrupt_download_never_receives_success_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model"

            def snapshot_download(**kwargs):
                path.mkdir(exist_ok=True)
                (path / "weights.safetensors").write_bytes(b"bad")

            module = Mock(snapshot_download=snapshot_download)
            item = {
                "path": str(path),
                "model": "synthetic",
                "revision": "fixed",
                "weights": [
                    {
                        "name": "weights.safetensors",
                        "size": 3,
                        "sha256": hashlib.sha256(b"yes").hexdigest(),
                    }
                ],
            }
            with (
                patch.dict(sys.modules, {"huggingface_hub": module}),
                self.assertRaisesRegex(ValueError, "digest mismatch"),
            ):
                download_models.download([item])
            self.assertFalse((path / ".serving-revision").exists())
            item["weights"][0]["sha256"] = hashlib.sha256(b"bad").hexdigest()
            with patch.dict(sys.modules, {"huggingface_hub": module}):
                download_models.download([item])
            self.assertEqual(
                (path / ".serving-revision").read_text(), "synthetic@fixed"
            )


if __name__ == "__main__":
    unittest.main()
