"""Evaluate multiple faster-whisper model IDs on one fixed F2 STT manifest."""

from __future__ import annotations

import argparse
import csv
import gc
import json
import re
import time
import unicodedata
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence


DEFAULT_RESULTS_DIR = Path(__file__).resolve().parent / "results"


@dataclass(frozen=True)
class EvaluationSample:
    sample_id: str
    audio_path: Path
    reference: str
    duration_seconds: float


@dataclass(frozen=True)
class ErrorRate:
    edits: int
    reference_units: int

    @property
    def rate(self) -> float:
        return self.edits / self.reference_units if self.reference_units else 0.0


class Transcriber(Protocol):
    def transcribe(self, audio_path: Path) -> str: ...


class FasterWhisperTranscriber:
    def __init__(
        self,
        model_id: str,
        *,
        device: str,
        compute_type: str,
        language: str,
        beam_size: int,
    ) -> None:
        try:
            from faster_whisper import WhisperModel
        except ImportError as error:
            raise RuntimeError(
                "faster-whisper가 설치되어 있지 않습니다. README의 실행 방법을 확인하세요."
            ) from error

        self._model = WhisperModel(model_id, device=device, compute_type=compute_type)
        self._language = language
        self._beam_size = beam_size

    def transcribe(self, audio_path: Path) -> str:
        segments, _ = self._model.transcribe(
            str(audio_path),
            language=self._language,
            task="transcribe",
            beam_size=self._beam_size,
            vad_filter=False,
            condition_on_previous_text=False,
        )
        return " ".join(segment.text.strip() for segment in segments if segment.text.strip())


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).lower()
    normalized = "".join(
        " " if unicodedata.category(character).startswith("P") else character
        for character in normalized
    )
    return re.sub(r"\s+", " ", normalized).strip()


def levenshtein_distance(reference: Sequence[str], hypothesis: Sequence[str]) -> int:
    if len(reference) < len(hypothesis):
        reference, hypothesis = hypothesis, reference
    previous = list(range(len(hypothesis) + 1))
    for reference_index, reference_unit in enumerate(reference, start=1):
        current = [reference_index]
        for hypothesis_index, hypothesis_unit in enumerate(hypothesis, start=1):
            insertion = current[hypothesis_index - 1] + 1
            deletion = previous[hypothesis_index] + 1
            substitution = previous[hypothesis_index - 1] + (
                reference_unit != hypothesis_unit
            )
            current.append(min(insertion, deletion, substitution))
        previous = current
    return previous[-1]


def error_rate(reference: Sequence[str], hypothesis: Sequence[str]) -> ErrorRate:
    if not reference:
        raise ValueError("정규화 후 정답이 비어 있습니다.")
    return ErrorRate(levenshtein_distance(reference, hypothesis), len(reference))


def calculate_metrics(reference: str, hypothesis: str) -> tuple[ErrorRate, ErrorRate]:
    normalized_reference = normalize_text(reference)
    normalized_hypothesis = normalize_text(hypothesis)
    character_reference = list(normalized_reference.replace(" ", ""))
    character_hypothesis = list(normalized_hypothesis.replace(" ", ""))
    word_reference = normalized_reference.split()
    word_hypothesis = normalized_hypothesis.split()
    return (
        error_rate(character_reference, character_hypothesis),
        error_rate(word_reference, word_hypothesis),
    )


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as audio:
        frame_rate = audio.getframerate()
        if frame_rate <= 0:
            raise ValueError(f"잘못된 WAV sample rate입니다: {path}")
        duration_seconds = audio.getnframes() / frame_rate
        if duration_seconds <= 0:
            raise ValueError(f"빈 WAV 파일입니다: {path}")
        return duration_seconds


def load_manifest(manifest_path: Path) -> list[EvaluationSample]:
    manifest_path = manifest_path.resolve()
    if not manifest_path.is_file():
        raise FileNotFoundError(f"평가 manifest를 찾을 수 없습니다: {manifest_path}")

    dataset_root = manifest_path.parent
    samples: list[EvaluationSample] = []
    seen_ids: set[str] = set()
    with manifest_path.open(encoding="utf-8") as manifest:
        for line_number, line in enumerate(manifest, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            sample_id = str(record["id"])
            if sample_id in seen_ids:
                raise ValueError(f"중복된 샘플 ID입니다: {sample_id}")
            audio_path = (dataset_root / record["audio"]).resolve()
            if not audio_path.is_relative_to(dataset_root):
                raise ValueError(f"manifest 디렉터리 밖의 음성 경로입니다: {record['audio']}")
            if not audio_path.is_file():
                raise FileNotFoundError(f"음성 파일을 찾을 수 없습니다: {audio_path}")
            reference = str(record["reference"]).strip()
            if not reference:
                raise ValueError(f"{line_number}번째 정답이 비어 있습니다.")
            samples.append(
                EvaluationSample(sample_id, audio_path, reference, wav_duration(audio_path))
            )
            seen_ids.add(sample_id)
    if not samples:
        raise ValueError("평가 manifest에 샘플이 없습니다.")
    return samples


def safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_") or "model"


def evaluate_model(
    *,
    model_id: str,
    transcriber: Transcriber,
    samples: list[EvaluationSample],
    output_path: Path,
    load_seconds: float,
) -> dict[str, object]:
    total_character_edits = 0
    total_reference_characters = 0
    total_word_edits = 0
    total_reference_words = 0
    total_latency = 0.0
    total_audio_seconds = 0.0
    success_count = 0
    error_count = 0

    with output_path.open("w", encoding="utf-8") as predictions:
        for sample in samples:
            started_at = time.perf_counter()
            try:
                hypothesis = transcriber.transcribe(sample.audio_path)
                latency_seconds = time.perf_counter() - started_at
                cer, wer = calculate_metrics(sample.reference, hypothesis)
                record = {
                    "id": sample.sample_id,
                    "audio": sample.audio_path.name,
                    "reference": sample.reference,
                    "hypothesis": hypothesis,
                    "cer": cer.rate,
                    "wer": wer.rate,
                    "audio_seconds": sample.duration_seconds,
                    "latency_seconds": latency_seconds,
                    "rtf": latency_seconds / sample.duration_seconds,
                    "status": "success",
                }
                total_character_edits += cer.edits
                total_reference_characters += cer.reference_units
                total_word_edits += wer.edits
                total_reference_words += wer.reference_units
                total_latency += latency_seconds
                total_audio_seconds += sample.duration_seconds
                success_count += 1
            except Exception as error:  # 한 샘플 실패가 전체 모델 평가를 중단하지 않게 한다.
                record = {
                    "id": sample.sample_id,
                    "audio": sample.audio_path.name,
                    "status": "error",
                    "error_type": type(error).__name__,
                    "error": str(error),
                }
                error_count += 1
            predictions.write(json.dumps(record, ensure_ascii=False) + "\n")

    return {
        "model": model_id,
        "sample_count": len(samples),
        "success_count": success_count,
        "error_count": error_count,
        "cer_successful": (
            total_character_edits / total_reference_characters
            if total_reference_characters
            else ""
        ),
        "wer_successful": (
            total_word_edits / total_reference_words if total_reference_words else ""
        ),
        "average_latency_seconds": total_latency / success_count if success_count else "",
        "total_audio_seconds": total_audio_seconds,
        "total_inference_seconds": total_latency,
        "rtf_successful": total_latency / total_audio_seconds if total_audio_seconds else "",
        "model_load_seconds": load_seconds,
        "predictions_file": output_path.name,
    }


def write_summary(rows: list[dict[str, object]], output_path: Path) -> None:
    if not rows:
        return
    with output_path.open("w", encoding="utf-8", newline="") as summary:
        writer = csv.DictWriter(summary, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="동일한 F2 음성으로 여러 STT 모델 평가")
    parser.add_argument("--models", nargs="+", required=True, help="faster-whisper 모델 ID")
    parser.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="평가 JSONL 경로. audio 값은 이 파일이 있는 디렉터리를 기준으로 해석합니다.",
    )
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--device", default="cpu", choices=("cpu", "cuda", "auto"))
    parser.add_argument("--compute-type", default="int8")
    parser.add_argument("--language", default="ko")
    parser.add_argument("--beam-size", type=int, default=5)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.beam_size <= 0:
        raise SystemExit("--beam-size는 1 이상이어야 합니다.")
    samples = load_manifest(args.manifest)
    results_dir = args.results_dir.resolve()
    results_dir.mkdir(parents=True, exist_ok=True)

    summaries: list[dict[str, object]] = []
    for model_id in args.models:
        print(f"[{model_id}] 모델 로딩")
        load_started_at = time.perf_counter()
        transcriber = FasterWhisperTranscriber(
            model_id,
            device=args.device,
            compute_type=args.compute_type,
            language=args.language,
            beam_size=args.beam_size,
        )
        load_seconds = time.perf_counter() - load_started_at
        output_path = results_dir / f"{safe_filename(model_id)}_predictions.jsonl"
        print(f"[{model_id}] {len(samples)}개 평가")
        summaries.append(
            evaluate_model(
                model_id=model_id,
                transcriber=transcriber,
                samples=samples,
                output_path=output_path,
                load_seconds=load_seconds,
            )
        )
        del transcriber
        gc.collect()

    summary_path = results_dir / "summary.csv"
    write_summary(summaries, summary_path)
    print(f"평가 완료: {summary_path}")


if __name__ == "__main__":
    main()
