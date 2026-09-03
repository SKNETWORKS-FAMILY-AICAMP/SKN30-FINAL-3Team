from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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


def full_sample(**overrides: object) -> dict[str, Any]:
    transcript = "제 이름은 가온고객이고 라온단지 101동 202호를 8억에 매도하려고 합니다."
    value: dict[str, Any] = {
        "sample_id": "f2-full-v05-sell-0001",
        "dataset_version": "0.5.0",
        "transcript": transcript,
        "label": "매도의뢰",
        "ledger_type": "매물장",
        "expected": {
            "consultation_type": "매도의뢰",
            "ledger_mismatch": False,
            "fields": {"임대인": "가온고객", "매매가": "8억"},
            "evidence": {"임대인": transcript, "매매가": transcript},
            "uncertainties": [],
            "summary": "가온고객이 라온단지 매물을 8억에 매도 의뢰함.",
        },
        "source_group_id": "f2-full-v05-sell-bp00-s00",
        "source_scenario_id": None,
        "source_type": "handwritten_dialogue_blueprint",
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


def test_convert_full_sample_uses_ledger_and_complete_expected_json() -> None:
    source = full_sample()

    converted = convert_sample(source, "test", task="full")

    assert converted["id"] == "f2-full-v05-sell-0001"
    assert converted["task"] == "full"
    assert converted["prompt"][1]["content"].startswith("현재 장부 종류: 매물장")
    assert json.loads(converted["completion"][0]["content"]) == source["expected"]


def test_convert_full_sample_rejects_ungrounded_evidence() -> None:
    source = full_sample()
    expected = dict(source["expected"])
    expected["evidence"] = {"임대인": "원문에 없는 문장", "매매가": "원문에 없는 문장"}

    with pytest.raises(ValueError, match="원문에 없는 evidence"):
        convert_sample(full_sample(expected=expected), "test", task="full")


def test_convert_full_sample_rejects_incorrect_mismatch_label() -> None:
    source = full_sample()
    expected = dict(source["expected"])
    expected["ledger_mismatch"] = True

    with pytest.raises(ValueError, match="장부·라벨 규칙"):
        convert_sample(full_sample(expected=expected), "test", task="full")


def test_convert_full_sample_rejects_fields_on_mismatch() -> None:
    source = full_sample()
    expected = dict(source["expected"])
    expected["ledger_mismatch"] = True

    with pytest.raises(ValueError, match="필드를 제안할 수 없습니다"):
        convert_sample(
            full_sample(ledger_type="구입장", expected=expected),
            "test",
            task="full",
        )


def test_convert_file_rejects_duplicate_ids(tmp_path: Path) -> None:
    input_path = tmp_path / "train.jsonl"
    output_path = tmp_path / "sft-train.jsonl"
    lines = [json.dumps(sample(), ensure_ascii=False), json.dumps(sample(), ensure_ascii=False)]
    input_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="중복 id"):
        convert_file(input_path, output_path)
