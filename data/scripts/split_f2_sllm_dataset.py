"""F2 상담 유형 JSONL을 source_group_id 단위로 train/validation/test 분할한다."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from itertools import pairwise
from pathlib import Path
from typing import Any

LABELS = ("매도의뢰", "매수문의", "기타상담")
LEGACY_LABELS = {
    "매수의뢰": "매수문의",
    "공동중개": "기타상담",
    "단순문의": "기타상담",
}
REQUIRED_FIELDS = {
    "transcript",
    "label",
    "source_group_id",
    "contains_real_personal_data",
}


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
    group_labels: dict[str, str] = {}

    with path.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            sample = json.loads(line)
            if not isinstance(sample, dict):
                raise TypeError(f"{path}:{line_number}: JSON object가 아닙니다")
            missing = REQUIRED_FIELDS - sample.keys()
            if missing:
                raise ValueError(f"{path}:{line_number}: 필수 필드 누락 {sorted(missing)}")

            record_id = sample.get("sample_id", sample.get("scenario_id"))
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
                raise ValueError(f"{path}:{line_number}: 문자열 필드가 비어 있습니다")
            if label not in LABELS:
                raise ValueError(f"{path}:{line_number}: 알 수 없는 label {label!r}")
            if sample["contains_real_personal_data"] is not False:
                raise ValueError(
                    f"{path}:{line_number}: 실제 개인정보 포함 데이터는 "
                    "학습 입력으로 사용할 수 없습니다"
                )
            if record_id in ids:
                raise ValueError(f"{path}:{line_number}: 중복 record id {record_id!r}")
            if transcript in transcripts:
                raise ValueError(f"{path}:{line_number}: 중복 transcript")
            previous_label = group_labels.setdefault(group_id, label)
            if previous_label != label:
                raise ValueError(
                    f"{path}:{line_number}: 한 source_group_id에 여러 label이 있습니다"
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


def normalized_bigrams(text: str) -> set[tuple[str, str]]:
    """숫자 슬롯을 일반화한 어절 bigram으로 near-duplicate 진단용 지문을 만든다."""

    tokens = ["#" if token.isdigit() else token for token in re.findall(r"[가-힣A-Za-z]+|\d+", text)]
    return set(pairwise(tokens))


def cross_split_near_duplicates(
    split_samples: dict[str, list[dict[str, Any]]], threshold: float = 0.85
) -> dict[str, Any]:
    """서로 다른 split의 매우 유사한 문장을 진단하되 자동 합격선으로 사용하지 않는다."""

    fingerprints = {
        name: [(sample, normalized_bigrams(sample["transcript"])) for sample in samples]
        for name, samples in split_samples.items()
    }
    pairs: list[dict[str, Any]] = []
    count = 0
    for left, right in (("train", "validation"), ("train", "test"), ("validation", "test")):
        for left_sample, left_fingerprint in fingerprints[left]:
            for right_sample, right_fingerprint in fingerprints[right]:
                union = left_fingerprint | right_fingerprint
                similarity = len(left_fingerprint & right_fingerprint) / len(union) if union else 1.0
                if similarity < threshold:
                    continue
                count += 1
                if len(pairs) < 20:
                    pairs.append(
                        {
                            "splits": f"{left}/{right}",
                            "left_id": left_sample.get("sample_id", left_sample.get("scenario_id")),
                            "right_id": right_sample.get("sample_id", right_sample.get("scenario_id")),
                            "similarity": round(similarity, 4),
                        }
                    )
    return {
        "method": "number-normalized word-bigram Jaccard",
        "threshold": threshold,
        "cross_split_pair_count": count,
        "sample_pairs": pairs,
        "interpretation": "diagnostic_only_not_an_approved_quality_threshold",
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

    all_group_sizes = Counter(sample["source_group_id"] for sample in samples)

    manifest = {
        "source": {"path": str(args.input), "sha256": sha256(args.input), "count": len(samples)},
        "split_policy": {
            "group_key": "source_group_id",
            "stratify_key": "label",
            "validation_per_label_target": args.validation_per_label,
            "test_per_label_target": args.test_per_label,
            "seed": args.seed,
        },
        "group_quality": {
            "source_group_count": len(all_group_sizes),
            "minimum_group_size": min(all_group_sizes.values()),
            "maximum_group_size": max(all_group_sizes.values()),
            "cross_split_group_overlap_count": 0,
            "near_duplicate_diagnostic": cross_split_near_duplicates(split_samples_by_name),
        },
        "outputs": {
            name: {
                "path": str(path),
                "sha256": sha256(path),
                "count": len(split_samples_by_name[name]),
                "label_distribution": distribution(split_samples_by_name[name]),
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
