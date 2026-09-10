import hashlib
import json
import tarfile
from pathlib import Path

import pytest
from training.f2_sLLM.package_release import (
    ReleaseError,
    adapter_files,
    package_release,
    tree_sha256,
)


def load_json_member(archive: tarfile.TarFile, name: str):
    member = archive.extractfile(name)
    assert member is not None
    return json.load(member)


def write_inputs(
    root: Path,
    *,
    release_mode: str = "lora",
    task: str = "full",
    model_id: str = "Qwen/Qwen3-4B",
    model_revision: str = "b" * 40,
    dataset_release: str = "f2-1.0.0",
) -> tuple[Path, Path, Path]:
    training = root / "training"
    adapter = training / "adapter"
    adapter.mkdir(parents=True)
    (adapter / "adapter_config.json").write_text(
        json.dumps({"base_model_name_or_path": "Qwen/Qwen3-4B"}), encoding="utf-8"
    )
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
    adapter_hash = tree_sha256(adapter, adapter_files(adapter)) if release_mode == "lora" else None
    adapter_path = str(adapter.resolve()) if release_mode == "lora" else None
    evaluation = root / "summary.json"
    evaluation.write_text(
        json.dumps(
            {
                "run_id": "evaluation-full-001",
                "release_mode": release_mode,
                "dataset": "/private/test.jsonl",
                "dataset_release": dataset_release,
                "dataset_sha256": "e" * 64,
                "sample_count": 12,
                "task": task,
                "quantization": "4bit",
                "adapter_path": adapter_path,
                "adapter_sha256": adapter_hash,
                "generation": {"max_input_tokens": 1024, "enable_thinking": False},
                "models": [
                    {
                        "label": "candidate",
                        "model_id": model_id,
                        "resolved_model_revision": model_revision,
                        "adapter_path": adapter_path,
                        "adapter_sha256": adapter_hash,
                        "samples": 12,
                        "classification_accuracy": 1.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    approval = root / "promotion-approval.json"
    approval.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "status": "approved",
                "release_mode": release_mode,
                "evaluation_run_id": "evaluation-full-001",
                "selected_model": "candidate",
                "decision_owner": "fine-tuning-owner",
                "rationale": "Full evaluation metrics were reviewed for shared dev promotion.",
            }
        ),
        encoding="utf-8",
    )
    return training, evaluation, approval


def package(root: Path, *, release_mode: str = "lora", dataset_release: str = "f2-1.0.0"):
    training, evaluation, approval = write_inputs(
        root, release_mode=release_mode, dataset_release=dataset_release
    )
    output = root / "release.tar.gz"
    result = package_release(
        release_id="consultation-v2",
        release_mode=release_mode,
        training_output=training if release_mode == "lora" else None,
        evaluation_summary=evaluation,
        promotion_approval=approval,
        dataset_release=dataset_release,
        output=output,
    )
    return result, output


@pytest.mark.parametrize("release_mode", ["lora", "base"])
def test_package_contains_only_release_contract_for_mode(tmp_path: Path, release_mode: str) -> None:
    result, output = package(tmp_path, release_mode=release_mode)
    assert result["release_mode"] == release_mode
    with tarfile.open(output, "r:gz") as archive:
        names = set(archive.getnames())
        members = archive.getmembers()
        manifest = load_json_member(archive, "release.json")
        evaluation = load_json_member(archive, "evaluation-summary.json")
        approval = load_json_member(archive, "promotion-approval.json")
    expected = {"release.json", "evaluation-summary.json", "promotion-approval.json"}
    if release_mode == "lora":
        expected |= {"adapter/adapter_config.json", "adapter/adapter_model.safetensors"}
        assert manifest["adapter"]["format"] == "peft-lora"
        assert manifest["training"] is not None
    else:
        assert manifest["adapter"] is None
        assert manifest["training"] is None
    assert names == expected
    assert all(member.mtime == 0 and not member.uname and not member.gname for member in members)
    assert manifest["schema_version"] == 2
    assert manifest["release_mode"] == release_mode
    assert (
        manifest["evaluation"]["source_summary_sha256"]
        == hashlib.sha256((tmp_path / "summary.json").read_bytes()).hexdigest()
    )
    assert approval["release_mode"] == release_mode
    assert evaluation["dataset_release"] == "f2-1.0.0"
    assert "dataset" not in evaluation
    assert "adapter_path" not in json.dumps(evaluation)
    assert "/private" not in json.dumps(evaluation)


def test_dev_lora_package_omits_evaluation_and_approval(tmp_path: Path) -> None:
    training, _, _ = write_inputs(tmp_path)
    output = tmp_path / "dev-release.tar.gz"

    result = package_release(
        release_id="dev-consultation-v2",
        release_mode="lora",
        release_stage="dev",
        training_output=training,
        evaluation_summary=None,
        promotion_approval=None,
        dataset_release="f2-1.0.0",
        output=output,
    )

    with tarfile.open(output, "r:gz") as archive:
        names = set(archive.getnames())
        manifest = load_json_member(archive, "release.json")
    assert result["release_stage"] == "dev"
    assert names == {
        "release.json",
        "adapter/adapter_config.json",
        "adapter/adapter_model.safetensors",
    }
    assert manifest["release_stage"] == "dev"
    assert manifest["evaluation"] == {
        "status": "not-evaluated",
        "dataset_release": "f2-1.0.0",
    }


def test_dev_release_requires_dev_id_and_forbids_promotion_files(tmp_path: Path) -> None:
    training, evaluation, approval = write_inputs(tmp_path)
    with pytest.raises(ReleaseError, match="start with dev-"):
        package_release(
            release_id="consultation-v2",
            release_mode="lora",
            release_stage="dev",
            training_output=training,
            evaluation_summary=None,
            promotion_approval=None,
            dataset_release="f2-1.0.0",
            output=tmp_path / "bad-id.tar.gz",
        )
    with pytest.raises(ReleaseError, match="forbids evaluation"):
        package_release(
            release_id="dev-consultation-v2",
            release_mode="lora",
            release_stage="dev",
            training_output=training,
            evaluation_summary=evaluation,
            promotion_approval=approval,
            dataset_release="f2-1.0.0",
            output=tmp_path / "bad-promotion.tar.gz",
        )


def test_dev_base_requires_explicit_immutable_model(tmp_path: Path) -> None:
    output = tmp_path / "dev-base.tar.gz"
    package_release(
        release_id="dev-base-v2",
        release_mode="base",
        release_stage="dev",
        training_output=None,
        evaluation_summary=None,
        promotion_approval=None,
        dataset_release="f2-1.0.0",
        base_model_id="Qwen/Qwen3-4B",
        base_model_revision="b" * 40,
        output=output,
    )
    with tarfile.open(output, "r:gz") as archive:
        manifest = load_json_member(archive, "release.json")
    assert manifest["base_model"] == {
        "id": "Qwen/Qwen3-4B",
        "revision": "b" * 40,
    }
    assert manifest["adapter"] is None


def test_classification_only_evaluation_cannot_be_promoted(tmp_path: Path) -> None:
    training, evaluation, approval = write_inputs(tmp_path, task="classification")
    with pytest.raises(ReleaseError, match="full-task"):
        package_release(
            release_id="classification-v2",
            release_mode="lora",
            training_output=training,
            evaluation_summary=evaluation,
            promotion_approval=approval,
            dataset_release="f2-1.0.0",
            output=tmp_path / "release.tar.gz",
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("model_id", "Other/Model", "trained base model"),
        ("resolved_model_revision", "f" * 40, "trained base model"),
        ("adapter_sha256", "f" * 64, "adapter checksum"),
    ],
)
def test_lora_evaluation_must_match_packaged_artifact(
    tmp_path: Path, field: str, value: str, message: str
) -> None:
    training, evaluation_path, approval = write_inputs(tmp_path)
    evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    evaluation["models"][0][field] = value
    if field == "adapter_sha256":
        evaluation["adapter_sha256"] = value
    evaluation_path.write_text(json.dumps(evaluation), encoding="utf-8")
    with pytest.raises(ReleaseError, match=message):
        package_release(
            release_id="consultation-v2",
            release_mode="lora",
            training_output=training,
            evaluation_summary=evaluation_path,
            promotion_approval=approval,
            dataset_release="f2-1.0.0",
            output=tmp_path / "release.tar.gz",
        )


def test_dataset_release_must_match_evaluation(tmp_path: Path) -> None:
    training, evaluation, approval = write_inputs(tmp_path)
    with pytest.raises(ReleaseError, match="dataset-release"):
        package_release(
            release_id="consultation-v2",
            release_mode="lora",
            training_output=training,
            evaluation_summary=evaluation,
            promotion_approval=approval,
            dataset_release="different",
            output=tmp_path / "release.tar.gz",
        )


def test_mode_and_training_output_must_match(tmp_path: Path) -> None:
    training, evaluation, approval = write_inputs(tmp_path, release_mode="base")
    with pytest.raises(ReleaseError, match="forbids"):
        package_release(
            release_id="consultation-v2",
            release_mode="base",
            training_output=training,
            evaluation_summary=evaluation,
            promotion_approval=approval,
            dataset_release="f2-1.0.0",
            output=tmp_path / "release.tar.gz",
        )

    lora_root = tmp_path / "lora"
    _, evaluation, approval = write_inputs(lora_root, release_mode="lora")
    with pytest.raises(ReleaseError, match="requires"):
        package_release(
            release_id="consultation-v2",
            release_mode="lora",
            training_output=None,
            evaluation_summary=evaluation,
            promotion_approval=approval,
            dataset_release="f2-1.0.0",
            output=lora_root / "release.tar.gz",
        )


def test_adapter_config_must_match_trained_base_model(tmp_path: Path) -> None:
    training, evaluation, approval = write_inputs(tmp_path)
    (training / "adapter" / "adapter_config.json").write_text(
        json.dumps({"base_model_name_or_path": "Other/Model"}), encoding="utf-8"
    )
    evaluation_value = json.loads(evaluation.read_text(encoding="utf-8"))
    new_hash = tree_sha256(training / "adapter", adapter_files(training / "adapter"))
    evaluation_value["adapter_sha256"] = new_hash
    evaluation_value["models"][0]["adapter_sha256"] = new_hash
    evaluation.write_text(json.dumps(evaluation_value), encoding="utf-8")
    with pytest.raises(ReleaseError, match="adapter config base model"):
        package_release(
            release_id="consultation-v2",
            release_mode="lora",
            training_output=training,
            evaluation_summary=evaluation,
            promotion_approval=approval,
            dataset_release="f2-1.0.0",
            output=tmp_path / "release.tar.gz",
        )


def test_checkpoint_file_is_rejected(tmp_path: Path) -> None:
    training, evaluation, approval = write_inputs(tmp_path)
    checkpoint = training / "adapter" / "checkpoint-100"
    checkpoint.mkdir()
    (checkpoint / "optimizer.pt").write_bytes(b"not-for-release")
    with pytest.raises(ReleaseError, match="checkpoint"):
        package_release(
            release_id="consultation-v2",
            release_mode="lora",
            training_output=training,
            evaluation_summary=evaluation,
            promotion_approval=approval,
            dataset_release="f2-1.0.0",
            output=tmp_path / "release.tar.gz",
        )


def test_secret_candidate_adapter_file_is_rejected(tmp_path: Path) -> None:
    training, evaluation, approval = write_inputs(tmp_path)
    (training / "adapter" / ".env").write_text("HF_TOKEN=private", encoding="utf-8")
    with pytest.raises(ReleaseError, match="unapproved file"):
        package_release(
            release_id="consultation-v2",
            release_mode="lora",
            training_output=training,
            evaluation_summary=evaluation,
            promotion_approval=approval,
            dataset_release="f2-1.0.0",
            output=tmp_path / "release.tar.gz",
        )


def test_training_args_pickle_is_not_bundled(tmp_path: Path) -> None:
    training, evaluation, approval = write_inputs(tmp_path)
    (training / "adapter" / "training_args.bin").write_bytes(b"trainer pickle")
    output = tmp_path / "release.tar.gz"
    package_release(
        release_id="consultation-v2",
        release_mode="lora",
        training_output=training,
        evaluation_summary=evaluation,
        promotion_approval=approval,
        dataset_release="f2-1.0.0",
        output=output,
    )
    with tarfile.open(output, "r:gz") as archive:
        assert "adapter/training_args.bin" not in archive.getnames()


def test_secret_like_approval_rationale_is_rejected(tmp_path: Path) -> None:
    training, evaluation, approval_path = write_inputs(tmp_path)
    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    approval["rationale"] = "approved token=hf_private_value"
    approval_path.write_text(json.dumps(approval), encoding="utf-8")
    with pytest.raises(ReleaseError, match="secret-like"):
        package_release(
            release_id="consultation-v2",
            release_mode="lora",
            training_output=training,
            evaluation_summary=evaluation,
            promotion_approval=approval_path,
            dataset_release="f2-1.0.0",
            output=tmp_path / "release.tar.gz",
        )


def test_unapproved_public_summary_field_is_rejected(tmp_path: Path) -> None:
    training, evaluation_path, approval = write_inputs(tmp_path)
    evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    evaluation["models"][0]["raw_output"] = "private prediction"
    evaluation_path.write_text(json.dumps(evaluation), encoding="utf-8")
    with pytest.raises(ReleaseError, match="unsupported fields"):
        package_release(
            release_id="consultation-v2",
            release_mode="lora",
            training_output=training,
            evaluation_summary=evaluation_path,
            promotion_approval=approval,
            dataset_release="f2-1.0.0",
            output=tmp_path / "release.tar.gz",
        )


def test_symlink_is_rejected(tmp_path: Path) -> None:
    training, evaluation, approval = write_inputs(tmp_path)
    (training / "adapter" / "linked").symlink_to(evaluation)
    with pytest.raises(ReleaseError, match="symlink"):
        package_release(
            release_id="consultation-v2",
            release_mode="lora",
            training_output=training,
            evaluation_summary=evaluation,
            promotion_approval=approval,
            dataset_release="f2-1.0.0",
            output=tmp_path / "release.tar.gz",
        )
