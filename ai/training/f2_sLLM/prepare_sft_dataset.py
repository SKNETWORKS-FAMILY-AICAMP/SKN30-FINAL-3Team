#!/usr/bin/env python3
"""분할된 F2 분류·full-output JSONL을 TRL prompt-completion 형식으로 변환한다."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

LABELS = ("매도의뢰", "매수문의", "기타상담")
LEDGER_TYPES = ("매물장", "구입장")
CLASSIFICATION_SYSTEM_PROMPT = """당신은 부동산 상담 유형 분류기입니다.
입력으로 STT 상담 텍스트만 받습니다.

매도·임대 의뢰는 매도의뢰, 매수·임차 수요는 매수문의로 분류하세요.
그 밖의 공동중개, 단순문의, 불명확하거나 혼합된 상담은 기타상담으로 분류하세요.
설명이나 마크다운 없이 다음 형식의 JSON 객체 하나만 출력하세요.
{"consultation_type": "매도의뢰|매수문의|기타상담"}"""

FULL_OUTPUT_SYSTEM_PROMPT = """당신은 부동산 상담 메모 분석기입니다.
입력으로 STT 상담 텍스트와 현재 장부 종류만 받습니다.

반드시 다음 규칙을 지키세요.
- 매도·임대 의뢰는 매도의뢰, 매수·임차 수요는 매수문의로 분류합니다.
- 공동중개, 단순문의, 불명확하거나 혼합된 상담은 기타상담으로 분류합니다.
- 매물장에서 매수문의이거나 구입장에서 매도의뢰이면 ledger_mismatch를 true로 둡니다.
- ledger_mismatch가 true이거나 기타상담이면 fields와 evidence는 빈 객체로 둡니다.
- 원문에서 명확히 확인된 값만 fields에 넣습니다.
- 불명확한 숫자, 날짜, 동, 호 또는 충돌하는 값은 확정하지 말고 uncertainties에 적습니다.
- 기존 장부 값을 추측하거나 자동으로 덮어쓰지 않습니다.
- 각 fields 값에는 원문 그대로의 evidence 문장을 제공합니다.
- 설명이나 마크다운 없이 JSON 객체 하나만 출력합니다.

출력 형식:
{
  "consultation_type": "매도의뢰|매수문의|기타상담",
  "ledger_mismatch": false,
  "fields": {"필드명": "값"},
  "evidence": {"필드명": "원문 근거"},
  "uncertainties": ["불명확하거나 충돌한 내용"],
  "summary": "상담 로그 초안"
}"""

FULL_EXPECTED_KEYS = {
    "consultation_type",
    "ledger_mismatch",
    "fields",
    "evidence",
    "uncertainties",
    "summary",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path, required=True, help="train.jsonl 또는 validation.jsonl"
    )
    parser.add_argument("--output", type=Path, required=True, help="변환 결과 JSONL")
    parser.add_argument(
        "--task",
        choices=("classification", "full"),
        default="classification",
        help="classification: 상담 유형만 학습, full: 분류·장부 불일치·필드·근거·요약 학습",
    )
    parser.add_argument("--force", action="store_true", help="기존 결과 덮어쓰기")
    return parser.parse_args()


def validate_common(sample: dict[str, Any], source: str, required: set[str]) -> None:
    """두 학습 과제가 공유하는 transcript, split과 필수 필드를 검사한다."""

    missing = required - sample.keys()
    if missing:
        raise ValueError(f"{source}: 필수 필드 누락 {sorted(missing)}")
    if not isinstance(sample["transcript"], str) or not sample["transcript"].strip():
        raise ValueError(f"{source}: transcript가 비어 있습니다")
    if sample["split"] not in {"train", "validation"}:
        raise ValueError(f"{source}: test 데이터는 SFT 입력으로 변환할 수 없습니다")


def convert_classification_sample(sample: dict[str, Any], source: str) -> dict[str, Any]:
    """기존 상담 유형 분류 사례를 한 필드 JSON 정답으로 변환한다."""

    required = {"scenario_id", "transcript", "label", "source_group_id", "split"}
    validate_common(sample, source, required)
    if sample["label"] not in LABELS:
        raise ValueError(f"{source}: 알 수 없는 label {sample['label']!r}")

    answer = json.dumps(
        {"consultation_type": sample["label"]}, ensure_ascii=False, separators=(",", ":")
    )
    return {
        "id": sample["scenario_id"],
        "prompt": [
            {"role": "system", "content": CLASSIFICATION_SYSTEM_PROMPT},
            {"role": "user", "content": f"STT 상담 텍스트:\n{sample['transcript']}"},
        ],
        "completion": [{"role": "assistant", "content": answer}],
        "task": "classification",
        "label": sample["label"],
        "source_group_id": sample["source_group_id"],
        "split": sample["split"],
    }


def expected_mismatch(ledger_type: str, label: str) -> bool:
    return (ledger_type == "매물장" and label == "매수문의") or (
        ledger_type == "구입장" and label == "매도의뢰"
    )


def convert_full_sample(sample: dict[str, Any], source: str) -> dict[str, Any]:
    """full-output 사례를 현재 장부+STT 입력과 전체 JSON 정답으로 변환한다."""

    required = {
        "sample_id",
        "transcript",
        "label",
        "ledger_type",
        "expected",
        "source_group_id",
        "split",
    }
    validate_common(sample, source, required)
    if sample["label"] not in LABELS:
        raise ValueError(f"{source}: 알 수 없는 label {sample['label']!r}")
    if sample["ledger_type"] not in LEDGER_TYPES:
        raise ValueError(f"{source}: 알 수 없는 ledger_type {sample['ledger_type']!r}")

    expected = sample["expected"]
    if not isinstance(expected, dict) or set(expected) != FULL_EXPECTED_KEYS:
        raise ValueError(f"{source}: expected는 정확한 6-key JSON 객체여야 합니다")
    if expected["consultation_type"] != sample["label"]:
        raise ValueError(f"{source}: label과 expected.consultation_type이 다릅니다")
    if not isinstance(expected["ledger_mismatch"], bool):
        raise ValueError(f"{source}: expected.ledger_mismatch는 boolean이어야 합니다")
    mismatch = expected_mismatch(sample["ledger_type"], sample["label"])
    if expected["ledger_mismatch"] is not mismatch:
        raise ValueError(f"{source}: expected.ledger_mismatch가 장부·라벨 규칙과 다릅니다")
    if not isinstance(expected["fields"], dict) or not isinstance(expected["evidence"], dict):
        raise ValueError(f"{source}: expected.fields와 evidence는 JSON 객체여야 합니다")
    if set(expected["fields"]) != set(expected["evidence"]):
        raise ValueError(f"{source}: expected.fields와 evidence의 필드가 다릅니다")
    if not all(
        isinstance(field_name, str) and isinstance(value, str)
        for field_name, value in expected["fields"].items()
    ):
        raise ValueError(f"{source}: expected.fields는 문자열 필드명과 값이어야 합니다")
    if not isinstance(expected["uncertainties"], list) or not all(
        isinstance(value, str) for value in expected["uncertainties"]
    ):
        raise ValueError(f"{source}: expected.uncertainties는 문자열 배열이어야 합니다")
    if not isinstance(expected["summary"], str) or not expected["summary"].strip():
        raise ValueError(f"{source}: expected.summary가 비어 있습니다")
    for field_name, evidence in expected["evidence"].items():
        if not isinstance(evidence, str) or evidence not in sample["transcript"]:
            raise ValueError(f"{source}: 원문에 없는 evidence {field_name!r}")
    if (mismatch or sample["label"] == "기타상담") and (expected["fields"] or expected["evidence"]):
        raise ValueError(f"{source}: 장부 불일치·기타상담은 필드를 제안할 수 없습니다")

    answer = json.dumps(expected, ensure_ascii=False, separators=(",", ":"))
    return {
        "id": sample["sample_id"],
        "prompt": [
            {"role": "system", "content": FULL_OUTPUT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"현재 장부 종류: {sample['ledger_type']}\n"
                    f"STT 상담 텍스트:\n{sample['transcript']}"
                ),
            },
        ],
        "completion": [{"role": "assistant", "content": answer}],
        "task": "full",
        "label": sample["label"],
        "source_group_id": sample["source_group_id"],
        "split": sample["split"],
    }


def convert_sample(
    sample: dict[str, Any], source: str, task: str = "classification"
) -> dict[str, Any]:
    """선택한 과제의 원본 사례를 SFT prompt-completion 한 건으로 변환한다."""

    if task == "classification":
        return convert_classification_sample(sample, source)
    if task == "full":
        return convert_full_sample(sample, source)
    raise ValueError(f"지원하지 않는 task {task!r}")


def convert_file(
    input_path: Path,
    output_path: Path,
    force: bool = False,
    task: str = "classification",
) -> int:
    if output_path.exists() and not force:
        raise FileExistsError(f"기존 결과가 있습니다. --force로 덮어쓰세요: {output_path}")

    converted: list[dict[str, Any]] = []
    ids: set[str] = set()
    with input_path.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            sample = json.loads(line)
            result = convert_sample(sample, f"{input_path}:{line_number}", task)
            if result["id"] in ids:
                raise ValueError(f"{input_path}:{line_number}: 중복 id {result['id']!r}")
            ids.add(result["id"])
            converted.append(result)
    if not converted:
        raise ValueError(f"{input_path}: 데이터가 없습니다")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        for sample in converted:
            file.write(json.dumps(sample, ensure_ascii=False) + "\n")
    return len(converted)


def main() -> None:
    args = parse_args()
    count = convert_file(args.input, args.output, args.force, args.task)
    print(f"{count}건 변환 완료: {args.output}")


if __name__ == "__main__":
    main()
