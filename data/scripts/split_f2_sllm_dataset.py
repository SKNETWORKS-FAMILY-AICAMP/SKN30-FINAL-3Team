"""F2 상담 JSONL을 source_group_id 단위로 train/validation/test 분할한다.

상담 유형 분류 스키마(`scenario_id`)와 full-output 스키마(`sample_id`, `ledger_type`,
`expected`)를 모두 받는다. full-output 행은 장부·라벨 정합과 필드 제안 금지 구간을 함께
검사하고, 분할 보고서에 장부와 셀 분포를 남긴다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

LABELS = ("매도의뢰", "매수문의", "기타상담")
LEGACY_LABELS = {
    "매수의뢰": "매수문의",
    "공동중개": "기타상담",
    "단순문의": "기타상담",
}
LEDGERS = ("매물장", "구입장")
# 분류 데이터는 scenario_id, full-output 데이터는 sample_id를 식별자로 쓴다.
ID_FIELDS = ("scenario_id", "sample_id")
REQUIRED_FIELDS = {
    "transcript",
    "label",
    "source_group_id",
    "contains_real_personal_data",
}
MATCHING_CELLS = {("매도의뢰", "매물장"), ("매수문의", "구입장")}


def identifier_of(sample: dict[str, Any], where: str) -> str:
    """행의 식별자를 찾는다. 두 스키마 중 어느 쪽이든 하나는 있어야 한다."""

    present = [name for name in ID_FIELDS if name in sample]
    if not present:
        raise ValueError(f"{where}: 식별자 누락 {list(ID_FIELDS)} 중 하나가 필요합니다")
    if len(present) > 1:
        raise ValueError(f"{where}: 식별자가 둘 이상입니다 {present}")
    return sample[present[0]]


def check_full_output(sample: dict[str, Any], label: str, where: str) -> None:
    """full-output 행의 장부·라벨 정합과 필드 제안 금지 구간을 확인한다.

    `expected`가 없는 분류 전용 행은 검사 대상이 아니다.
    """

    expected = sample["expected"]
    if not isinstance(expected, dict):
        raise ValueError(f"{where}: expected가 객체가 아닙니다")
    ledger = sample.get("ledger_type")
    if ledger not in LEDGERS:
        raise ValueError(f"{where}: 알 수 없는 ledger_type {ledger!r}")
    if expected.get("consultation_type") != label:
        raise ValueError(f"{where}: label과 expected.consultation_type이 다릅니다")

    mismatch = expected.get("ledger_mismatch")
    if not isinstance(mismatch, bool):
        raise ValueError(f"{where}: ledger_mismatch가 bool이 아닙니다")
    derived = label != "기타상담" and (label, ledger) not in MATCHING_CELLS
    if mismatch is not derived:
        raise ValueError(
            f"{where}: ledger_mismatch가 label·ledger_type 조합과 맞지 않습니다 "
            f"({label}, {ledger})"
        )

    fields = expected.get("fields")
    evidence = expected.get("evidence")
    if not isinstance(fields, dict) or not isinstance(evidence, dict):
        raise ValueError(f"{where}: fields와 evidence는 객체여야 합니다")
    if fields.keys() != evidence.keys():
        raise ValueError(f"{where}: fields와 evidence의 키가 다릅니다")
    if (mismatch or label == "기타상담") and fields:
        raise ValueError(f"{where}: 필드를 제안할 수 없는 행에 fields가 있습니다")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="원본 JSONL")
    parser.add_argument("--output-dir", type=Path, required=True, help="분할 결과 디렉터리")
    parser.add_argument(
        "--validation-per-label",
        type=int,
        required=True,
        help="라벨별 validation 목표 건수(그룹 단위라 정확히 일치하지 않을 수 있음)",
    )
    parser.add_argument(
        "--test-per-label",
        type=int,
        required=True,
        help="라벨별 최종 test 목표 건수(그룹 단위라 정확히 일치하지 않을 수 있음)",
    )
    parser.add_argument("--seed", type=int, default=20260820)
    parser.add_argument("--force", action="store_true", help="기존 결과 파일 덮어쓰기")
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_samples(path: Path) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    ids: set[str] = set()
    transcripts: set[str] = set()
    # full-output에서는 한 그룹이 장부까지 같아야 분할 후 셀 분포가 유지된다.
    group_cells: dict[str, tuple[str, str | None]] = {}

    with path.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            where = f"{path}:{line_number}"
            sample = json.loads(line)
            if not isinstance(sample, dict):
                raise TypeError(f"{where}: JSON object가 아닙니다")
            missing = REQUIRED_FIELDS - sample.keys()
            if missing:
                raise ValueError(f"{where}: 필수 필드 누락 {sorted(missing)}")

            record_id = identifier_of(sample, where)
            transcript = sample["transcript"]
            raw_label = sample["label"]
            label = LEGACY_LABELS.get(raw_label, raw_label)
            sample["label"] = label
            group_id = sample["source_group_id"]
            if not all(
                isinstance(value, str) and value.strip()
                for value in (
                    record_id,
                    transcript,
                    label,
                    group_id,
                )
            ):
                raise ValueError(f"{where}: 문자열 필드가 비어 있습니다")
            if label not in LABELS:
                raise ValueError(f"{where}: 알 수 없는 label {label!r}")
            if sample["contains_real_personal_data"] is not False:
                raise ValueError(
                    f"{where}: 실제 개인정보 포함 데이터는 학습 입력으로 사용할 수 없습니다"
                )
            if "expected" in sample:
                check_full_output(sample, label, where)
            if record_id in ids:
                raise ValueError(f"{where}: 중복 식별자 {record_id!r}")
            if transcript in transcripts:
                raise ValueError(f"{where}: 중복 transcript")
            cell = (label, sample.get("ledger_type"))
            previous_cell = group_cells.setdefault(group_id, cell)
            if previous_cell != cell:
                raise ValueError(
                    f"{where}: 한 source_group_id에 여러 label·ledger_type 조합이 있습니다"
                )

            ids.add(record_id)
            transcripts.add(transcript)
            samples.append(sample)

    if not samples:
        raise ValueError(f"{path}: 데이터가 없습니다")
    return samples


def split_samples(
    samples: list[dict[str, Any]], validation_per_label: int, test_per_label: int, seed: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    if validation_per_label < 1 or test_per_label < 1:
        raise ValueError("validation_per_label과 test_per_label은 1 이상이어야 합니다")

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sample in samples:
        grouped[sample["source_group_id"]].append(sample)

    groups_by_label: dict[str, list[list[dict[str, Any]]]] = defaultdict(list)
    for group in grouped.values():
        groups_by_label[group[0]["label"]].append(group)

    missing_labels = set(LABELS) - groups_by_label.keys()
    if missing_labels:
        raise ValueError(f"데이터에 없는 label: {sorted(missing_labels)}")

    rng = random.Random(seed)
    train: list[dict[str, Any]] = []
    validation: list[dict[str, Any]] = []
    test: list[dict[str, Any]] = []
    for label in LABELS:
        groups = groups_by_label[label]
        rng.shuffle(groups)
        label_train: list[dict[str, Any]] = []
        label_validation: list[dict[str, Any]] = []
        label_test: list[dict[str, Any]] = []
        validation_count = 0
        test_count = 0
        for group in groups:
            if validation_count < validation_per_label:
                destination = label_validation
                split_name = "validation"
                validation_count += len(group)
            elif test_count < test_per_label:
                destination = label_test
                split_name = "test"
                test_count += len(group)
            else:
                destination = label_train
                split_name = "train"
            destination.extend({**sample, "split": split_name} for sample in group)
        if not label_train or not label_validation or not label_test:
            raise ValueError(f"{label}: train/validation/test 분할에 충분한 그룹이 없습니다")
        train.extend(label_train)
        validation.extend(label_validation)
        test.extend(label_test)

    rng.shuffle(train)
    rng.shuffle(validation)
    rng.shuffle(test)
    return train, validation, test


def write_jsonl(path: Path, samples: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as file:
        for sample in samples:
            file.write(json.dumps(sample, ensure_ascii=False) + "\n")


def distribution(samples: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(sample["label"] for sample in samples)
    return {label: counts[label] for label in LABELS}


def full_output_summary(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """full-output 행의 장부·셀 분포와 필드 제안 여부를 센다.

    라벨만 층화하면 특정 split에 장부나 불일치가 몰릴 수 있어 보고서에서 확인한다.
    분류 전용 데이터에는 해당 행이 없어 빈 결과를 돌려준다.
    """

    rows = [sample for sample in samples if "expected" in sample]
    if not rows:
        return {}
    ledgers = Counter(sample["ledger_type"] for sample in rows)
    cells = Counter(f"{sample['ledger_type']}+{sample['label']}" for sample in rows)
    mismatch = sum(1 for sample in rows if sample["expected"]["ledger_mismatch"])
    with_fields = sum(1 for sample in rows if sample["expected"]["fields"])
    return {
        "full_output_rows": len(rows),
        "ledger_distribution": {ledger: ledgers[ledger] for ledger in LEDGERS},
        "cell_distribution": dict(cells.most_common()),
        "ledger_mismatch_count": mismatch,
        "rows_with_fields": with_fields,
        "rows_without_fields": len(rows) - with_fields,
    }


def main() -> None:
    args = parse_args()
    output_paths = {
        "train": args.output_dir / "train.jsonl",
        "validation": args.output_dir / "validation.jsonl",
        "test": args.output_dir / "test.jsonl",
        "report": args.output_dir / "split-report.json",
    }
    existing = [path for path in output_paths.values() if path.exists()]
    if existing and not args.force:
        raise FileExistsError(f"기존 결과가 있습니다. --force로 덮어쓰세요: {existing}")

    samples = load_samples(args.input)
    train, validation, test = split_samples(
        samples, args.validation_per_label, args.test_per_label, args.seed
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(output_paths["train"], train)
    write_jsonl(output_paths["validation"], validation)
    write_jsonl(output_paths["test"], test)

    split_samples_by_name = {"train": train, "validation": validation, "test": test}
    split_groups = {
        name: {sample["source_group_id"] for sample in records}
        for name, records in split_samples_by_name.items()
    }
    overlaps = {
        f"{left}/{right}": sorted(split_groups[left] & split_groups[right])
        for left, right in (("train", "validation"), ("train", "test"), ("validation", "test"))
        if split_groups[left] & split_groups[right]
    }
    if overlaps:
        raise RuntimeError(f"분할 간 source_group_id 중복: {overlaps}")

    manifest = {
        "source": {
            "path": str(args.input),
            "sha256": sha256(args.input),
            "count": len(samples),
            **full_output_summary(samples),
        },
        "split_policy": {
            "group_key": "source_group_id",
            "stratify_key": "label",
            "validation_per_label_target": args.validation_per_label,
            "test_per_label_target": args.test_per_label,
            "seed": args.seed,
        },
        "outputs": {
            name: {
                "path": str(path),
                "sha256": sha256(path),
                "count": len(split_samples_by_name[name]),
                "label_distribution": distribution(split_samples_by_name[name]),
                **full_output_summary(split_samples_by_name[name]),
            }
            for name, path in output_paths.items()
            if name != "report"
        },
    }
    output_paths["report"].write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
