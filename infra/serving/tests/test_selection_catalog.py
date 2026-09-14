"""Offline migration and fail-closed selection contracts."""

import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import selection_catalog as catalog


class SelectionCatalog(unittest.TestCase):
    def f2(self, **changes):
        return {
            "cloud": "runpod",
            "gpu_id": "NVIDIA RTX A5000",
            "release_id": "consultation-v3",
            "bucket": "synthetic-model-bucket",
            **changes,
        }

    def general(self, **changes):
        return {
            "cloud": "runpod",
            "gpu_id": "NVIDIA L40S",
            "model_profile": "qwen38-27b-fp8",
            **changes,
        }

    def test_existing_selection_preserves_cloud_model_and_gpu(self):
        actual = catalog.normalize_spec("f2", self.f2())
        self.assertEqual(actual["hardware_profile"], "runpod-a5000-24gb")
        self.assertEqual(actual["release_id"], "consultation-v3")
        self.assertEqual(actual["gpu_id"], "NVIDIA RTX A5000")
        self.assertEqual(catalog.normalize_spec("f2", actual), actual)
        general = catalog.normalize_spec("general", self.general())
        self.assertEqual(general["model_profile"], "qwen38-27b-fp8")
        self.assertEqual(catalog.normalize_spec("general", general), general)

    def test_aws_drops_unused_legacy_runpod_gpu_field(self):
        for workload, spec, instance in (
            ("f2", self.f2(cloud="aws"), "aws-g6-2xlarge"),
            ("general", self.general(cloud="aws"), "aws-g6e-2xlarge"),
        ):
            actual = catalog.normalize_spec(workload, spec)
            self.assertEqual(actual["hardware_profile"], instance)
            self.assertNotIn("gpu_id", actual)
            self.assertIn("@sha256:", actual["image"])

    def test_image_update_preserves_saved_selection_and_its_evidence(self):
        saved = catalog.normalize_spec("f2", self.f2())
        modified = copy.deepcopy(catalog.load_catalog())
        old_evidence = copy.deepcopy(modified["f2_image"])
        new_image = saved["image"].split("@sha256:")[0] + "@sha256:" + "a" * 64
        modified["f2_image"] = {"image": new_image, "status": "pending-new-image"}
        with patch.object(catalog, "load_catalog", return_value=modified):
            self.assertEqual(catalog.normalize_spec("f2", saved), saved)
            self.assertEqual(
                catalog.validation_metadata("f2", saved)["image_evidence"], old_evidence
            )
            self.assertEqual(
                catalog.normalize_spec("f2", self.f2())["image"], new_image
            )

    def test_unknown_and_cross_workload_fields_rejected(self):
        for workload, spec in (
            ("f2", self.f2(model_profile="qwen38-27b-fp8")),
            ("general", self.general(release_id="consultation-v3")),
            ("f2", self.f2(enabled=True)),
        ):
            with self.subTest(workload=workload), self.assertRaises(ValueError):
                catalog.normalize_spec(workload, spec)

    def test_arbitrary_gpu_or_incompatible_hardware_fails(self):
        for changes in (
            {"gpu_id": "NVIDIA A100"},
            {"hardware_profile": "runpod-l40s-48gb"},
            {"hardware_profile": "aws-g6-2xlarge"},
            {"hardware_profile": "runpod-rtx4090-24gb"},
            {"cloud": "cpu"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                catalog.normalize_spec("f2", self.f2(**changes))

    def test_model_and_image_must_be_explicit_supported_combination(self):
        for changes in (
            {"model_profile": None},
            {"model_profile": "arbitrary"},
            {"image": "ghcr.io/project/general:latest"},
            {
                "image": "ghcr.io/sknetworks-family-aicamp/skn30-final-3team/general-serving@sha256:ce0e6e07d3656b81c63b4698e82f04421548b4f06ab1e428e9de3778adf9da6e"
            },
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                catalog.normalize_spec("general", self.general(**changes))
        for profile in catalog.GeneralModelProfile:
            self.assertEqual(
                catalog.normalize_spec(
                    "general", self.general(model_profile=profile.value)
                )["model_profile"],
                profile.value,
            )

    def test_f2_requires_known_release_and_explicit_dev_opt_in(self):
        for changes in (
            {"release_id": "unknown"},
            {"release_id": "dev-f2-handwritten-v05-qwen3-4b-full-v1"},
            {"allow_dev_release": "true"},
            {"bucket": "https://bucket"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                catalog.normalize_spec("f2", self.f2(**changes))
        self.assertTrue(
            catalog.normalize_spec(
                "f2",
                self.f2(
                    release_id="dev-f2-handwritten-v05-qwen3-4b-full-v1",
                    allow_dev_release=True,
                ),
            )["allow_dev_release"]
        )

    def test_insufficient_catalog_memory_rejected_without_fallback(self):
        modified = copy.deepcopy(catalog.load_catalog())
        modified["profiles"]["runpod-l40s-48gb"]["vram_gb"] = 24
        with (
            patch.object(catalog, "load_catalog", return_value=modified),
            self.assertRaisesRegex(ValueError, "insufficient"),
        ):
            catalog.normalize_spec("general", self.general())

    def test_candidate_evidence_does_not_certify_new_release(self):
        for cloud in catalog.Cloud:
            result = catalog.validation_metadata("f2", self.f2(cloud=cloud.value))
            self.assertEqual(result["status"], "pending-user-startup-check")
            self.assertEqual(result["release_id"], "consultation-v3")
            self.assertEqual(result["memory_budget"]["sllm_fraction"], 0.65)
            self.assertIn("not measured", result["memory_budget"]["meaning"])
        general = catalog.validation_metadata(
            "general",
            self.general(
                image="ghcr.io/sknetworks-family-aicamp/skn30-final-3team/general-serving@sha256:801473c822b3536c58dd310f0768dfacf0aebd968c06a4ea427d0d9561f5c1e7"
            ),
        )
        self.assertEqual(general["image_profile_evidence"]["status"], "evaluated")
        self.assertEqual(general["status"], "pending-user-startup-check")


if __name__ == "__main__":
    unittest.main()
