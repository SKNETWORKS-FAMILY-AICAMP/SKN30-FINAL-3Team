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

    def make_base_bundle(self, root: Path) -> Path:
        summary = {
            "run_id": "evaluation-full-002",
            "task": "full",
            "release_mode": "base",
            "dataset_release": "f2-2.0.0",
            "dataset_sha256": "e" * 64,
            "models": [
                {
                    "label": "base-candidate",
                    "model_id": "Qwen/Qwen3-4B",
                    "resolved_model_revision": "a" * 40,
                    "adapter_sha256": None,
                }
            ],
        }
        approval_value = {
            "schema_version": 2,
            "release_mode": "base",
            "status": "approved",
            "evaluation_run_id": "evaluation-full-002",
            "selected_model": "base-candidate",
            "decision_owner": "fine-tuning-owner",
            "rationale": "Full base evaluation was reviewed.",
        }
        evaluation = root / "evaluation-summary.json"
        evaluation.write_text(json.dumps(summary), encoding="utf-8")
        approval = root / "promotion-approval.json"
        approval.write_text(json.dumps(approval_value), encoding="utf-8")
        manifest = {
            "schema_version": 2,
            "release_id": "release-base-v2",
            "release_mode": "base",
            "capability": MODULE.CAPABILITY,
            "served_model_name": MODULE.SERVED_MODEL_NAME,
            "created_at": "2026-09-02T00:00:00+00:00",
            "base_model": {"id": "Qwen/Qwen3-4B", "revision": "a" * 40},
            "adapter": None,
            "training": None,
            "evaluation": {
                "task": "full",
                "dataset_release": "f2-2.0.0",
                "dataset_sha256": "e" * 64,
                "source_summary_sha256": "f" * 64,
                "summary_path": "evaluation-summary.json",
                "summary_sha256": MODULE.file_sha256(evaluation),
                "promotion_status": "approved",
                "selected_model": "base-candidate",
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
        return bundle

    def make_v2_lora_bundle(
        self, root: Path, *, include_secret_file: bool = False
    ) -> Path:
        self.make_bundle(root)
        adapter = root / "adapter"
        if include_secret_file:
            (adapter / ".env").write_text("HF_TOKEN=private", encoding="utf-8")
        files = sorted(adapter.iterdir())
        adapter_sha = MODULE._tree_sha256(
            [(path.name, path.read_bytes()) for path in files]
        )
        summary_value = {
            "run_id": "evaluation-full-002",
            "release_mode": "lora",
            "dataset_release": "f2-2.0.0",
            "dataset_sha256": "e" * 64,
            "task": "full",
            "models": [
                {
                    "label": "candidate",
                    "model_id": "Qwen/Qwen3-4B",
                    "resolved_model_revision": "a" * 40,
                    "adapter_sha256": adapter_sha,
                }
            ],
        }
        approval_value = {
            "schema_version": 2,
            "release_mode": "lora",
            "status": "approved",
            "evaluation_run_id": "evaluation-full-002",
            "selected_model": "candidate",
            "decision_owner": "fine-tuning-owner",
            "rationale": "Full LoRA evaluation was reviewed.",
        }
        evaluation = root / "evaluation-summary.json"
        evaluation.write_text(json.dumps(summary_value), encoding="utf-8")
        approval = root / "promotion-approval.json"
        approval.write_text(json.dumps(approval_value), encoding="utf-8")
        manifest = json.loads((root / "release.json").read_text(encoding="utf-8"))
        manifest.update(
            {
                "schema_version": 2,
                "release_id": "release-lora-v2",
                "release_mode": "lora",
                "adapter": {
                    "format": "peft-lora",
                    "path": "adapter",
                    "sha256": adapter_sha,
                    "size_bytes": sum(path.stat().st_size for path in files),
                    "file_count": len(files),
                },
                "training": {
                    "code_revision": "b" * 40,
                    "train_sha256": "c" * 64,
                    "validation_sha256": "d" * 64,
                },
                "evaluation": {
                    "task": "full",
                    "dataset_release": "f2-2.0.0",
                    "dataset_sha256": "e" * 64,
                    "source_summary_sha256": "f" * 64,
                    "summary_path": "evaluation-summary.json",
                    "summary_sha256": MODULE.file_sha256(evaluation),
                    "promotion_status": "approved",
                    "selected_model": "candidate",
                    "approval_path": "promotion-approval.json",
                    "approval_sha256": MODULE.file_sha256(approval),
                },
            }
        )
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

    def make_dev_lora_bundle(
        self, root: Path, *, include_promotion_files: bool = False
    ) -> Path:
        adapter = root / "adapter"
        adapter.mkdir()
        (adapter / "adapter_config.json").write_text("{}\n", encoding="utf-8")
        (adapter / "adapter_model.safetensors").write_bytes(b"weights")
        files = sorted(adapter.iterdir())
        manifest = {
            "schema_version": 2,
            "release_id": "dev-release-lora-v2",
            "release_stage": "dev",
            "release_mode": "lora",
            "capability": MODULE.CAPABILITY,
            "served_model_name": MODULE.SERVED_MODEL_NAME,
            "created_at": "2026-09-03T00:00:00+00:00",
            "base_model": {"id": "Qwen/Qwen3-4B", "revision": "a" * 40},
            "adapter": {
                "format": "peft-lora",
                "path": "adapter",
                "sha256": MODULE._tree_sha256(
                    [(path.name, path.read_bytes()) for path in files]
                ),
                "size_bytes": sum(path.stat().st_size for path in files),
                "file_count": len(files),
            },
            "training": {
                "code_revision": "b" * 40,
                "train_sha256": "c" * 64,
                "validation_sha256": "d" * 64,
            },
            "evaluation": {
                "status": "not-evaluated",
                "dataset_release": "f2-dev",
            },
        }
        release = root / "release.json"
        release.write_text(json.dumps(manifest), encoding="utf-8")
        bundle = root / "bundle.tar.gz"
        with tarfile.open(bundle, "w:gz") as archive:
            archive.add(release, arcname="release.json")
            for path in files:
                archive.add(path, arcname=f"adapter/{path.name}")
            if include_promotion_files:
                evaluation = root / "evaluation-summary.json"
                evaluation.write_text("{}", encoding="utf-8")
                archive.add(evaluation, arcname="evaluation-summary.json")
        return bundle

    def test_valid_bundle_is_inspected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bundle = self.make_bundle(Path(directory))
            inspected = MODULE.inspect_bundle(bundle)
        self.assertEqual(inspected.release_id, "release-v1")
        self.assertEqual(inspected.manifest["served_model_name"], "sllm")

    def test_valid_v2_base_bundle_has_no_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            inspected = MODULE.inspect_bundle(self.make_base_bundle(Path(directory)))
        self.assertEqual(inspected.release_mode, "base")
        self.assertIsNone(inspected.manifest["adapter"])

    def test_valid_v2_lora_bundle_is_inspected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            inspected = MODULE.inspect_bundle(self.make_v2_lora_bundle(Path(directory)))
        self.assertEqual(inspected.release_mode, "lora")

    def test_valid_dev_lora_bundle_is_explicitly_marked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            inspected = MODULE.inspect_bundle(
                self.make_dev_lora_bundle(Path(directory))
            )
        self.assertEqual(inspected.release_stage, "dev")
        self.assertEqual(inspected.manifest["evaluation"]["status"], "not-evaluated")

    def test_dev_bundle_rejects_promotion_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bundle = self.make_dev_lora_bundle(
                Path(directory), include_promotion_files=True
            )
            with self.assertRaisesRegex(MODULE.ToolError, "must not contain"):
                MODULE.inspect_bundle(bundle)

    def test_dev_bundle_requires_dev_release_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = self.make_dev_lora_bundle(root)
            manifest = json.loads((root / "release.json").read_text(encoding="utf-8"))
            manifest["release_id"] = "release-lora-v2"
            (root / "release.json").write_text(json.dumps(manifest), encoding="utf-8")
            with tarfile.open(bundle, "w:gz") as archive:
                archive.add(root / "release.json", arcname="release.json")
                for path in sorted((root / "adapter").iterdir()):
                    archive.add(path, arcname=f"adapter/{path.name}")
            with self.assertRaisesRegex(MODULE.ToolError, "must start with dev-"):
                MODULE.inspect_bundle(bundle)

    def test_v2_lora_bundle_rejects_secret_candidate_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bundle = self.make_v2_lora_bundle(Path(directory), include_secret_file=True)
            with self.assertRaisesRegex(MODULE.ToolError, "unapproved adapter file"):
                MODULE.inspect_bundle(bundle)

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
                archive.add(
                    root / "evaluation-summary.json", arcname="evaluation-summary.json"
                )
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


class MemoryAws(MODULE.AwsCli):
    def __init__(self) -> None:
        self.objects: dict[str, dict[str, object]] = {}

    def object_head(self, *, bucket: str, key: str):
        del bucket
        return self.objects.get(key)

    def put_immutable(self, *, bucket, key, body, content_type, metadata):
        del bucket, body, content_type
        self.objects[key] = {"Metadata": dict(metadata)}


class AwsCliTests(unittest.TestCase):
    def test_presign_does_not_embed_credentials_in_arguments(self) -> None:
        executor = FakeExecutor()
        client = MODULE.AwsCli(executor, profile="team", region="ap-northeast-2")
        result = client.presign(
            bucket="private", key="releases/sllm/r/bundle.tar.gz", expires=3600
        )
        self.assertEqual(result, "https://signed.example")
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", " ".join(executor.calls[0]))

    def test_immutable_object_resumes_only_for_identical_metadata(self) -> None:
        client = MemoryAws()
        with tempfile.NamedTemporaryFile() as file:
            body = Path(file.name)
            metadata = {"sha256": "a" * 64, "bundle-sha256": "b" * 64}
            first = client.ensure_immutable(
                bucket="private",
                key="release.json",
                body=body,
                content_type="application/json",
                metadata=metadata,
            )
            second = client.ensure_immutable(
                bucket="private",
                key="release.json",
                body=body,
                content_type="application/json",
                metadata=metadata,
            )
            with self.assertRaisesRegex(MODULE.ToolError, "already differs"):
                client.ensure_immutable(
                    bucket="private",
                    key="release.json",
                    body=body,
                    content_type="application/json",
                    metadata=metadata | {"sha256": "c" * 64},
                )
        self.assertEqual(first, "created")
        self.assertEqual(second, "retained-identical")

    def test_publish_resumes_after_bundle_only_partial_publish(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            inspected = MODULE.inspect_bundle(
                BundleTests().make_bundle(Path(directory))
            )
            manifest_sha = MODULE.hashlib.sha256(inspected.manifest_bytes).hexdigest()
            client = MemoryAws()
            prefix = MODULE.release_prefix(inspected.release_id)
            client.objects[f"{prefix}/bundle.tar.gz"] = {
                "Metadata": {
                    "sha256": inspected.sha256,
                }
            }
            MODULE.publish(inspected, bucket="private", client=client, apply=True)
        self.assertIn(f"{prefix}/release.json", client.objects)
        self.assertEqual(
            client.objects[f"{prefix}/release.json"]["Metadata"],
            {"sha256": manifest_sha},
        )

    def test_v2_publish_cross_binds_bundle_and_manifest_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            inspected = MODULE.inspect_bundle(
                BundleTests().make_base_bundle(Path(directory))
            )
            client = MemoryAws()
            MODULE.publish(inspected, bucket="private", client=client, apply=True)
            prefix = MODULE.release_prefix(inspected.release_id)
            manifest_sha = MODULE.hashlib.sha256(inspected.manifest_bytes).hexdigest()
        self.assertEqual(
            client.objects[f"{prefix}/bundle.tar.gz"]["Metadata"],
            {
                "sha256": inspected.sha256,
                "release-manifest-sha256": manifest_sha,
            },
        )
        self.assertEqual(
            client.objects[f"{prefix}/release.json"]["Metadata"],
            {"sha256": manifest_sha, "bundle-sha256": inspected.sha256},
        )


if __name__ == "__main__":
    unittest.main()
