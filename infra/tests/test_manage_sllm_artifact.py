import importlib.util
import json
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "infra/scripts/manage_sllm_artifact.py"
SPEC = importlib.util.spec_from_file_location("manage_sllm_artifact", PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class BundleTests(unittest.TestCase):
    def make_bundle(self, root: Path) -> Path:
        adapter = root / "adapter"
        adapter.mkdir()
        (adapter / "adapter_config.json").write_text("{}\n", encoding="utf-8")
        (adapter / "adapter_model.safetensors").write_bytes(b"weights")
        evaluation = root / "evaluation-summary.json"
        evaluation.write_text(
            json.dumps(
                {
                    "run_id": "evaluation-full-001",
                    "task": "full",
                    "models": [{"label": "candidate"}],
                }
            ),
            encoding="utf-8",
        )
        approval = root / "promotion-approval.json"
        approval.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "approved",
                    "evaluation_run_id": "evaluation-full-001",
                    "selected_model": "candidate",
                    "decision_owner": "fine-tuning-owner",
                    "rationale": "Full evaluation was reviewed for shared dev promotion.",
                }
            ),
            encoding="utf-8",
        )
        files = sorted(adapter.iterdir())
        manifest = {
            "schema_version": 1,
            "release_id": "release-v1",
            "capability": MODULE.CAPABILITY,
            "served_model_name": MODULE.SERVED_MODEL_NAME,
            "created_at": "2026-09-01T00:00:00+00:00",
            "base_model": {"id": "Qwen/Qwen3-4B", "revision": "a" * 40},
            "adapter": {
                "format": "peft-lora",
                "path": "adapter",
                "sha256": MODULE._tree_sha256(
                    [(p.name, p.read_bytes()) for p in files]
                ),
                "size_bytes": sum(p.stat().st_size for p in files),
                "file_count": len(files),
            },
            "training": {
                "code_revision": "b" * 40,
                "dataset_release": "f2-v1",
                "train_sha256": "c" * 64,
                "validation_sha256": "d" * 64,
            },
            "evaluation": {
                "task": "full",
                "summary_path": "evaluation-summary.json",
                "summary_sha256": MODULE.file_sha256(evaluation),
                "promotion_status": "approved",
                "selected_model": "candidate",
                "approval_path": "promotion-approval.json",
                "approval_sha256": MODULE.file_sha256(approval),
            },
        }
        release = root / "release.json"
        release.write_text(json.dumps(manifest), encoding="utf-8")
        bundle = root / "bundle.tar.gz"
        with tarfile.open(bundle, "w:gz") as archive:
            archive.add(release, arcname="release.json")
            archive.add(evaluation, arcname="evaluation-summary.json")
            archive.add(approval, arcname="promotion-approval.json")
            for path in files:
                archive.add(path, arcname=f"adapter/{path.name}")
        return bundle

    def test_valid_bundle_is_inspected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bundle = self.make_bundle(Path(directory))
            inspected = MODULE.inspect_bundle(bundle)
        self.assertEqual(inspected.release_id, "release-v1")
        self.assertEqual(inspected.manifest["served_model_name"], "sllm")

    def test_bundle_with_extra_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = self.make_bundle(root)
            extra = root / "raw-transcript.jsonl"
            extra.write_text("private", encoding="utf-8")
            with tarfile.open(bundle, "w:gz") as archive:
                archive.add(root / "release.json", arcname="release.json")
                archive.add(
                    root / "evaluation-summary.json", arcname="evaluation-summary.json"
                )
                archive.add(
                    root / "promotion-approval.json", arcname="promotion-approval.json"
                )
                for path in sorted((root / "adapter").iterdir()):
                    archive.add(path, arcname=f"adapter/{path.name}")
                archive.add(extra, arcname="raw-transcript.jsonl")
            with self.assertRaises(MODULE.ToolError):
                MODULE.inspect_bundle(bundle)

    def test_bundle_with_unmatched_promotion_approval_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = self.make_bundle(root)
            approval = root / "promotion-approval.json"
            value = json.loads(approval.read_text(encoding="utf-8"))
            value["selected_model"] = "different-model"
            approval.write_text(json.dumps(value), encoding="utf-8")
            with tarfile.open(bundle, "w:gz") as archive:
                archive.add(root / "release.json", arcname="release.json")
                archive.add(root / "evaluation-summary.json", arcname="evaluation-summary.json")
                archive.add(approval, arcname="promotion-approval.json")
                for path in sorted((root / "adapter").iterdir()):
                    archive.add(path, arcname=f"adapter/{path.name}")
            with self.assertRaises(MODULE.ToolError):
                MODULE.inspect_bundle(bundle)


class FakeExecutor:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, command):
        self.calls.append(list(command))
        return subprocess.CompletedProcess(command, 0, "https://signed.example\n", "")


class AwsCliTests(unittest.TestCase):
    def test_presign_does_not_embed_credentials_in_arguments(self) -> None:
        executor = FakeExecutor()
        client = MODULE.AwsCli(executor, profile="team", region="ap-northeast-2")
        result = client.presign(
            bucket="private", key="releases/sllm/r/bundle.tar.gz", expires=3600
        )
        self.assertEqual(result, "https://signed.example")
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", " ".join(executor.calls[0]))


if __name__ == "__main__":
    unittest.main()
