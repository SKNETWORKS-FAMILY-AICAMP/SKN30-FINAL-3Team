from __future__ import annotations

import json
from pathlib import Path

import pytest
from training.f2_sLLM.prepare_sft_dataset import convert_file, convert_sample


def sample(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "scenario_id": "f2-v03-000001",
        "transcript": "아파트를 매도하려고 전화드렸습니다.",
        "label": "매도의뢰",
        "source_group_id": "f2-v03-group-000001",
        "split": "train",
    }
    value.update(overrides)
    return value


def test_convert_sample_creates_chat_prompt_and_json_completion() -> None:
    converted = convert_sample(sample(), "test")

    assert converted["id"] == "f2-v03-000001"
    assert converted["prompt"][1]["content"].endswith("아파트를 매도하려고 전화드렸습니다.")
    assert converted["completion"] == [
        {"role": "assistant", "content": '{"consultation_type":"매도의뢰"}'}
    ]


def test_convert_sample_rejects_unknown_label() -> None:
    with pytest.raises(ValueError, match="알 수 없는 label"):
        convert_sample(sample(label="기타"), "test")


def test_convert_sample_rejects_test_split() -> None:
    with pytest.raises(ValueError, match="test 데이터"):
        convert_sample(sample(split="test"), "test")


def test_convert_file_rejects_duplicate_ids(tmp_path: Path) -> None:
    input_path = tmp_path / "train.jsonl"
    output_path = tmp_path / "sft-train.jsonl"
    lines = [json.dumps(sample(), ensure_ascii=False), json.dumps(sample(), ensure_ascii=False)]
    input_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="중복 id"):
        convert_file(input_path, output_path)
