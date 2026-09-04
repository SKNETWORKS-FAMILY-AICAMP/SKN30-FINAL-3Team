from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

RUNPOD_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = RUNPOD_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


def load(name: str):
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"f2_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bootstrap = load("artifact_bootstrap")
supervisor = load("supervisor")
SLLM_KEY = "l" * 43
STT_KEY = "s" * 43


def release(adapter_path: str = "/opt/f2-models/release-v1/adapter"):
    return bootstrap.Release(
        release_id="release-v1",
        release_mode="lora",
        base_model_id="Qwen/Qwen3-4B",
        base_model_revision="a" * 40,
        adapter_path=adapter_path,
    )


def base_release():
    return bootstrap.Release(
        release_id="release-base-v2",
        release_mode="base",
        base_model_id="Qwen/Qwen3-4B",
        base_model_revision="a" * 40,
        adapter_path=None,
    )


def valid_environment() -> dict[str, str]:
    return {
        "AI_VLLM_SLLM_API_KEY": SLLM_KEY,
        "AI_VLLM_STT_API_KEY": STT_KEY,
        "F2_STT_MODEL_ID": "openai/whisper-large-v3-turbo",
        "F2_STT_MODEL_REVISION": "b" * 40,
        "F2_SLLM_MAX_MODEL_LEN": "4096",
        "F2_SLLM_GPU_MEMORY_UTILIZATION": "0.65",
        "F2_STT_GPU_MEMORY_UTILIZATION": "0.20",
    }


class SupervisorTests(unittest.TestCase):
    def test_release_owns_sllm_model_and_template_owns_stt(self) -> None:
        config = supervisor.load_config(release(), valid_environment())
        self.assertEqual(config.sllm_model_id, "Qwen/Qwen3-4B")
        self.assertEqual(config.sllm_model_revision, "a" * 40)
        self.assertEqual(config.stt_model_id, "openai/whisper-large-v3-turbo")

    def test_keys_are_strong_and_distinct(self) -> None:
        for override in (
            {"AI_VLLM_SLLM_API_KEY": "short"},
            {"AI_VLLM_STT_API_KEY": SLLM_KEY},
        ):
            with (
                self.subTest(override=override),
                self.assertRaises(supervisor.ConfigurationError),
            ):
                supervisor.load_config(release(), valid_environment() | override)

    def test_gpu_fractions_are_bounded(self) -> None:
        with self.assertRaises(supervisor.ConfigurationError):
            supervisor.load_config(
                release(),
                valid_environment()
                | {
                    "F2_SLLM_GPU_MEMORY_UTILIZATION": "0.8",
                    "F2_STT_GPU_MEMORY_UTILIZATION": "0.2",
                },
            )

    def test_commands_use_capability_names_and_adapter(self) -> None:
        config = supervisor.load_config(release(), valid_environment())
        commands = supervisor.build_commands(config, "vllm")
        self.assertEqual(set(commands), {"sllm", "stt"})
        sllm = commands["sllm"]
        stt = commands["stt"]
        self.assertEqual(sllm[sllm.index("--served-model-name") + 1], "sllm-base")
        self.assertEqual(stt[stt.index("--served-model-name") + 1], "stt")
        self.assertIn("sllm=/opt/f2-models/release-v1/adapter", sllm)
        self.assertNotIn("--enable-lora", stt)
        self.assertNotIn(SLLM_KEY, sllm + stt)

    def test_base_command_uses_sllm_name_without_lora_options(self) -> None:
        config = supervisor.load_config(base_release(), valid_environment())
        sllm = supervisor.build_commands(config, "vllm")["sllm"]
        self.assertEqual(sllm[sllm.index("--served-model-name") + 1], "sllm")
        self.assertNotIn("--enable-lora", sllm)
        self.assertNotIn("--lora-modules", sllm)

    def test_control_plane_values_are_removed_from_children(self) -> None:
        environment = valid_environment() | {
            "F2_SLLM_BUNDLE_URL": "https://signed.example/private",
            "AWS_SECRET_ACCESS_KEY": "private",
            "HF_TOKEN": "huggingface",
        }
        model = supervisor._model_environment(environment, api_key=SLLM_KEY)
        proxy = supervisor._proxy_environment(environment, SLLM_KEY)
        self.assertNotIn("F2_SLLM_BUNDLE_URL", model)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", model)
        self.assertNotIn("HF_TOKEN", model)
        self.assertNotIn("HF_TOKEN", proxy)


class BootstrapTests(unittest.TestCase):
    def _release_manifest(self, destination: Path) -> dict[str, object]:
        adapter = destination / "adapter"
        adapter.mkdir()
        (adapter / "adapter_config.json").write_text("{}", encoding="utf-8")
        (adapter / "adapter_model.safetensors").write_bytes(b"adapter")
        adapter_files = sorted(path for path in adapter.rglob("*") if path.is_file())
        adapter_digest = hashlib.sha256()
        for path in adapter_files:
            relative = path.relative_to(adapter).as_posix().encode()
            adapter_digest.update(len(relative).to_bytes(4, "big"))
            adapter_digest.update(relative)
            adapter_digest.update(hashlib.sha256(path.read_bytes()).digest())
        summary = {
            "run_id": "evaluation-full-001",
            "task": "full",
            "models": [{"label": "candidate"}],
        }
        approval = {
            "schema_version": 1,
            "status": "approved",
            "evaluation_run_id": "evaluation-full-001",
            "selected_model": "candidate",
            "decision_owner": "fine-tuning-owner",
            "rationale": "Full evaluation was reviewed for shared dev promotion.",
        }
        summary_bytes = (
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
        ).encode()
        approval_bytes = (
            json.dumps(approval, ensure_ascii=False, indent=2) + "\n"
        ).encode()
        (destination / "evaluation-summary.json").write_bytes(summary_bytes)
        (destination / "promotion-approval.json").write_bytes(approval_bytes)
        return {
            "schema_version": 1,
            "release_id": "release-v1",
            "capability": "f2-consultation-analysis",
            "served_model_name": "sllm",
            "base_model": {"id": "Qwen/Qwen3-4B", "revision": "a" * 40},
            "adapter": {
                "format": "peft-lora",
                "path": "adapter",
                "sha256": adapter_digest.hexdigest(),
                "size_bytes": sum(path.stat().st_size for path in adapter_files),
                "file_count": len(adapter_files),
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
                "summary_sha256": hashlib.sha256(summary_bytes).hexdigest(),
                "promotion_status": "approved",
                "selected_model": "candidate",
                "approval_path": "promotion-approval.json",
                "approval_sha256": hashlib.sha256(approval_bytes).hexdigest(),
            },
        }

    def test_manifest_requires_consultation_capability_and_sllm_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            manifest = self._release_manifest(destination)
            result = bootstrap._validate(manifest, "release-v1", destination)
            self.assertEqual(result.base_model_id, "Qwen/Qwen3-4B")
            with self.assertRaises(bootstrap.BootstrapError):
                bootstrap._validate(
                    manifest | {"served_model_name": "qwen"}, "release-v1", destination
                )

    def test_v2_base_manifest_has_no_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
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
            approval = {
                "schema_version": 2,
                "release_mode": "base",
                "status": "approved",
                "evaluation_run_id": "evaluation-full-002",
                "selected_model": "base-candidate",
                "decision_owner": "fine-tuning-owner",
                "rationale": "Full base evaluation was reviewed.",
            }
            summary_bytes = (json.dumps(summary) + "\n").encode()
            approval_bytes = (json.dumps(approval) + "\n").encode()
            (destination / "evaluation-summary.json").write_bytes(summary_bytes)
            (destination / "promotion-approval.json").write_bytes(approval_bytes)
            manifest = {
                "schema_version": 2,
                "release_id": "release-base-v2",
                "release_mode": "base",
                "capability": "f2-consultation-analysis",
                "served_model_name": "sllm",
                "base_model": {"id": "Qwen/Qwen3-4B", "revision": "a" * 40},
                "adapter": None,
                "training": None,
                "evaluation": {
                    "task": "full",
                    "dataset_release": "f2-2.0.0",
                    "dataset_sha256": "e" * 64,
                    "source_summary_sha256": "f" * 64,
                    "summary_path": "evaluation-summary.json",
                    "summary_sha256": hashlib.sha256(summary_bytes).hexdigest(),
                    "promotion_status": "approved",
                    "selected_model": "base-candidate",
                    "approval_path": "promotion-approval.json",
                    "approval_sha256": hashlib.sha256(approval_bytes).hexdigest(),
                },
            }
            result = bootstrap._validate(manifest, "release-base-v2", destination)
        self.assertEqual(result.release_mode, "base")
        self.assertIsNone(result.adapter_path)

    def test_dev_lora_manifest_is_accepted_without_evaluation_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            manifest = self._release_manifest(destination)
            (destination / "evaluation-summary.json").unlink()
            (destination / "promotion-approval.json").unlink()
            manifest.update(
                {
                    "schema_version": 2,
                    "release_id": "dev-release-v2",
                    "release_stage": "dev",
                    "release_mode": "lora",
                    "evaluation": {
                        "status": "not-evaluated",
                        "dataset_release": "f2-dev",
                    },
                }
            )
            training = manifest["training"]
            assert isinstance(training, dict)
            training.pop("dataset_release")
            result = bootstrap._validate(manifest, "dev-release-v2", destination)
        self.assertEqual(result.release_stage, "dev")
        self.assertEqual(result.release_mode, "lora")

    def test_dev_manifest_requires_dev_release_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            manifest = self._release_manifest(destination)
            manifest.update(
                {
                    "schema_version": 2,
                    "release_stage": "dev",
                    "release_mode": "lora",
                    "evaluation": {
                        "status": "not-evaluated",
                        "dataset_release": "f2-dev",
                    },
                }
            )
            training = manifest["training"]
            assert isinstance(training, dict)
            training.pop("dataset_release")
            with self.assertRaisesRegex(
                bootstrap.BootstrapError, "must start with dev-"
            ):
                bootstrap._validate(manifest, "release-v1", destination)

    def test_manifest_requires_matching_approved_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            manifest = self._release_manifest(destination)
            approval_path = destination / "promotion-approval.json"
            approval = json.loads(approval_path.read_text(encoding="utf-8"))
            approval["selected_model"] = "different-model"
            approval_bytes = (
                json.dumps(approval, ensure_ascii=False, indent=2) + "\n"
            ).encode()
            approval_path.write_bytes(approval_bytes)
            evaluation = manifest["evaluation"]
            assert isinstance(evaluation, dict)
            evaluation["approval_sha256"] = hashlib.sha256(approval_bytes).hexdigest()

            with self.assertRaisesRegex(
                bootstrap.BootstrapError, "promotion approval does not match"
            ):
                bootstrap._validate(manifest, "release-v1", destination)


class ImageAndTemplateTests(unittest.TestCase):
    def test_template_has_no_volume_ssh_or_sllm_model(self) -> None:
        template = json.loads(
            (RUNPOD_ROOT / "template.json").read_text(encoding="utf-8")
        )
        self.assertEqual(template["name"], "skn30-f2-serving-v2")
        self.assertEqual(set(template["ports"]), {"8001/http", "8002/http"})
        self.assertNotIn("volume_disk_gb", template)
        self.assertNotIn("F2_SLLM_MODEL_ID", template["env"])
        self.assertIn("F2_STT_MODEL_ID", template["env"])

    def test_dockerfile_is_locked_and_has_no_model_hardcode(self) -> None:
        dockerfile = (RUNPOD_ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("FROM runpod/pytorch@sha256:", dockerfile)
        self.assertIn("--no-deps", dockerfile)
        self.assertIn("--require-hashes", dockerfile)
        self.assertIn("import artifact_bootstrap", dockerfile)
        self.assertNotIn("vllm --version", dockerfile)
        self.assertNotIn("AutoConfig.from_pretrained", dockerfile)
        self.assertNotIn("PYTHONPATH", dockerfile)
        self.assertNotIn("tmux", dockerfile)

    def test_dependencies_stay_pinned(self) -> None:
        project = (RUNPOD_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('"vllm[audio]==0.11.0"', project)
        lock = (RUNPOD_ROOT / "requirements.lock").read_text(encoding="utf-8")
        self.assertRegex(lock, r"(?m)^vllm==0\.11\.0 \\")
        self.assertRegex(lock, r"(?m)^torch==2\.8\.0 \\")


if __name__ == "__main__":
    unittest.main()
