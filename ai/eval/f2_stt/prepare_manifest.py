"""Build a reproducible STT evaluation manifest from paired WAV/TXT files."""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PairedSample:
    sample_id: str
    audio_path: Path
    label_path: Path


def _files_by_stem(directory: Path, suffix: str) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for path in sorted(directory.rglob(f"*{suffix}")):
        if path.stem in files:
            raise ValueError(f"중복된 파일 ID가 있습니다: {path.stem}")
        files[path.stem] = path
    return files


def find_pairs(data_dir: Path) -> list[PairedSample]:
    if not data_dir.is_dir():
        raise FileNotFoundError(f"데이터 디렉터리를 찾을 수 없습니다: {data_dir}")

    audio_files = _files_by_stem(data_dir / "audio", ".wav")
    label_files = _files_by_stem(data_dir / "labels", ".txt")

    audio_only = sorted(audio_files.keys() - label_files.keys())
    label_only = sorted(label_files.keys() - audio_files.keys())
    if audio_only or label_only:
        details = []
        if audio_only:
            details.append(f"라벨 없는 음성: {', '.join(audio_only[:10])}")
        if label_only:
            details.append(f"음성 없는 라벨: {', '.join(label_only[:10])}")
        raise ValueError("음성/라벨 짝이 맞지 않습니다. " + " / ".join(details))

    return [
        PairedSample(sample_id, audio_files[sample_id], label_files[sample_id])
        for sample_id in sorted(audio_files)
    ]


def read_reference(path: Path) -> str:
    reference = path.read_text(encoding="utf-8-sig").strip()
    if not reference:
        raise ValueError(f"빈 정답 라벨입니다: {path.name}")
    return reference


def build_manifest(
    *, data_dir: Path, sample_count: int, seed: int, output: Path, force: bool
) -> list[str]:
    pairs = find_pairs(data_dir)
    if len(pairs) < sample_count:
        raise ValueError(f"요청한 {sample_count}개보다 사용 가능한 짝이 적습니다: {len(pairs)}개")
    if output.exists() and not force:
        raise FileExistsError(f"이미 파일이 있습니다: {output} (덮어쓰려면 --force 사용)")

    selected = random.Random(seed).sample(pairs, sample_count)
    selected.sort(key=lambda sample: sample.sample_id)

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output.with_suffix(output.suffix + ".tmp")
    selected_ids: list[str] = []
    try:
        with temporary_output.open("w", encoding="utf-8") as manifest:
            for sample in selected:
                relative_audio = sample.audio_path.relative_to(data_dir).as_posix()
                record = {
                    "id": sample.sample_id,
                    "audio": relative_audio,
                    "reference": read_reference(sample.label_path),
                }
                manifest.write(json.dumps(record, ensure_ascii=False) + "\n")
                selected_ids.append(sample.sample_id)
        temporary_output.replace(output)
    finally:
        temporary_output.unlink(missing_ok=True)

    return selected_ids


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="WAV/TXT 짝에서 평가용 labels.jsonl 생성")
    parser.add_argument(
        "--data-dir",
        type=Path,
        required=True,
        help="audio/와 labels/를 포함하는 로컬 데이터 디렉터리",
    )
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.count <= 0:
        raise SystemExit("--count는 1 이상이어야 합니다.")
    data_dir = args.data_dir.resolve()
    output = args.output.resolve() if args.output else data_dir / "labels.jsonl"
    if not output.is_relative_to(data_dir):
        raise SystemExit("--output은 --data-dir 내부 경로여야 합니다.")
    selected_ids = build_manifest(
        data_dir=data_dir,
        sample_count=args.count,
        seed=args.seed,
        output=output,
        force=args.force,
    )
    print(f"평가 manifest 생성 완료: {output}")
    print(f"선택된 샘플: {len(selected_ids)}개 (seed={args.seed})")


if __name__ == "__main__":
    main()
