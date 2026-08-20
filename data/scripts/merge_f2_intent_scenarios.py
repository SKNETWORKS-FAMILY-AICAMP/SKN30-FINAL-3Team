from __future__ import annotations

import argparse
import json
import random
from pathlib import Path


EXPECTED_KEYS = {
    "scenario_id",
    "dataset_version",
    "label",
    "transcript",
    "source_type",
    "source_group_id",
    "split",
    "contains_real_personal_data",
}
SOURCE_LABELS = {"매도의뢰", "매수의뢰", "공동중개", "단순문의"}
OUTPUT_LABELS = {"매도의뢰", "매수문의", "공동중개", "단순문의"}
LABEL_NORMALIZATION = {"매수의뢰": "매수문의"}
SHUFFLE_SEED = 20260819


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="F2 상담 유형별 JSONL 네 개를 검증하고 하나로 병합한다."
    )
    parser.add_argument("inputs", nargs=4, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: row must be an object")
            if set(value) != EXPECTED_KEYS:
                raise ValueError(f"{path}:{line_number}: schema mismatch")
            rows.append(value)
    if len(rows) != 50:
        raise ValueError(f"{path}: expected 50 rows, got {len(rows)}")
    labels = {str(row["label"]) for row in rows}
    if len(labels) != 1 or not labels <= SOURCE_LABELS:
        raise ValueError(f"{path}: invalid labels {sorted(labels)}")
    return rows


def validate_combined(rows: list[dict[str, object]]) -> None:
    if len(rows) != 200:
        raise ValueError(f"expected 200 rows, got {len(rows)}")

    for key in ("scenario_id", "source_group_id", "transcript"):
        values = [str(row[key]) for row in rows]
        if len(set(values)) != len(values):
            raise ValueError(f"duplicate {key}")

    if any(row["contains_real_personal_data"] is not False for row in rows):
        raise ValueError("contains_real_personal_data must be false")
    if {str(row["dataset_version"]) for row in rows} != {"0.2.0"}:
        raise ValueError("all source rows must use dataset_version 0.2.0")
    if {str(row["split"]) for row in rows} != {"unassigned"}:
        raise ValueError("all source rows must have split=unassigned")

    label_counts = {
        label: sum(row["label"] == label for row in rows) for label in OUTPUT_LABELS
    }
    if label_counts != {label: 50 for label in OUTPUT_LABELS}:
        raise ValueError(f"unexpected label distribution: {label_counts}")


def main() -> None:
    args = parse_args()
    rows = [row for path in args.inputs for row in read_jsonl(path)]
    for row in rows:
        label = str(row["label"])
        row["label"] = LABEL_NORMALIZATION.get(label, label)

    validate_combined(rows)
    random.Random(SHUFFLE_SEED).shuffle(rows)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as destination:
        for row in rows:
            destination.write(
                json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            )


if __name__ == "__main__":
    main()
