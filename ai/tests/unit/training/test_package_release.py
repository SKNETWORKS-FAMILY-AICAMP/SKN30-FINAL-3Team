import json
import tarfile
from pathlib import Path

import pytest
from training.f2_sLLM.package_release import ReleaseError, package_release


def write_inputs(root: Path, *, task: str = "full") -> tuple[Path, Path]:
    training = root / "training"
    adapter = training / "adapter"
    adapter.mkdir(parents=True)
    (adapter / "adapter_config.json").write_text("{}\n", encoding="utf-8")
    (adapter / "adapter_model.safetensors").write_bytes(b"safe-adapter")
    metadata = {
        "git_revision": "a" * 40,
        "resolved_model_revision": "b" * 40,
        "config": {"model": {"id": "Qwen/Qwen3-4B", "revision": "main"}},
        "data": {
            "train": {"path": "/private/train.jsonl", "sha256": "c" * 64},
            "validation": {"path": "/private/validation.jsonl", "sha256": "d" * 64},
        },
        "adapter_path": "/private/adapter",
    }
    (training / "run_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    evaluation = root / "summary.json"
    evaluation.write_text(
        json.dumps(
            {
                "task": task,
                "dataset": "/private/test.jsonl",
                "adapter_path": "/private/adapter",
                "models": [{"label": "candidate", "metrics": {"accuracy": 1.0}}],
            }
        ),
        encoding="utf-8",
    )
    return training, evaluation


def test_package_contains_only_release_contract_and_adapter(tmp_path: Path) -> None:
    training, evaluation = write_inputs(tmp_path)
    output = tmp_path / "release.tar.gz"

    result = package_release(
        release_id="consultation-v1",
        training_output=training,
        evaluation_summary=evaluation,
        dataset_release="f2-1.0.0",
        output=output,
    )

    assert result["release_id"] == "consultation-v1"
    with tarfile.open(output, "r:gz") as archive:
        assert set(archive.getnames()) == {
            "release.json",
            "evaluation-summary.json",
            "adapter/adapter_config.json",
            "adapter/adapter_model.safetensors",
        }
        manifest_file = archive.extractfile("release.json")
        evaluation_file = archive.extractfile("evaluation-summary.json")
        assert manifest_file is not None
        assert evaluation_file is not None
        manifest = json.load(manifest_file)
        evaluation = json.load(evaluation_file)
    assert manifest["capability"] == "f2-consultation-analysis"
    assert manifest["served_model_name"] == "sllm"
    assert manifest["base_model"]["revision"] == "b" * 40
    assert "/private" not in json.dumps(manifest)
    assert "/private" not in json.dumps(evaluation)


def test_classification_only_evaluation_cannot_be_promoted(tmp_path: Path) -> None:
    training, evaluation = write_inputs(tmp_path, task="classification")
    with pytest.raises(ReleaseError, match="full-task"):
        package_release(
            release_id="classification-v1",
            training_output=training,
            evaluation_summary=evaluation,
            dataset_release="f2-1.0.0",
            output=tmp_path / "release.tar.gz",
        )


def test_symlink_is_rejected(tmp_path: Path) -> None:
    training, evaluation = write_inputs(tmp_path)
    (training / "adapter" / "linked").symlink_to(evaluation)
    with pytest.raises(ReleaseError, match="symlink"):
        package_release(
            release_id="consultation-v1",
            training_output=training,
            evaluation_summary=evaluation,
            dataset_release="f2-1.0.0",
            output=tmp_path / "release.tar.gz",
        )
