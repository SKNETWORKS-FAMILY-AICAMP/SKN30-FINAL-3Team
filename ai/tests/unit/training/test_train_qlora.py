from __future__ import annotations

import json
from pathlib import Path

import pytest
from training.f2_sLLM.train_qlora import load_config, validate_sft_file


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
