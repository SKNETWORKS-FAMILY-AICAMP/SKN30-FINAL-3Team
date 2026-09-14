"""Exercise the real Terraform selection validation without AWS or state access."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("terraform"), "Terraform is required")
class GeneralSelectionValidation(unittest.TestCase):
    def plan(
        self,
        selection=None,
        *,
        filename="general-model.tf",
        variable="general_model_selection",
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copyfile(ROOT / "environments/dev" / filename, root / "selection.tf")
            if selection is not None:
                (root / "selection.auto.tfvars.json").write_text(
                    json.dumps({variable: selection})
                )
            return subprocess.run(
                ["terraform", "plan", "-input=false", "-lock=false", "-no-color"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )

    def test_app_deployment_mode_has_only_explicit_transition_choices(self):
        for mode in (None, "automatic", "maintenance", "typo"):
            with self.subTest(mode=mode):
                result = self.plan(
                    mode, filename="deployment-mode.tf", variable="app_deployment_mode"
                )
                if mode == "typo":
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("Invalid value for variable", result.stderr)
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_supported_defaults_and_provider_pairs(self):
        for selection in (
            None,
            {"provider": "openai", "model": "gpt-5.6-luna"},
            {
                "provider": "bedrock",
                "model": "global.openai.gpt-5.6-luna",
                "aws_region": "ap-northeast-2",
            },
            {"provider": "vllm", "model": "Qwen/Qwen3-14B-AWQ"},
        ):
            with self.subTest(selection=selection):
                result = self.plan(selection)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_invalid_pairs_and_provider_specific_regions_rejected(self):
        for selection in (
            {"provider": "anything", "model": "gpt-5.6-luna"},
            {"provider": "vllm", "model": "gpt-5.6-luna"},
            {
                "provider": "vllm",
                "model": "Qwen/Qwen3.8-27B-FP8",
                "aws_region": "ap-northeast-2",
            },
            {"provider": "bedrock", "model": "global.openai.gpt-5.6-luna"},
            {
                "provider": "bedrock",
                "model": "global.openai.gpt-5.6-luna",
                "aws_region": "us-east-1",
            },
        ):
            with self.subTest(selection=selection):
                result = self.plan(selection)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Invalid value for variable", result.stderr)


if __name__ == "__main__":
    unittest.main()
