#!/usr/bin/env python3
"""분할된 F2 상담 유형 JSONL을 TRL prompt-completion 형식으로 변환한다."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

LABELS = ("매도의뢰", "매수문의", "기타상담")
SYSTEM_PROMPT = """당신은 부동산 상담 유형 분류기입니다.
입력으로 STT 상담 텍스트만 받습니다.

매도·임대 의뢰는 매도의뢰, 매수·임차 수요는 매수문의로 분류하세요.
그 밖의 공동중개, 단순문의, 불명확하거나 혼합된 상담은 기타상담으로 분류하세요.
설명이나 마크다운 없이 다음 형식의 JSON 객체 하나만 출력하세요.
{"consultation_type": "매도의뢰|매수문의|기타상담"}"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path, required=True, help="train.jsonl 또는 validation.jsonl"
    )
    parser.add_argument("--output", type=Path, required=True, help="변환 결과 JSONL")
    parser.add_argument("--force", action="store_true", help="기존 결과 덮어쓰기")
    return parser.parse_args()


def convert_sample(sample: dict[str, Any], source: str) -> dict[str, Any]:
    required = {"scenario_id", "transcript", "label", "source_group_id", "split"}
    missing = required - sample.keys()
    if missing:
        raise ValueError(f"{source}: 필수 필드 누락 {sorted(missing)}")
    if sample["label"] not in LABELS:
        raise ValueError(f"{source}: 알 수 없는 label {sample['label']!r}")
    if not isinstance(sample["transcript"], str) or not sample["transcript"].strip():
        raise ValueError(f"{source}: transcript가 비어 있습니다")
    if sample["split"] not in {"train", "validation"}:
        raise ValueError(f"{source}: test 데이터는 SFT 입력으로 변환할 수 없습니다")

    answer = json.dumps(
        {"consultation_type": sample["label"]}, ensure_ascii=False, separators=(",", ":")
    )
    return {
        "id": sample["scenario_id"],
        "prompt": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"STT 상담 텍스트:\n{sample['transcript']}"},
        ],
        "completion": [{"role": "assistant", "content": answer}],
        "label": sample["label"],
        "source_group_id": sample["source_group_id"],
        "split": sample["split"],
    }


def convert_file(input_path: Path, output_path: Path, force: bool = False) -> int:
    if output_path.exists() and not force:
        raise FileExistsError(f"기존 결과가 있습니다. --force로 덮어쓰세요: {output_path}")

    converted: list[dict[str, Any]] = []
    ids: set[str] = set()
    with input_path.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            sample = json.loads(line)
            result = convert_sample(sample, f"{input_path}:{line_number}")
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
    count = convert_file(args.input, args.output, args.force)
    print(f"{count}건 변환 완료: {args.output}")


if __name__ == "__main__":
    main()
