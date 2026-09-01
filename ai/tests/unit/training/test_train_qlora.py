from __future__ import annotations

import json
from pathlib import Path

import pytest
from training.f2_sLLM.train_qlora import (
    load_config,
    sha256_directory,
    validate_init_adapter,
    validate_sft_file,
)


def write_sft(path: Path, *, split: str = "train", group_id: str = "group-1") -> None:
    sample = {
        "id": "sample-1",
        "prompt": [{"role": "user", "content": "상담 내용"}],
        "completion": [{"role": "assistant", "content": "{}"}],
        "source_group_id": group_id,
        "split": split,
    }
    path.write_text(json.dumps(sample, ensure_ascii=False) + "\n", encoding="utf-8")


def test_default_config_has_required_sections() -> None:
    config_path = (
        Path(__file__).parents[3] / "training" / "f2_sLLM" / "configs" / "qwen3-4b-qlora.yaml"
    )

    config = load_config(config_path)

    assert config["model"]["id"] == "Qwen/Qwen3-4B"
    assert config["quantization"]["load_in_4bit"] is True


def test_validate_sft_file_rejects_test_as_training_input(tmp_path: Path) -> None:
    path = tmp_path / "test.jsonl"
    write_sft(path, split="test")

    with pytest.raises(ValueError, match="split은 'train'"):
        validate_sft_file(path, "train")


def test_validate_init_adapter_accepts_matching_qlora_config(tmp_path: Path) -> None:
    config_path = (
        Path(__file__).parents[3] / "training" / "f2_sLLM" / "configs" / "qwen3-4b-qlora.yaml"
    )
    config = load_config(config_path)
    revision = "a" * 40
    config["model"]["revision"] = revision
    adapter_dir = tmp_path / "adapter"
    adapter_dir.mkdir()
    adapter_config = {
        "base_model_name_or_path": "Qwen/Qwen3-4B",
        "revision": None,
        "r": 16,
        "lora_alpha": 32,
        "lora_dropout": 0.05,
        "target_modules": config["lora"]["target_modules"],
    }
    (adapter_dir / "adapter_config.json").write_text(json.dumps(adapter_config), encoding="utf-8")
    (adapter_dir / "adapter_model.safetensors").write_bytes(b"adapter")
    metadata_path = tmp_path / "run_metadata.json"
    metadata_path.write_text(json.dumps({"resolved_model_revision": revision}), encoding="utf-8")

    validated_config, validated_revision, validated_metadata = validate_init_adapter(
        adapter_dir, config
    )
    assert validated_config == adapter_config
    assert validated_revision == revision
    assert validated_metadata == metadata_path
    assert len(sha256_directory(adapter_dir)) == 64


def test_validate_init_adapter_rejects_different_base_model(tmp_path: Path) -> None:
    config_path = (
        Path(__file__).parents[3] / "training" / "f2_sLLM" / "configs" / "qwen3-4b-qlora.yaml"
    )
    config = load_config(config_path)
    adapter_dir = tmp_path / "adapter"
    adapter_dir.mkdir()
    (adapter_dir / "adapter_config.json").write_text(
        json.dumps({"base_model_name_or_path": "different/model"}), encoding="utf-8"
    )
    (adapter_dir / "adapter_model.safetensors").write_bytes(b"adapter")

    with pytest.raises(ValueError, match="기반 모델이 학습 설정과 다릅니다"):
        validate_init_adapter(adapter_dir, config)
