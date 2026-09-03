"""F2 Tier A 생성본과 Tier B 재포장본을 분할 전 full-output JSONL로 병합한다.

두 입력의 모델 입력·정답은 모두 같은 full-output 계약이다. Tier B에만 있는
`source_scenario_id`는 Tier A 행에 null을 넣어 메타데이터 스키마를 통일한다.
병합본은 분할하지 않으며 모든 행의 `split`은 `unassigned`로 유지한다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TIER_A = (
    ROOT / "f2_llm" / "working" / "f2_full_output_scenarios.privacy_safe.v0.5.jsonl"
)
DEFAULT_TIER_B = (
    ROOT
    / "f2_llm"
    / "working"
    / "f2_rewrapped_full_output_scenarios.privacy_safe.v0.5.jsonl"
)
DEFAULT_OUTPUT = (
    ROOT
    / "f2_llm"
    / "working"
    / "f2_merged_full_output_scenarios.privacy_safe.v0.5.jsonl"
)

LABELS = {"매도의뢰", "매수문의", "기타상담"}
LEDGER_TYPES = {"매물장", "구입장"}
EXPECTED_KEYS = {
    "consultation_type",
    "ledger_mismatch",
    "fields",
    "evidence",
    "uncertainties",
    "summary",
}
COMMON_KEYS = {
    "sample_id",
    "dataset_version",
    "label",
    "transcript",
    "ledger_type",
    "expected",
    "source_type",
    "source_group_id",
    "split",
    "contains_real_personal_data",
    "review_status",
    "difficulty_tags",
}
MERGED_KEYS = COMMON_KEYS | {"source_scenario_id"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier-a", type=Path, default=DEFAULT_TIER_A)
    parser.add_argument("--tier-b", type=Path, default=DEFAULT_TIER_B)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true", help="기존 병합본 덮어쓰기")
    return parser.parse_args()


def expected_mismatch(ledger_type: str, label: str) -> bool:
    return (ledger_type == "매물장" and label == "매수문의") or (
        ledger_type == "구입장" and label == "매도의뢰"
    )


def load_rows(path: Path, tier: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            location = f"{path}:{line_number}"
            row = json.loads(line)
            if not isinstance(row, dict):
                raise TypeError(f"{location}: JSON object가 아닙니다")
            allowed_keys = COMMON_KEYS if tier == "tier_a" else MERGED_KEYS
            if set(row) != allowed_keys:
                raise ValueError(f"{location}: {tier} 스키마가 다릅니다")
            normalized = dict(row)
            normalized.setdefault("source_scenario_id", None)
            rows.append(normalized)
    if not rows:
        raise ValueError(f"{path}: 데이터가 없습니다")
    return rows


def validate_row(row: dict[str, Any], source: str) -> None:
    if set(row) != MERGED_KEYS:
        raise ValueError(f"{source}: 병합 스키마가 다릅니다")
    if row["dataset_version"] != "0.5.0":
        raise ValueError(f"{source}: dataset_version은 '0.5.0'이어야 합니다")
    if row["label"] not in LABELS or row["ledger_type"] not in LEDGER_TYPES:
        raise ValueError(f"{source}: label 또는 ledger_type이 잘못되었습니다")
    if not isinstance(row["transcript"], str) or not row["transcript"].strip():
        raise ValueError(f"{source}: transcript가 비어 있습니다")
    if row["split"] != "unassigned":
        raise ValueError(f"{source}: 병합 전 split은 'unassigned'여야 합니다")
    if row["contains_real_personal_data"] is not False:
        raise ValueError(f"{source}: 실제 개인정보 플래그가 있습니다")

    expected = row["expected"]
    if not isinstance(expected, dict) or set(expected) != EXPECTED_KEYS:
        raise ValueError(f"{source}: expected 6-key 계약이 다릅니다")
    if expected["consultation_type"] != row["label"]:
        raise ValueError(f"{source}: label과 consultation_type이 다릅니다")
    mismatch = expected_mismatch(row["ledger_type"], row["label"])
    if expected["ledger_mismatch"] is not mismatch:
        raise ValueError(f"{source}: ledger_mismatch 규칙이 다릅니다")
    fields = expected["fields"]
    evidence = expected["evidence"]
    if not isinstance(fields, dict) or not isinstance(evidence, dict):
        raise ValueError(f"{source}: fields와 evidence는 JSON object여야 합니다")
    if set(fields) != set(evidence):
        raise ValueError(f"{source}: fields와 evidence 키가 다릅니다")
    if (mismatch or row["label"] == "기타상담") and (fields or evidence):
        raise ValueError(f"{source}: 필드 제안 금지 구간에 fields가 있습니다")
    for field_name, cited in evidence.items():
        if not isinstance(cited, str) or cited not in row["transcript"]:
            raise ValueError(f"{source}: 원문에 없는 evidence {field_name!r}")
    if not isinstance(expected["uncertainties"], list) or not all(
        isinstance(value, str) for value in expected["uncertainties"]
    ):
        raise ValueError(f"{source}: uncertainties는 문자열 배열이어야 합니다")
    if not isinstance(expected["summary"], str) or not expected["summary"].strip():
        raise ValueError(f"{source}: summary가 비어 있습니다")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_combined(rows: list[dict[str, Any]]) -> dict[str, Any]:
    for position, row in enumerate(rows, start=1):
        validate_row(row, f"merged:{position}")
    for key in ("sample_id", "transcript"):
        values = [row[key] for row in rows]
        if len(set(values)) != len(values):
            raise ValueError(f"병합 후 중복 {key}")

    cell_counts = Counter(f"{row['ledger_type']}+{row['label']}" for row in rows)
    source_counts = Counter(row["source_type"] for row in rows)
    return {
        "rows": len(rows),
        "source_groups": len({row["source_group_id"] for row in rows}),
        "rows_with_fields": sum(bool(row["expected"]["fields"]) for row in rows),
        "rows_without_fields": sum(not row["expected"]["fields"] for row in rows),
        "ledger_mismatch_rows": sum(row["expected"]["ledger_mismatch"] for row in rows),
        "labels": dict(sorted(Counter(row["label"] for row in rows).items())),
        "cells": dict(sorted(cell_counts.items())),
        "source_types": dict(sorted(source_counts.items())),
        "compact_rows_with_fields": sum(
            bool(row["expected"]["fields"])
            and "compact_dialogue" in row["difficulty_tags"]
            for row in rows
        ),
    }


def main() -> None:
    args = parse_args()
    if args.output.exists() and not args.force:
        raise FileExistsError(f"기존 병합본이 있습니다: {args.output}")

    tier_a = load_rows(args.tier_a, "tier_a")
    tier_b = load_rows(args.tier_b, "tier_b")
    for key in ("sample_id", "source_group_id", "transcript"):
        tier_a_values = {row[key] for row in tier_a}
        tier_b_values = {row[key] for row in tier_b}
        if overlap := tier_a_values & tier_b_values:
            raise ValueError(f"두 파일 간 {key} 충돌: {sorted(overlap)[:5]}")
    rows = [*tier_a, *tier_b]
    report = validate_combined(rows)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as destination:
        for row in rows:
            destination.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    print(
        json.dumps(
            {
                "output": str(args.output),
                "input_sha256": {
                    "tier_a": sha256(args.tier_a),
                    "tier_b": sha256(args.tier_b),
                },
                "output_sha256": sha256(args.output),
                **report,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
