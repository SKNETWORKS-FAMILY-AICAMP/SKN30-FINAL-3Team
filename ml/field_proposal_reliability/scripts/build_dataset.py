#!/usr/bin/env python3
"""Build the deterministic synthetic F2 field-proposal review PoC dataset.

The source JSONL files are already synthetic project fixtures.  This script
derives one proposal-shaped row from each selected source scenario and creates
a rule-based proxy target.  It does not claim that the target is human feedback
or the output of the production sLLM.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np


RANDOM_STATE = 42
ROWS_PER_FIELD = 15
POSITIVE_ROWS_PER_FIELD = 7

FIELD_TYPES = (
    "sale_price",
    "jeonse_deposit",
    "monthly_rent",
    "monthly_deposit",
    "expiry_date",
    "building_number",
    "unit_number",
    "pyeong",
    "deal_type",
    "handover_condition",
)

MODEL_FEATURE_COLUMNS = (
    "field_type",
    "confidence",
    "evidence_length",
    "mention_count",
    "has_conflict",
    "has_negation",
    "parse_success",
)
TARGET_COLUMN = "needs_review"

OUTPUT_COLUMNS = (
    "proposal_id",
    "source_scenario_id",
    "source_group_id",
    "source_transcript_hash",
    "source_dataset",
    "source_label",
    "proxy_risk_score",
    *MODEL_FEATURE_COLUMNS,
    TARGET_COLUMN,
)

SOURCE_SPECS = (
    (
        "f2_sllm_naturalistic",
        Path("data/f2_llm/working/f2_sllm_.jsonl"),
        "f2_sllm_.jsonl",
    ),
    (
        "f2_sllm_blueprint",
        Path("data/f2_llm/working/f2_sllm_data_small.jsonl"),
        "f2_sllm_data_small.jsonl",
    ),
    (
        "f2_sell_request_blueprint",
        Path(
            "data/f2_sell_request/working/"
            "f2_sell_request_scenarios.privacy_safe.v0.2.jsonl"
        ),
        "f2_sell_request_scenarios.privacy_safe.v0.2.jsonl",
    ),
)

FIELD_SIGNALS: dict[str, tuple[str, ...]] = {
    "sale_price": ("매매", "매도", "매수", "희망 가격", "억", "시세", "가격"),
    "jeonse_deposit": ("전세보증금", "전세 보증금", "전세", "보증금"),
    "monthly_rent": ("월세", "월 임대료", "월 임대", "월 임차료"),
    "monthly_deposit": ("월세 보증금", "보증금", "월세"),
    "expiry_date": ("만기", "계약 종료", "계약기간", "계약 기간", "개월", "내년", "날짜"),
    "building_number": ("동", "가상동", "건물"),
    "unit_number": ("호", "가상호", "호실"),
    "pyeong": ("평형", "평", "제곱미터", "㎡", "전용면적"),
    "deal_type": ("매매", "매도", "매수", "전세", "월세", "임대", "소유권"),
    "handover_condition": ("명도", "입주", "퇴거", "공실", "잔금", "인도", "이사"),
}

VALUE_PATTERNS: dict[str, tuple[str, ...]] = {
    "sale_price": (
        r"(?:[일이삼사오육칠팔구십백천만억\d,]+(?:\s*[억천백만]+)?\s*원)",
        r"(?:[일이삼사오육칠팔구십백천만\d,]+\s*억(?:\s*[일이삼사오육칠팔구십백천만\d,]+)?)",
        r"(?:희망\s*가격|매매가|가격|시세)",
    ),
    "jeonse_deposit": (
        r"전세\s*보증금",
        r"전세.{0,18}?(?:[일이삼사오육칠팔구십백천만억\d,]+\s*(?:억|만원|원))",
        r"전세",
    ),
    "monthly_rent": (
        r"월세.{0,18}?(?:[일이삼사오육칠팔구십백천만억\d,]+\s*(?:만원|원))",
        r"월\s*(?:임대료|임차료)",
        r"월세",
    ),
    "monthly_deposit": (
        r"(?:월세\s*)?보증금.{0,18}?(?:[일이삼사오육칠팔구십백천만억\d,]+\s*(?:억|만원|원))",
        r"보증금",
        r"월세",
    ),
    "expiry_date": (
        r"\d{4}[-./년]\s*\d{1,2}(?:[-./월]\s*\d{1,2}일?)?",
        r"(?:다음|이번|내년|올해|금년).{0,5}?(?:달|월|년)",
        r"\d+\s*(?:개월|년)",
        r"만기|계약\s*종료",
    ),
    "building_number": (
        r"\[가상동-[^\]]+\]",
        r"\d{1,4}\s*동",
        r"[가-힣]{1,12}동",
    ),
    "unit_number": (
        r"\[가상호-[^\]]+\]",
        r"\d{1,5}\s*호",
        r"호실",
    ),
    "pyeong": (
        r"\d+(?:\.\d+)?\s*(?:평|㎡|제곱미터)",
        r"(?:소형과\s*중형\s*사이|초소형|소형|중소형|중형|중대형|대형)\s*평형",
        r"평형|전용면적",
    ),
    "deal_type": (r"매매|매도|매수|전세|월세|임대|소유권\s*이전",),
    "handover_condition": (
        r"(?:즉시|바로|\d+\s*(?:일|주|개월|달)\s*(?:뒤|후|정도)?).{0,8}?(?:입주|이사|인도|명도)",
        r"공실|명도|입주|퇴거|인도|잔금|이사",
    ),
}

EXPLICIT_PARSE_PATTERNS: dict[str, tuple[str, ...]] = {
    "sale_price": (
        r"[일이삼사오육칠팔구십백천만억\d,]+\s*(?:억|만원|원)",
    ),
    "jeonse_deposit": (
        r"전세.{0,22}?[일이삼사오육칠팔구십백천만억\d,]+\s*(?:억|만원|원)",
    ),
    "monthly_rent": (
        r"월세.{0,22}?[일이삼사오육칠팔구십백천만억\d,]+\s*(?:만원|원)",
    ),
    "monthly_deposit": (
        r"보증금.{0,22}?[일이삼사오육칠팔구십백천만억\d,]+\s*(?:억|만원|원)",
    ),
    "expiry_date": (
        r"\d{4}[-./년]\s*\d{1,2}",
        r"\d+\s*(?:개월|년)",
        r"(?:다음|이번|내년|올해|금년).{0,5}?(?:달|월|년)",
    ),
    "building_number": (r"\[가상동-[^\]]+\]", r"\d{1,4}\s*동"),
    "unit_number": (r"\[가상호-[^\]]+\]", r"\d{1,5}\s*호"),
    "pyeong": (r"\d+(?:\.\d+)?\s*(?:평|㎡|제곱미터)",),
    "deal_type": (r"매매|매도|매수|전세|월세|임대|소유권\s*이전",),
    "handover_condition": (r"공실|명도|입주|퇴거|인도|잔금|이사",),
}

NEGATION_TERMS = (
    "안 ",
    "않",
    "아니",
    "없",
    "말고",
    "보류",
    "못 ",
    "원하지 않",
)

CONFLICT_TERMS = (
    "정정",
    "변경",
    "바꿔",
    "말이 꼬",
    "다시",
    "보류했지만",
    "아니라",
    "말고",
    "대신",
    "다만",
    "하지만",
    "보다 적",
    "아래까지",
    "이상",
    "협의",
)

NO_FILL_LABELS = {"공동중개", "단순문의"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repository root containing data/. Auto-detected when omitted.",
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=None,
        help="Optional flat directory containing the three source JSONL files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory. Defaults to <PoC root>/data.",
    )
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_hash(*parts: object) -> str:
    joined = "|".join(str(part) for part in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def find_repo_root(start: Path) -> Path | None:
    for candidate in (start, *start.parents):
        if (candidate / "data/f2_llm/working/f2_sllm_.jsonl").is_file():
            return candidate
    return None


def resolve_sources(
    poc_root: Path, repo_root: Path | None, source_dir: Path | None
) -> list[tuple[str, Path]]:
    resolved: list[tuple[str, Path]] = []
    auto_repo_root = repo_root or find_repo_root(poc_root)

    for source_name, relative_path, filename in SOURCE_SPECS:
        candidates: list[Path] = []
        if source_dir is not None:
            candidates.append(source_dir / filename)
        if auto_repo_root is not None:
            candidates.append(auto_repo_root / relative_path)
        candidates.extend(
            [
                poc_root / "source_data" / filename,
                Path.cwd() / "source_data" / filename,
                Path("/content/source_data") / filename,
            ]
        )
        match = next((candidate.resolve() for candidate in candidates if candidate.is_file()), None)
        if match is None:
            checked = "\n  - ".join(str(path) for path in candidates)
            raise FileNotFoundError(
                f"Source file {filename!r} was not found. Checked:\n  - {checked}"
            )
        resolved.append((source_name, match))

    return resolved


def load_sources(source_paths: Sequence[tuple[str, Path]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen_scenarios: set[str] = set()
    seen_groups: set[str] = set()
    seen_transcripts: set[str] = set()

    for source_name, source_path in source_paths:
        with source_path.open("r", encoding="utf-8") as file_obj:
            for line_number, raw_line in enumerate(file_obj, start=1):
                if not raw_line.strip():
                    continue
                record = json.loads(raw_line)
                required = {
                    "scenario_id",
                    "source_group_id",
                    "label",
                    "transcript",
                    "contains_real_personal_data",
                }
                missing = sorted(required - record.keys())
                if missing:
                    raise ValueError(
                        f"{source_path}:{line_number} missing required keys: {missing}"
                    )
                if record["contains_real_personal_data"] is not False:
                    raise ValueError(
                        f"{source_path}:{line_number} is not marked privacy-safe synthetic data"
                    )
                scenario_id = str(record["scenario_id"])
                group_id = str(record["source_group_id"])
                transcript_hash = hashlib.sha256(
                    str(record["transcript"]).encode("utf-8")
                ).hexdigest()
                if (
                    scenario_id in seen_scenarios
                    or group_id in seen_groups
                    or transcript_hash in seen_transcripts
                ):
                    # The 50-row sell fixture is a complete subset of the
                    # 200-row small fixture. Keep the first appearance so
                    # selection and split cannot leak duplicated transcripts.
                    continue
                seen_scenarios.add(scenario_id)
                seen_groups.add(group_id)
                seen_transcripts.add(transcript_hash)
                records.append(
                    {
                        **record,
                        "_transcript_hash": transcript_hash,
                        "_source_dataset": source_name,
                        "_source_path": str(source_path),
                    }
                )

    if len(records) < len(FIELD_TYPES) * ROWS_PER_FIELD:
        raise ValueError(f"Need at least 150 unique source groups, found {len(records)}")
    return records


def split_sentences(text: str) -> list[str]:
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", text)]
    return [sentence for sentence in sentences if sentence] or [text]


def signal_count(text: str, field_type: str) -> int:
    return sum(text.count(signal) for signal in FIELD_SIGNALS[field_type])


def evidence_sentence(text: str, field_type: str) -> str:
    sentences = split_sentences(text)
    return max(
        sentences,
        key=lambda sentence: (
            signal_count(sentence, field_type),
            -len(sentence),
            stable_hash(field_type, sentence),
        ),
    )


def extract_mentions(text: str, field_type: str) -> list[str]:
    matches: list[str] = []
    for pattern in VALUE_PATTERNS[field_type]:
        matches.extend(match.group(0).strip() for match in re.finditer(pattern, text))
    normalized = []
    seen = set()
    for match in matches:
        compact = re.sub(r"\s+", "", match)
        if compact and compact not in seen:
            seen.add(compact)
            normalized.append(compact)
    return normalized


def parse_success(text: str, field_type: str) -> int:
    return int(any(re.search(pattern, text) for pattern in EXPLICIT_PARSE_PATTERNS[field_type]))


def contains_any(text: str, terms: Iterable[str]) -> int:
    return int(any(term in text for term in terms))


def choose_records(records: Sequence[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    chosen: dict[str, list[dict[str, Any]]] = {}
    used_group_ids: set[str] = set()

    for field_type in FIELD_TYPES:
        ranked = sorted(
            records,
            key=lambda record: (
                -min(signal_count(str(record["transcript"]), field_type), 4),
                stable_hash(RANDOM_STATE, field_type, record["scenario_id"]),
            ),
        )
        available = [
            record for record in ranked if str(record["source_group_id"]) not in used_group_ids
        ]
        if len(available) < ROWS_PER_FIELD:
            raise ValueError(f"Not enough unique source groups for {field_type}")
        selected = available[:ROWS_PER_FIELD]
        chosen[field_type] = selected
        used_group_ids.update(str(record["source_group_id"]) for record in selected)

    return chosen


def build_rows(records: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    rng = np.random.default_rng(RANDOM_STATE)
    chosen = choose_records(records)
    rows: list[dict[str, Any]] = []

    for field_type in FIELD_TYPES:
        field_rows: list[dict[str, Any]] = []
        for position, record in enumerate(chosen[field_type], start=1):
            transcript = str(record["transcript"])
            evidence = evidence_sentence(transcript, field_type)
            mentions = extract_mentions(transcript, field_type)
            mention_count = min(4, max(1, len(mentions)))
            parsed = parse_success(transcript, field_type)
            negation = contains_any(evidence, NEGATION_TERMS)
            conflict = int(
                mention_count > 1
                or contains_any(evidence, CONFLICT_TERMS)
                or contains_any(transcript, ("정정", "변경", "말고", "아니라"))
            )
            confidence_noise = float(rng.normal(0.0, 0.07))
            confidence = float(
                np.clip(
                    0.82
                    + 0.08 * parsed
                    - 0.14 * conflict
                    - 0.10 * negation
                    - 0.04 * (mention_count - 1)
                    + confidence_noise,
                    0.20,
                    0.99,
                )
            )
            no_fill_context = int(str(record["label"]) in NO_FILL_LABELS)
            risk_noise = float(rng.normal(0.0, 0.35))
            proxy_risk_score = (
                2.0 * (1.0 - confidence)
                + 1.5 * conflict
                + 1.2 * negation
                + 0.35 * (mention_count - 1)
                + 1.4 * (1 - parsed)
                + 0.75 * no_fill_context
                + risk_noise
            )
            field_rows.append(
                {
                    "proposal_id": f"f2-review-{field_type}-{position:02d}",
                    "source_scenario_id": str(record["scenario_id"]),
                    "source_group_id": str(record["source_group_id"]),
                    "source_transcript_hash": str(record["_transcript_hash"]),
                    "source_dataset": str(record["_source_dataset"]),
                    "source_label": str(record["label"]),
                    "proxy_risk_score": round(float(proxy_risk_score), 6),
                    "field_type": field_type,
                    "confidence": round(confidence, 6),
                    "evidence_length": min(80, max(5, len(evidence))),
                    "mention_count": mention_count,
                    "has_conflict": conflict,
                    "has_negation": negation,
                    "parse_success": parsed,
                    "needs_review": 0,
                }
            )

        # Seven positives per field guarantees the agreed 70:80 target ratio
        # while the score, rather than one feature, controls the assignment.
        positive_ids = {
            row["proposal_id"]
            for row in sorted(
                field_rows,
                key=lambda row: (-row["proxy_risk_score"], row["proposal_id"]),
            )[:POSITIVE_ROWS_PER_FIELD]
        }
        for row in field_rows:
            row["needs_review"] = int(row["proposal_id"] in positive_ids)
        rows.extend(field_rows)

    return rows


def validate_rows(rows: Sequence[dict[str, Any]]) -> None:
    expected_rows = len(FIELD_TYPES) * ROWS_PER_FIELD
    if len(rows) != expected_rows:
        raise AssertionError(f"Expected {expected_rows} rows, found {len(rows)}")
    if len({row["proposal_id"] for row in rows}) != expected_rows:
        raise AssertionError("proposal_id values must be unique")
    if len({row["source_group_id"] for row in rows}) != expected_rows:
        raise AssertionError("source_group_id values must be unique across all rows")
    if len({row["source_transcript_hash"] for row in rows}) != expected_rows:
        raise AssertionError("source transcripts must be unique across all rows")

    field_counts = Counter(row["field_type"] for row in rows)
    if field_counts != Counter({field_type: ROWS_PER_FIELD for field_type in FIELD_TYPES}):
        raise AssertionError(f"Unexpected field_type distribution: {field_counts}")
    target_counts = Counter(int(row["needs_review"]) for row in rows)
    if target_counts != Counter({0: 80, 1: 70}):
        raise AssertionError(f"Unexpected target distribution: {target_counts}")

    for row in rows:
        if set(row) != set(OUTPUT_COLUMNS):
            raise AssertionError(f"Unexpected columns for {row.get('proposal_id')}")
        if any(value is None or (isinstance(value, float) and math.isnan(value)) for value in row.values()):
            raise AssertionError(f"Missing value in {row['proposal_id']}")
        if not 0.0 <= float(row["confidence"]) <= 1.0:
            raise AssertionError(f"confidence out of range in {row['proposal_id']}")
        if not 5 <= int(row["evidence_length"]) <= 80:
            raise AssertionError(f"evidence_length out of range in {row['proposal_id']}")
        if not 1 <= int(row["mention_count"]) <= 4:
            raise AssertionError(f"mention_count out of range in {row['proposal_id']}")
        for column in ("has_conflict", "has_negation", "parse_success", "needs_review"):
            if int(row[column]) not in (0, 1):
                raise AssertionError(f"{column} is not binary in {row['proposal_id']}")


def write_csv(rows: Sequence[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def write_json(payload: Any, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def build_source_inventory(
    source_paths: Sequence[tuple[str, Path]], records: Sequence[dict[str, Any]]
) -> dict[str, Any]:
    retained_rows_by_source = Counter(record["_source_dataset"] for record in records)
    raw_rows_by_source: dict[str, int] = {}
    raw_labels_by_source: dict[str, Counter[str]] = {}
    for source_name, source_path in source_paths:
        raw_count = 0
        labels: Counter[str] = Counter()
        with source_path.open("r", encoding="utf-8") as file_obj:
            for raw_line in file_obj:
                if not raw_line.strip():
                    continue
                raw_count += 1
                labels.update([str(json.loads(raw_line)["label"])])
        raw_rows_by_source[source_name] = raw_count
        raw_labels_by_source[source_name] = labels
    raw_total = sum(raw_rows_by_source.values())
    return {
        "generated_at_utc": utc_now(),
        "dataset_type": "fully_synthetic_project_fixtures",
        "contains_real_personal_data": False,
        "raw_row_count": raw_total,
        "deduplicated_row_count": len(records),
        "duplicate_row_count": raw_total - len(records),
        "deduplication_keys": [
            "scenario_id",
            "source_group_id",
            "sha256(transcript)",
        ],
        "deduplication_note": (
            "The three files contain 1,250 rows. The 50-row sell-request file is "
            "fully duplicated in the 200-row small fixture, leaving 1,200 unique rows."
        ),
        "sources": [
            {
                "source_dataset": source_name,
                "path": str(source_path),
                "sha256": sha256_file(source_path),
                "raw_rows": raw_rows_by_source[source_name],
                "retained_rows_after_cross_file_deduplication": retained_rows_by_source[
                    source_name
                ],
                "raw_label_distribution": dict(
                    sorted(raw_labels_by_source[source_name].items())
                ),
            }
            for source_name, source_path in source_paths
        ],
    }


def print_dataset_summary(rows: Sequence[dict[str, Any]]) -> None:
    print("Dataset generated")
    print(f"Rows: {len(rows)}")
    print(f"Columns: {list(OUTPUT_COLUMNS)}")
    print(f"Target distribution: {dict(sorted(Counter(row[TARGET_COLUMN] for row in rows).items()))}")
    print(f"field_type distribution: {dict(Counter(row['field_type'] for row in rows))}")
    print("Missing values: 0")
    print("First 10 rows:")
    for row in rows[:10]:
        print(json.dumps(row, ensure_ascii=False))


def main() -> None:
    args = parse_args()
    script_path = Path(__file__).resolve()
    poc_root = script_path.parent.parent
    output_dir = (args.output_dir or poc_root / "data").resolve()
    source_paths = resolve_sources(poc_root, args.repo_root, args.source_dir)
    records = load_sources(source_paths)
    rows = build_rows(records)
    validate_rows(rows)

    dataset_path = output_dir / "synthetic_field_proposals.csv"
    source_inventory_path = output_dir / "source_inventory.json"
    metadata_path = output_dir / "data_generation_metadata.json"
    write_csv(rows, dataset_path)
    inventory = build_source_inventory(source_paths, records)
    write_json(inventory, source_inventory_path)
    write_json(
        {
            "generated_at_utc": utc_now(),
            "dataset_name": "Field Proposal Review Risk Model PoC",
            "dataset_type": "synthetic_proxy_label_poc",
            "random_state": RANDOM_STATE,
            "row_count": len(rows),
            "source_raw_row_count": inventory["raw_row_count"],
            "source_deduplicated_row_count": inventory["deduplicated_row_count"],
            "source_duplicate_row_count": inventory["duplicate_row_count"],
            "rows_per_field_type": ROWS_PER_FIELD,
            "positive_rows_per_field_type": POSITIVE_ROWS_PER_FIELD,
            "target_distribution": {"0": 80, "1": 70},
            "feature_columns": list(MODEL_FEATURE_COLUMNS),
            "target_column": TARGET_COLUMN,
            "trace_columns": list(OUTPUT_COLUMNS[:7]),
            "source_inventory": source_inventory_path.name,
            "dataset_file": dataset_path.name,
            "dataset_sha256": sha256_file(dataset_path),
            "generator_sha256": sha256_file(script_path),
            "proxy_label_rule": {
                "formula": (
                    "2*(1-confidence) + 1.5*has_conflict + 1.2*has_negation "
                    "+ 0.35*(mention_count-1) + 1.4*(1-parse_success) "
                    "+ 0.75*no_fill_context + N(0,0.35)"
                ),
                "assignment": "Top 7 proxy risk scores within each field_type are class 1.",
                "no_fill_context_labels": sorted(NO_FILL_LABELS),
            },
            "limitations": [
                "Source conversations are synthetic project fixtures.",
                "needs_review is a deterministic proxy label, not human acceptance/edit/rejection feedback.",
                "confidence is simulated and is not an observed production sLLM confidence.",
                "The dataset is for a small submission PoC and must not be used to claim production performance.",
            ],
        },
        metadata_path,
    )
    print_dataset_summary(rows)
    print(f"Dataset path: {dataset_path}")
    print(f"Dataset SHA-256: {sha256_file(dataset_path)}")


if __name__ == "__main__":
    main()
