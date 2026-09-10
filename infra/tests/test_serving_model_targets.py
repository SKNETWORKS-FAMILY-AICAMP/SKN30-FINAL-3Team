"""Maintenance orchestration requires explicit, reviewed targets before DB writes."""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from serving_model_targets import AppDeploymentRequired, ModelTargets, ToolError

SELECTION = {"general": {"model_profile": "qwen38-27b-fp8"}}


def preview(compatible=False, pending=0):
    return {
        "desired": {"provider": "vllm", "model_name": "new-model"},
        "snapshot": "a" * 64,
        "targets": [
            {
                "brokerage_id": 7,
                "capability": "CHATBOT",
                "current": [{"model_name": "old"}],
                "compatible": compatible,
                "pending_work": pending,
            }
        ],
    }


class ModelTargetsTest(unittest.TestCase):
    def test_fresh_host_requires_app_deploy_before_backend_cli(self):
        serving = Mock()
        serving.app_id.return_value = None
        with self.assertRaisesRegex(AppDeploymentRequired, "app-deploy"):
            ModelTargets(serving).preview(SELECTION)
        serving.command.assert_not_called()

    def test_old_revision_requires_app_deploy(self):
        serving = Mock()
        serving.command.return_value = "app-deploy-required"
        with self.assertRaises(AppDeploymentRequired):
            ModelTargets(serving).preview(SELECTION)
        self.assertEqual(serving.command.call_count, 1)

    def test_preview_passes_explicit_model_without_endpoint_or_secret(self):
        serving = Mock()
        serving.command.side_effect = [
            "supported",
            "model-targets-ready",
            json.dumps(preview()),
        ]
        self.assertEqual(ModelTargets(serving).preview(SELECTION), preview())
        command = serving.command.call_args.args[1]
        self.assertIn(
            "--provider vllm --model Qwen/Qwen3.8-27B-FP8 --list-targets", command
        )
        self.assertNotIn("--apply", command)

    def test_omitted_incompatible_target_blocks_before_gpu_start(self):
        with self.assertRaisesRegex(ToolError, "remain"):
            ModelTargets.choose(preview(), input_fn=lambda _: "")

    def test_before_after_targets_require_confirmation(self):
        replies = iter(["7:CHATBOT", "no"])
        with self.assertRaisesRegex(ToolError, "not confirmed"):
            ModelTargets.choose(preview(), input_fn=lambda _: next(replies))
        replies = iter(["7:CHATBOT", "yes"])
        self.assertEqual(
            ModelTargets.choose(preview(), input_fn=lambda _: next(replies)),
            ["7:CHATBOT"],
        )

    def test_pending_requests_block_without_prompting(self):
        ask = Mock()
        with self.assertRaisesRegex(ToolError, "queued"):
            ModelTargets.choose(preview(pending=1), input_fn=ask)
        ask.assert_not_called()

    def test_apply_transmits_reviewed_snapshot_and_only_explicit_targets(self):
        serving = Mock()
        serving.command.side_effect = [
            "supported",
            "model-targets-ready",
            '{"applied":["7:CHATBOT"]}',
        ]
        ModelTargets(serving).apply(SELECTION, ["7:CHATBOT"], "a" * 64)
        command = serving.command.call_args.args[1]
        self.assertIn("--target 7:CHATBOT", command)
        self.assertIn("--expected-snapshot " + "a" * 64, command)
        self.assertIn("--workloads-stopped", command)

    def test_malformed_ssm_response_never_counts_as_success(self):
        serving = Mock()
        serving.command.side_effect = [
            "supported",
            "model-targets-ready",
            '{"targets":',
        ]
        with self.assertRaisesRegex(ToolError, "truncated"):
            ModelTargets(serving).preview(SELECTION)


if __name__ == "__main__":
    unittest.main()
