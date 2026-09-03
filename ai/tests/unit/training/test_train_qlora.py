from __future__ import annotations

import json
from pathlib import Path

import pytest
from training.f2_sLLM.train_qlora import (
    load_config,
    validate_sft_file,
    validate_token_lengths,
)


def write_sft(
    path: Path,
    *,
    split: str = "train",
    group_id: str = "group-1",
    task: str = "full",
) -> None:
    sample = {
        "id": "sample-1",
        "prompt": [{"role": "user", "content": "상담 내용"}],
        "completion": [{"role": "assistant", "content": "{}"}],
        "source_group_id": group_id,
        "split": split,
        "task": task,
    }
    path.write_text(json.dumps(sample, ensure_ascii=False) + "\n", encoding="utf-8")


def test_default_config_has_required_sections() -> None:
    config_path = (
        Path(__file__).parents[3] / "training" / "f2_sLLM" / "configs" / "qwen3-4b-qlora.yaml"
    )

    config = load_config(config_path)

    assert config["model"]["id"] == "Qwen/Qwen3-4B"
    assert config["quantization"]["load_in_4bit"] is True


def test_full_output_config_uses_longer_context() -> None:
    config_path = (
        Path(__file__).parents[3] / "training" / "f2_sLLM" / "configs" / "qwen3-4b-qlora-full.yaml"
    )

    config = load_config(config_path)

    assert config["model"]["max_length"] == 2048
    assert config["training"]["per_device_train_batch_size"] == 2


def test_validate_sft_file_rejects_test_as_training_input(tmp_path: Path) -> None:
    path = tmp_path / "test.jsonl"
    write_sft(path, split="test")

    with pytest.raises(ValueError, match="split은 'train'"):
        validate_sft_file(path, "train")


def test_validate_sft_file_returns_full_task(tmp_path: Path) -> None:
    path = tmp_path / "train.jsonl"
    write_sft(path)

    _, _, tasks = validate_sft_file(path, "train")

    assert tasks == {"full"}


class WordTokenizer:
    def __call__(self, text: str, *, add_special_tokens: bool) -> dict[str, list[int]]:
        assert add_special_tokens is False
        return {"input_ids": list(range(len(text.split())))}


def test_validate_token_lengths_rejects_truncated_completion() -> None:
    data = {
        "train": [{"id": "long", "prompt": "one two ", "completion": "three four"}],
        "validation": [{"id": "ok", "prompt": "one ", "completion": "two"}],
    }

    with pytest.raises(ValueError, match="model.max_length=3"):
        validate_token_lengths(data, WordTokenizer(), 3)


def test_validate_token_lengths_reports_each_split() -> None:
    data = {
        "train": [{"id": "train", "prompt": "one ", "completion": "two"}],
        "validation": [{"id": "validation", "prompt": "one ", "completion": "two three"}],
    }

    stats = validate_token_lengths(data, WordTokenizer(), 3)

    assert stats["train"]["maximum"] == 2
    assert stats["validation"]["maximum"] == 3
