#!/usr/bin/env python3
"""Qwen3 후보들을 F2 분류·추출 작업에서 동일한 조건으로 비교한다.

실행 순서
1. models.yaml에서 Qwen3 모델 ID와 공통 생성 설정을 읽는다.
2. 평가용 JSONL에서 STT 텍스트와 사람이 검수한 정답을 읽는다.
3. Qwen3 모델을 한 번에 하나씩 로드해 모든 사례를 추론한다.
4. 분류·필드 추출·장부 불일치·근거·지연시간 지표를 계산한다.
5. 모델별 상세 예측과 전체 비교용 summary.json을 저장한다.

네 모델을 동시에 GPU에 올리는 코드가 아니다. 모델 하나의 평가가 끝나면 메모리에서
제거하고 다음 모델을 로드하므로, 모델 목록 중 가장 큰 모델 하나가 들어갈 VRAM이 필요하다.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import torch
import yaml
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

# 네 모델에 동일하게 적용하는 F2 분석 규칙과 JSON 출력 계약이다.
# 모델마다 프롬프트가 달라지면 크기에 따른 성능을 공정하게 비교할 수 없으므로
# 모든 후보가 이 프롬프트를 공통으로 사용한다.
SYSTEM_PROMPT = """당신은 부동산 상담 메모 분석기입니다.
입력으로 STT 상담 텍스트와 현재 장부 종류만 받습니다.

반드시 다음 규칙을 지키세요.
- 상담 유형은 매도의뢰, 매수문의, 공동중개, 단순문의 중 하나로 분류합니다.
- 매물장에서 매수문의이거나 구입장에서 매도의뢰이면 ledger_mismatch를 true로 둡니다.
- ledger_mismatch가 true이면 fields와 evidence는 빈 객체로 둡니다.
- 원문에서 명확히 확인된 값만 fields에 넣습니다.
- 불명확한 숫자, 날짜, 동, 호 또는 충돌하는 값은 확정하지 말고 uncertainties에 적습니다.
- 기존 장부 값을 추측하거나 자동으로 덮어쓰지 않습니다.
- 각 fields 값에는 원문 그대로의 evidence 문장을 제공합니다.
- 설명이나 마크다운 없이 JSON 객체 하나만 출력합니다.

출력 형식:
{
  "consultation_type": "매도의뢰|매수문의|공동중개|단순문의",
  "ledger_mismatch": false,
  "fields": {"필드명": "값"},
  "evidence": {"필드명": "원문 근거"},
  "uncertainties": ["불명확하거나 충돌한 내용"],
  "summary": "상담 로그 초안"
}"""


@dataclass(frozen=True)
class ModelSpec:
    """models.yaml의 모델 한 개를 Python 객체로 표현한다.

    model_id는 Hugging Face에서 실제 모델과 토크나이저를 찾는 이름이다.
    label은 결과 파일명에 사용하는 짧은 이름이다.
    """

    model_id: str
    label: str


def parse_args() -> argparse.Namespace:
    """데이터셋, 비교 모델, 양자화와 결과 저장 위치를 CLI 인자로 받는다."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True, help="평가 JSONL 경로")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).with_name("models.yaml"),
        help="모델 및 공통 생성 설정 YAML",
    )
    parser.add_argument(
        "--models",
        nargs="+",
        help="실행할 모델 ID 목록(기본: 설정의 전체 모델)",
    )
    parser.add_argument(
        "--quantization",
        choices=("none", "4bit"),
        default="none",
        help="모든 후보에 동일하게 적용할 양자화",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).with_name("results"),
        help="실행 결과 루트",
    )
    parser.add_argument("--limit", type=int, help="구조 확인용 최대 사례 수")
    return parser.parse_args()


def load_config(path: Path) -> dict[str, Any]:
    """models.yaml을 읽어 모델 후보와 공통 생성 설정을 반환한다.

    예를 들어 models[0]["id"]에는 ``Qwen/Qwen3-0.6B``가 들어 있고,
    generation에는 입력 토큰 상한, 출력 토큰 상한과 thinking 설정이 들어 있다.
    """

    with path.open(encoding="utf-8") as file:
        config = yaml.safe_load(file)
    if not isinstance(config, dict):
        raise ValueError("config must be a YAML object")
    return config


def load_dataset(path: Path, limit: int | None) -> list[dict[str, Any]]:
    """평가 JSONL을 한 줄씩 읽고 필수 필드가 있는지 검사한다.

    각 줄은 하나의 상담 사례다. 모델 입력에는 transcript와 ledger_type을 사용하고,
    expected는 모델 예측과 비교할 정답으로만 사용한다. expected를 프롬프트에 넣지 않는다.
    """

    required = {"sample_id", "transcript", "ledger_type", "expected"}
    samples: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            # JSONL은 파일 전체가 배열이 아니라 한 줄마다 독립된 JSON 객체다.
            sample = json.loads(line)
            missing = required - sample.keys()
            if missing:
                raise ValueError(f"{path}:{line_number}: missing {sorted(missing)}")
            if not isinstance(sample["expected"], dict):
                raise ValueError(f"{path}:{line_number}: expected must be an object")
            samples.append(sample)
            if limit is not None and len(samples) >= limit:
                break
    if not samples:
        raise ValueError(f"no samples found in {path}")
    return samples


def select_models(config: dict[str, Any], requested: list[str] | None) -> list[ModelSpec]:
    """models.yaml의 모델 목록에서 이번에 실행할 후보를 선택한다.

    --models 옵션이 없으면 등록된 네 모델을 모두 반환한다. 옵션이 있으면 요청된 모델만
    반환하며, models.yaml에 없는 ID가 들어오면 오타로 보고 실행을 중단한다.
    """

    # YAML의 {id, label} 딕셔너리를 ModelSpec 객체로 변환한다.
    # 이때 id가 이후 run_model()의 spec.model_id로 전달된다.
    specs = [ModelSpec(item["id"], item["label"]) for item in config["models"]]
    if requested is None:
        return specs
    by_id = {spec.model_id: spec for spec in specs}
    unknown = sorted(set(requested) - by_id.keys())
    if unknown:
        raise ValueError(f"models not found in config: {unknown}")
    return [by_id[model_id] for model_id in requested]


def model_load_kwargs(quantization: str) -> dict[str, Any]:
    """from_pretrained()에 넘길 장치 배치와 양자화 옵션을 만든다.

    device_map="auto"는 Transformers/Accelerate가 사용 가능한 GPU와 CPU에 모델을
    자동 배치하게 한다. torch_dtype="auto"는 체크포인트에 적합한 자료형을 선택한다.
    --quantization 4bit를 사용하면 모든 후보에 같은 NF4 설정을 적용한다.
    """

    kwargs: dict[str, Any] = {"device_map": "auto", "torch_dtype": "auto"}
    if quantization == "4bit":
        # bitsandbytes 4비트 추론은 현재 평가 구성에서 CUDA가 필요하다.
        if not torch.cuda.is_available():
            raise RuntimeError("4bit evaluation requires CUDA and bitsandbytes")
        # NF4는 신경망 가중치 분포에 맞춘 4비트 형식이다. double quantization은
        # 양자화에 필요한 상수까지 다시 압축해 VRAM 사용량을 추가로 줄인다.
        kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
        )
    return kwargs


def build_user_prompt(sample: dict[str, Any]) -> str:
    """현재 장부 종류와 STT 결과만 모델의 사용자 입력으로 만든다.

    평가 정답 expected가 입력에 섞이면 모델이 답을 미리 보게 되므로 포함하지 않는다.
    """

    return (
        f"현재 장부 종류: {sample['ledger_type']}\n"
        f"STT 상담 텍스트:\n{sample['transcript']}"
    )


def extract_json(text: str) -> dict[str, Any]:
    """모델 응답에서 JSON 객체를 복구한다.

    정상적인 JSON 응답을 우선 처리한다. 모델이 코드 블록이나 짧은 설명을 붙인 경우에는
    첫 번째 여는 중괄호부터 마지막 닫는 중괄호까지 다시 파싱한다.
    """

    # 1차 처리: 응답 앞뒤 공백을 제거한다.
    candidate = text.strip()

    # 모델이 요청과 달리 ```json ... ``` 코드 블록을 붙인 경우 내부 내용만 꺼낸다.
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", candidate, flags=re.DOTALL)
    if fenced:
        candidate = fenced.group(1)
    # 가장 정상적인 경우인 '응답 전체가 JSON 객체'인 형태를 먼저 파싱한다.
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        # 모델이 JSON 앞뒤에 설명을 붙였다면 첫 번째 {부터 마지막 }까지 다시 파싱한다.
        # 이 방법으로도 실패하면 run_model()에서 오류 사례로 기록한다.
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start < 0 or end <= start:
            raise
        value = json.loads(candidate[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("model output is not a JSON object")
    return value


def normalize_value(value: Any) -> str:
    """같은 값의 단순 표기 차이를 줄이기 위해 공백·쉼표·원 표기를 제거한다.

    예: ``1,200,000원``과 ``1200000``을 같은 값으로 비교한다. 다만 ``12억``을
    ``1200000000``으로 환산하는 의미 기반 정규화는 수행하지 않는다.
    """

    return re.sub(r"[\s,원]", "", str(value)).casefold()


def field_pairs(fields: Any) -> set[tuple[str, str]]:
    """필드 딕셔너리를 (필드명, 정규화한 값) 집합으로 변환한다.

    필드명과 값이 모두 일치해야 정답이다. 집합으로 변환하면 교집합은 TP,
    예측에만 있는 값은 FP, 정답에만 있는 값은 FN으로 계산할 수 있다.
    """

    if not isinstance(fields, dict):
        return set()
    return {(str(key), normalize_value(value)) for key, value in fields.items()}


def count_evidence_violations(prediction: dict[str, Any], transcript: str) -> int:
    """모델이 제시한 근거 문장이 실제 STT 원문에 없는 횟수를 센다.

    fields의 각 키에는 같은 키의 evidence가 있어야 한다. 공백 차이는 허용하지만,
    evidence 문구가 transcript에 그대로 존재하지 않으면 근거 위반으로 처리한다.
    """

    fields = prediction.get("fields", {})
    evidence = prediction.get("evidence", {})
    if not isinstance(fields, dict):
        return 0
    if not isinstance(evidence, dict):
        return len(fields)
    normalized_transcript = re.sub(r"\s+", "", transcript)
    violations = 0
    for key in fields:
        cited = evidence.get(key)
        if not isinstance(cited, str) or re.sub(r"\s+", "", cited) not in normalized_transcript:
            violations += 1
    return violations


def safe_divide(numerator: int, denominator: int) -> float:
    """평가 대상이 하나도 없을 때 0으로 나누는 오류를 방지한다."""

    return numerator / denominator if denominator else 0.0


def percentile(values: list[float], fraction: float) -> float | None:
    """최근접 순위 방식으로 지연시간 백분위 값을 계산한다."""

    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * fraction) - 1)
    return ordered[index]


def calculate_metrics(
    rows: list[dict[str, Any]], allowed_types: list[str]
) -> dict[str, Any]:
    """한 모델의 모든 사례를 모아 최종 비교 지표를 계산한다.

    분류는 네 상담 유형의 클래스별 F1과 Macro F1을 계산한다. 필드 추출은 모든 사례의
    TP·FP·FN을 합산해 Precision·Recall·F1을 계산한다. JSON 파싱 실패는 숨기지 않고
    json_parse_rate에서 실패로 반영한다.
    """

    # JSON 파싱 실패 사례도 전체 표본 수에 남겨 파싱 성공률에 반영한다.
    parsed = [row for row in rows if row["prediction"] is not None]
    # 분류용 카운터
    # TP: 정답과 예측이 모두 해당 클래스
    # FP: 정답은 다른 클래스인데 해당 클래스로 잘못 예측
    # FN: 정답은 해당 클래스인데 다른 클래스로 예측
    true_positive: Counter[str] = Counter()
    false_positive: Counter[str] = Counter()
    false_negative: Counter[str] = Counter()
    mismatch_correct = 0
    field_tp = field_fp = field_fn = unsupported_fields = 0
    evidence_grounding_violations = 0

    for row in parsed:
        expected = row["expected"]
        prediction = row["prediction"]
        expected_class = expected.get("consultation_type")
        predicted_class = prediction.get("consultation_type")
        # 클래스별 TP·FP·FN을 센 뒤 아래에서 Macro F1을 계산한다.
        for label in allowed_types:
            if expected_class == label and predicted_class == label:
                true_positive[label] += 1
            elif expected_class != label and predicted_class == label:
                false_positive[label] += 1
            elif expected_class == label and predicted_class != label:
                false_negative[label] += 1

        if prediction.get("ledger_mismatch") is expected.get("ledger_mismatch"):
            mismatch_correct += 1

        # 필드명과 정규화된 값이 모두 일치해야 올바른 추출로 인정한다.
        expected_fields = field_pairs(expected.get("fields", {}))
        predicted_fields = field_pairs(prediction.get("fields", {}))
        # 교집합은 정확한 필드, 예측 차집합은 잘못 제안한 필드,
        # 정답 차집합은 모델이 추출하지 못한 필드다.
        field_tp += len(expected_fields & predicted_fields)
        field_fp += len(predicted_fields - expected_fields)
        field_fn += len(expected_fields - predicted_fields)
        evidence_grounding_violations += row["evidence_grounding_violations"]
        # 장부가 맞지 않을 때 fields를 제안하면 금지 동작으로 집계한다.
        if expected.get("ledger_mismatch") is True:
            unsupported_fields += len(predicted_fields)

    class_f1: dict[str, float] = {}
    for label in allowed_types:
        precision = safe_divide(true_positive[label], true_positive[label] + false_positive[label])
        recall = safe_divide(true_positive[label], true_positive[label] + false_negative[label])
        class_f1[label] = safe_divide(2 * precision * recall, precision + recall)

    # Precision: 모델이 제안한 필드 중 맞은 비율
    # Recall: 정답 필드 중 모델이 찾아낸 비율
    field_precision = safe_divide(field_tp, field_tp + field_fp)
    field_recall = safe_divide(field_tp, field_tp + field_fn)
    # 정상적으로 끝난 사례만 평균/p95 추론 시간에 포함한다.
    # 실패 사례 자체는 각 JSONL의 error와 json_parse_rate에 남는다.
    latencies = [row["latency_seconds"] for row in rows if row["error"] is None]
    class_correct = sum(
        row["prediction"].get("consultation_type") == row["expected"].get("consultation_type")
        for row in parsed
    )

    return {
        "samples": len(rows),
        "json_parse_rate": safe_divide(len(parsed), len(rows)),
        "classification_accuracy": safe_divide(class_correct, len(parsed)),
        "classification_macro_f1": statistics.fmean(class_f1.values()) if class_f1 else 0.0,
        "classification_f1_by_class": class_f1,
        "ledger_mismatch_accuracy": safe_divide(mismatch_correct, len(parsed)),
        "field_precision": field_precision,
        "field_recall": field_recall,
        "field_f1": safe_divide(2 * field_precision * field_recall, field_precision + field_recall),
        "evidence_grounding_violations": evidence_grounding_violations,
        "unsupported_field_proposals_on_mismatch": unsupported_fields,
        "mean_latency_seconds": statistics.fmean(latencies) if latencies else None,
        "p95_latency_seconds": percentile(latencies, 0.95),
    }


def run_model(
    spec: ModelSpec,
    samples: list[dict[str, Any]],
    generation: dict[str, Any],
    quantization: str,
    output_path: Path,
    allowed_types: list[str],
) -> dict[str, Any]:
    """Qwen 모델 하나를 불러와 모든 평가 사례를 실행한다.

    spec.model_id에는 models.yaml에서 읽은 ``Qwen/Qwen3-0.6B`` 같은 ID가 들어온다.
    이 ID를 from_pretrained()에 전달하면 토크나이저와 모델 가중치가 로드된다.
    최초 실행은 Hugging Face에서 파일을 내려받고 이후에는 로컬 캐시를 사용한다.
    모델 파일만 다운로드하는 것이며 외부 추론 API로 상담 문장을 보내지 않는다.
    """

    # 이전 후보가 사용한 CUDA 메모리를 비우고 최대 사용량 측정을 시작한다.
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()

    # 모델 로딩 시간 측정을 시작한다. 이 시간에는 최초 다운로드 시간이 포함될 수 있으므로
    # 순수 로딩 속도를 비교할 때는 모든 모델 다운로드를 완료한 뒤 다시 실행하는 것이 좋다.
    load_started = time.perf_counter()

    # 1. spec.model_id에 맞는 토크나이저를 자동 선택한다.
    # Qwen 전용 클래스를 직접 지정하지 않아도 AutoTokenizer가 config를 보고 결정한다.
    tokenizer = AutoTokenizer.from_pretrained(spec.model_id)

    # 2. 실제 Qwen 가중치를 다운로드/캐시에서 읽어 메모리에 올린다.
    # AutoModelForCausalLM은 config.json의 model_type을 확인해 내부적으로 적절한
    # Qwen CausalLM 클래스를 선택한다. 따라서 코드에 Qwen3ForCausalLM 이름이 없어도 된다.
    model = AutoModelForCausalLM.from_pretrained(
        spec.model_id, **model_load_kwargs(quantization)
    )

    # Dropout 같은 학습 전용 동작을 끄고 평가 모드로 전환한다.
    model.eval()
    load_seconds = time.perf_counter() - load_started

    # 입력 토큰 텐서를 모델과 같은 장치(CPU 또는 GPU)로 이동하기 위해 장치를 확인한다.
    model_device = next(model.parameters()).device
    rows: list[dict[str, Any]] = []

    with output_path.open("w", encoding="utf-8") as output_file:
        for sample in samples:
            # 3. 모든 후보에 같은 시스템 프롬프트와 사용자 입력을 적용한다.
            # 모델마다 프롬프트를 다르게 하면 모델 크기에 따른 공정한 비교가 어려워진다.
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(sample)},
            ]
            # 4. Qwen이 학습할 때 사용한 채팅 형식에 맞춰 system/user 메시지를 조립한다.
            # add_generation_prompt=True는 assistant가 답변을 시작할 위치를 표시한다.
            prompt = tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=bool(generation["enable_thinking"]),
            )
            # 5. 문자열 프롬프트를 모델이 처리할 정수 토큰 ID 텐서로 변환한다.
            # 너무 긴 입력은 models.yaml의 공통 토큰 상한으로 모든 모델에서 동일하게 자른다.
            encoded = tokenizer(
                prompt,
                return_tensors="pt",
                truncation=True,
                max_length=int(generation["max_input_tokens"]),
            ).to(model_device)
            # 토큰화 이후부터 생성 및 JSON 파싱 완료까지를 사례별 지연시간으로 측정한다.
            started = time.perf_counter()
            prediction: dict[str, Any] | None = None
            raw_output = ""
            error: str | None = None
            try:
                # 6. gradient를 만들지 않는 순수 추론 모드로 답변 토큰을 생성한다.
                # 학습 그래프를 만들지 않기 때문에 VRAM과 연산량을 줄일 수 있다.
                with torch.inference_mode():
                    generated = model.generate(
                        **encoded,
                        max_new_tokens=int(generation["max_new_tokens"]),
                        do_sample=bool(generation["do_sample"]),
                        pad_token_id=tokenizer.eos_token_id,
                    )
                # generate() 결과에는 입력 토큰도 함께 들어 있다. 입력 부분을 잘라내고
                # 모델이 새로 만든 답변 토큰만 사람이 읽을 수 있는 문자열로 변환한다.
                new_tokens = generated[0, encoded["input_ids"].shape[1] :]
                raw_output = tokenizer.decode(new_tokens, skip_special_tokens=True)
                prediction = extract_json(raw_output)
            except Exception as exc:
                # 실패 사례도 결과에 남겨 오류율과 재현성을 확인한다.
                error = f"{type(exc).__name__}: {exc}"
            latency = time.perf_counter() - started
            # 7. 한 사례의 정답, 예측, 근거 위반, 시간과 오류를 결과 행으로 만든다.
            # transcript 원문 자체는 결과에 다시 쓰지 않지만, raw_output과 expected에도
            # 민감정보가 포함될 수 있으므로 results/는 Git에서 제외한다.
            row = {
                "sample_id": sample["sample_id"],
                "ledger_type": sample["ledger_type"],
                "expected": sample["expected"],
                "prediction": prediction,
                "raw_output": raw_output,
                "evidence_grounding_violations": (
                    count_evidence_violations(prediction, sample["transcript"])
                    if prediction is not None
                    else 0
                ),
                "latency_seconds": latency,
                "error": error,
            }
            rows.append(row)
            output_file.write(json.dumps(row, ensure_ascii=False) + "\n")

    # 8. 모든 사례가 끝나면 모델 하나의 종합 지표를 계산한다.
    metrics = calculate_metrics(rows, allowed_types)
    metrics.update(
        {
            "model_id": spec.model_id,
            "label": spec.label,
            "load_seconds": load_seconds,
            "peak_cuda_memory_bytes": (
                torch.cuda.max_memory_allocated() if torch.cuda.is_available() else None
            ),
        }
    )
    # 9. 다음 후보를 올리기 전에 현재 모델과 토크나이저 참조를 제거한다.
    # CUDA 캐시도 비워 네 모델이 동시에 GPU 메모리를 점유하지 않게 한다.
    del model
    del tokenizer
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return metrics


def main() -> None:
    """설정과 데이터를 읽고 모델 4개를 순차적으로 평가하는 진입점."""

    # 1. CLI 옵션을 읽는다. --config를 생략하면 evaluate.py 옆 models.yaml을 사용한다.
    args = parse_args()

    # 2. models.yaml과 평가 JSONL을 읽는다.
    config = load_config(args.config)
    samples = load_dataset(args.dataset, args.limit)

    # 3. models.yaml의 네 후보를 ModelSpec 목록으로 만든다.
    # --models를 지정했다면 그중 요청된 모델만 남는다.
    specs = select_models(config, args.models)
    generation = config["generation"]
    allowed_types = config["evaluation"]["allowed_consultation_types"]
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = args.output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    # 4. 모델을 하나씩 run_model()에 전달한다.
    # 예: 0.6B 로드→200개 평가→해제→1.7B 로드→200개 평가→해제→...
    summaries: list[dict[str, Any]] = []
    for spec in specs:
        # label은 qwen3-0.6b 같은 값이며 모델별 JSONL 파일명에 사용한다.
        output_path = run_dir / f"{spec.label}.jsonl"
        summaries.append(
            run_model(
                spec,
                samples,
                generation,
                args.quantization,
                output_path,
                allowed_types,
            )
        )

    # 5. 네 모델의 요약 지표와 공통 실행 조건을 summary.json으로 저장한다.
    # 데이터 경로와 생성 설정을 함께 남겨 같은 조건으로 다시 실행할 수 있게 한다.
    summary = {
        "run_id": run_id,
        "dataset": str(args.dataset.resolve()),
        "sample_count": len(samples),
        "quantization": args.quantization,
        "generation": generation,
        "models": summaries,
    }
    with (run_dir / "summary.json").open("w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
