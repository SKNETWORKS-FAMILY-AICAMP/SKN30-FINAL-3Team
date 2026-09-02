import json
import tarfile
from pathlib import Path

import pytest
from training.f2_sLLM.package_release import ReleaseError, package_release


def write_inputs(
    root: Path,
    *,
    task: str = "full",
    approval_status: str = "approved",
    selected_model: str = "candidate",
    approval_run_id: str = "evaluation-full-001",
) -> tuple[Path, Path, Path]:
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
                "run_id": "evaluation-full-001",
                "task": task,
                "dataset": "/private/test.jsonl",
                "adapter_path": "/private/adapter",
                "models": [{"label": "candidate", "metrics": {"accuracy": 1.0}}],
            }
        ),
        encoding="utf-8",
    )
    approval = root / "promotion-approval.json"
    approval.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": approval_status,
                "evaluation_run_id": approval_run_id,
                "selected_model": selected_model,
                "decision_owner": "fine-tuning-owner",
                "rationale": "Full evaluation metrics were reviewed for shared dev promotion.",
            }
        ),
        encoding="utf-8",
    )
    return training, evaluation, approval


def test_package_contains_only_release_contract_and_adapter(tmp_path: Path) -> None:
    training, evaluation, approval = write_inputs(tmp_path)
    output = tmp_path / "release.tar.gz"

    result = package_release(
        release_id="consultation-v1",
        training_output=training,
        evaluation_summary=evaluation,
        promotion_approval=approval,
        dataset_release="f2-1.0.0",
        output=output,
    )

    assert result["release_id"] == "consultation-v1"
    with tarfile.open(output, "r:gz") as archive:
        assert set(archive.getnames()) == {
            "release.json",
            "evaluation-summary.json",
            "promotion-approval.json",
            "adapter/adapter_config.json",
            "adapter/adapter_model.safetensors",
        }
        manifest_file = archive.extractfile("release.json")
        evaluation_file = archive.extractfile("evaluation-summary.json")
        approval_file = archive.extractfile("promotion-approval.json")
        assert manifest_file is not None
        assert evaluation_file is not None
        assert approval_file is not None
        manifest = json.load(manifest_file)
        evaluation = json.load(evaluation_file)
        approval = json.load(approval_file)
    assert manifest["capability"] == "f2-consultation-analysis"
    assert manifest["served_model_name"] == "sllm"
    assert manifest["base_model"]["revision"] == "b" * 40
    assert manifest["evaluation"]["promotion_status"] == "approved"
    assert manifest["evaluation"]["selected_model"] == "candidate"
    assert approval["decision_owner"] == "fine-tuning-owner"
    assert "/private" not in json.dumps(manifest)
    assert "/private" not in json.dumps(evaluation)


def test_classification_only_evaluation_cannot_be_promoted(tmp_path: Path) -> None:
    training, evaluation, approval = write_inputs(tmp_path, task="classification")
    with pytest.raises(ReleaseError, match="full-task"):
        package_release(
            release_id="classification-v1",
            training_output=training,
            evaluation_summary=evaluation,
            promotion_approval=approval,
            dataset_release="f2-1.0.0",
            output=tmp_path / "release.tar.gz",
        )


@pytest.mark.parametrize(
    ("approval_status", "selected_model", "approval_run_id", "message"),
    [
        ("rejected", "candidate", "evaluation-full-001", "status must be approved"),
        ("approved", "unreviewed", "evaluation-full-001", "must exist"),
        ("approved", "candidate", "another-evaluation", "must match"),
    ],
)
def test_unapproved_or_unbound_evaluation_cannot_be_promoted(
    tmp_path: Path,
    approval_status: str,
    selected_model: str,
    approval_run_id: str,
    message: str,
) -> None:
    training, evaluation, approval = write_inputs(
        tmp_path,
        approval_status=approval_status,
        selected_model=selected_model,
        approval_run_id=approval_run_id,
    )
    with pytest.raises(ReleaseError, match=message):
        package_release(
            release_id="consultation-v1",
            training_output=training,
            evaluation_summary=evaluation,
            promotion_approval=approval,
            dataset_release="f2-1.0.0",
            output=tmp_path / "release.tar.gz",
        )


def test_symlink_is_rejected(tmp_path: Path) -> None:
    training, evaluation, approval = write_inputs(tmp_path)
    (training / "adapter" / "linked").symlink_to(evaluation)
    with pytest.raises(ReleaseError, match="symlink"):
        package_release(
            release_id="consultation-v1",
            training_output=training,
            evaluation_summary=evaluation,
            promotion_approval=approval,
            dataset_release="f2-1.0.0",
            output=tmp_path / "release.tar.gz",
        )
