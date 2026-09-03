#!/usr/bin/env python3
"""Qwen3-4B를 F2 분류 또는 full-output 데이터로 QLoRA 미세조정한다.

전체 실행 흐름
1. CLI 인자와 YAML 설정을 읽고 입력 파일 및 출력 경로를 검증한다.
2. prompt-completion 형식의 train/validation JSONL을 Hugging Face Dataset으로 읽는다.
3. Qwen 토크나이저와 4bit 양자화된 기반 모델을 GPU에 올린다.
4. 기반 모델은 그대로 두고 LoRA 어댑터만 학습하도록 SFTTrainer를 구성한다.
5. 학습과 검증을 수행하고 어댑터, 토크나이저, 재현 메타데이터를 저장한다.

이 스크립트는 전체 4B 가중치를 다시 학습하지 않는다. QLoRA는 기반 모델을 4bit로
메모리에 올린 뒤 일부 선형 계층에 작은 LoRA 행렬을 추가해 그 행렬만 학습하므로,
일반적인 전체 미세조정보다 필요한 VRAM과 저장 공간이 작다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    """학습에 필요한 경로와 스모크 테스트/재개 옵션을 CLI에서 받는다."""

    parser = argparse.ArgumentParser(description=__doc__)
    # prepare_sft_dataset.py가 만든 prompt/completion JSONL 두 개를 사용한다.
    parser.add_argument("--train-data", type=Path, required=True, help="SFT train JSONL")
    parser.add_argument("--validation-data", type=Path, required=True, help="SFT validation JSONL")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).parent / "configs" / "qwen3-4b-qlora.yaml",
    )
    parser.add_argument(
        "--output-dir", type=Path, required=True, help="어댑터/체크포인트 저장 위치"
    )
    # 실제 전체 학습 전에 --max-samples 8 --max-steps 2처럼 지정하면 모델 로딩부터
    # 저장까지 전체 연결이 정상인지 적은 비용으로 확인할 수 있다.
    parser.add_argument("--max-samples", type=int, help="연결 확인용 split별 최대 건수")
    parser.add_argument("--max-steps", type=int, default=-1, help="연결 확인용 학습 step 제한")
    # 중단된 학습을 checkpoint-N 디렉터리부터 이어서 실행할 때 사용한다.
    parser.add_argument("--resume-from-checkpoint", type=Path)
    return parser.parse_args()


def load_config(path: Path) -> dict[str, Any]:
    """YAML 학습 설정을 읽고 실행 전에 필수 섹션과 필드를 검증한다."""

    # PyYAML은 RunPod 학습 환경에만 필요한 의존성이다. 함수 안에서 import하면
    # 학습 환경이 없는 로컬에서도 train_qlora.py --help는 실행할 수 있다.
    import yaml

    with path.open(encoding="utf-8") as file:
        config = yaml.safe_load(file)
    if not isinstance(config, dict):
        raise ValueError("config는 YAML 객체여야 합니다")

    for section in ("model", "quantization", "lora", "training"):
        if not isinstance(config.get(section), dict):
            raise ValueError(f"config.{section} 객체가 필요합니다")
    # 설정 오타나 누락을 학습 시작 후가 아니라 모델 다운로드 전에 발견하기 위한 목록이다.
    required = {
        "model": {"id", "revision", "max_length"},
        "quantization": {"load_in_4bit", "quant_type", "use_double_quant", "compute_dtype"},
        "lora": {"rank", "alpha", "dropout", "target_modules"},
        "training": {
            "learning_rate",
            "num_train_epochs",
            "per_device_train_batch_size",
            "per_device_eval_batch_size",
            "gradient_accumulation_steps",
            "warmup_ratio",
            "weight_decay",
            "gradient_checkpointing",
            "logging_steps",
            "eval_steps",
            "save_steps",
            "save_total_limit",
            "seed",
        },
    }
    for section, keys in required.items():
        missing = keys - config[section].keys()
        if missing:
            raise ValueError(f"config.{section} 필드 누락: {sorted(missing)}")
    if config["quantization"]["compute_dtype"] not in {"bfloat16", "float16"}:
        raise ValueError("compute_dtype은 bfloat16 또는 float16이어야 합니다")
    if config["quantization"]["load_in_4bit"] is not True:
        raise ValueError("QLoRA 학습에서는 quantization.load_in_4bit가 true여야 합니다")
    if not config["lora"]["target_modules"]:
        raise ValueError("lora.target_modules가 비어 있습니다")
    return config


def sha256(path: Path) -> str:
    """입력 데이터가 어떤 파일이었는지 재현할 수 있도록 SHA-256을 계산한다."""

    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_revision() -> str | None:
    """학습에 사용한 코드 revision을 반환하고 Git 정보가 없으면 None을 반환한다."""

    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def validate_sft_file(path: Path, expected_split: str) -> tuple[set[str], set[str], set[str]]:
    """SFT JSONL의 최소 계약과 split을 확인하고 ID·그룹·과제를 반환한다."""

    ids: set[str] = set()
    groups: set[str] = set()
    tasks: set[str] = set()
    with path.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            sample = json.loads(line)
            if not isinstance(sample, dict):
                raise TypeError(f"{path}:{line_number}: JSON object가 아닙니다")
            required = {"id", "prompt", "completion", "source_group_id", "split"}
            if missing := required - sample.keys():
                raise ValueError(f"{path}:{line_number}: 필수 필드 누락 {sorted(missing)}")
            if sample["split"] != expected_split:
                raise ValueError(f"{path}:{line_number}: split은 {expected_split!r}이어야 합니다")
            if not isinstance(sample["prompt"], list) or not sample["prompt"]:
                raise ValueError(f"{path}:{line_number}: prompt 대화가 비어 있습니다")
            if not isinstance(sample["completion"], list) or not sample["completion"]:
                raise ValueError(f"{path}:{line_number}: completion 대화가 비어 있습니다")
            task = sample.get("task", "classification")
            if task not in {"classification", "full"}:
                raise ValueError(f"{path}:{line_number}: 알 수 없는 task {task!r}")
            sample_id = sample["id"]
            group_id = sample["source_group_id"]
            if not all(isinstance(value, str) and value.strip() for value in (sample_id, group_id)):
                raise ValueError(f"{path}:{line_number}: id 또는 source_group_id가 비어 있습니다")
            if sample_id in ids:
                raise ValueError(f"{path}:{line_number}: 중복 id {sample_id!r}")
            ids.add(sample_id)
            groups.add(group_id)
            tasks.add(task)
    if not ids:
        raise ValueError(f"{path}: 데이터가 없습니다")
    return ids, groups, tasks


def validate_token_lengths(
    datasets_by_split: Any, tokenizer: Any, max_length: int
) -> dict[str, dict[str, int | float]]:
    """Qwen 채팅 템플릿 적용 후 prompt+completion이 잘리지 않는지 검사한다."""

    if max_length < 1:
        raise ValueError("model.max_length는 1 이상이어야 합니다")
    stats: dict[str, dict[str, int | float]] = {}
    overflow: list[tuple[str, str, int]] = []
    for split_name, dataset in datasets_by_split.items():
        lengths: list[int] = []
        for sample in dataset:
            encoded = tokenizer(
                sample["prompt"] + sample["completion"],
                add_special_tokens=False,
            )
            token_ids = encoded["input_ids"]
            length = len(token_ids)
            lengths.append(length)
            if length > max_length:
                overflow.append((split_name, sample["id"], length))
        if not lengths:
            raise ValueError(f"{split_name}: 렌더링된 데이터가 없습니다")
        ordered = sorted(lengths)
        stats[split_name] = {
            "count": len(ordered),
            "minimum": ordered[0],
            "median": float(ordered[len(ordered) // 2]),
            "maximum": ordered[-1],
        }
    if overflow:
        examples = ", ".join(
            f"{split}/{sample_id}={length}" for split, sample_id, length in overflow[:5]
        )
        raise ValueError(
            f"prompt+completion이 model.max_length={max_length}를 초과합니다: {examples}"
        )
    return stats


def main() -> None:
    """데이터 로딩부터 QLoRA 학습, 평가와 어댑터 저장까지 수행한다."""

    # 1. 사용자 입력과 YAML 설정을 먼저 읽는다.
    args = parse_args()
    config = load_config(args.config)
    if args.max_steps == 0 or args.max_steps < -1:
        raise ValueError("max_steps는 -1 또는 1 이상의 정수여야 합니다")

    # 학습을 오래 시작한 뒤 경로 오류를 발견하지 않도록 입력 존재 여부를 먼저 검사한다.
    for path in (args.train_data, args.validation_data):
        if not path.is_file():
            raise FileNotFoundError(path)
    if args.train_data.resolve() == args.validation_data.resolve():
        raise ValueError("train-data와 validation-data는 서로 다른 파일이어야 합니다")
    train_ids, train_groups, train_tasks = validate_sft_file(args.train_data, "train")
    validation_ids, validation_groups, validation_tasks = validate_sft_file(
        args.validation_data, "validation"
    )
    if overlap := train_ids & validation_ids:
        raise ValueError(f"train/validation에 중복 id가 있습니다: {sorted(overlap)[:5]}")
    if overlap := train_groups & validation_groups:
        raise ValueError(
            f"train/validation에 중복 source_group_id가 있습니다: {sorted(overlap)[:5]}"
        )
    if len(train_tasks) != 1 or train_tasks != validation_tasks:
        raise ValueError(
            "train/validation은 동일한 단일 task여야 합니다: "
            f"train={sorted(train_tasks)}, validation={sorted(validation_tasks)}"
        )
    training_task = next(iter(train_tasks))
    if args.resume_from_checkpoint and not args.resume_from_checkpoint.is_dir():
        raise FileNotFoundError(args.resume_from_checkpoint)

    # 실수로 이전 실험의 checkpoint/adapter를 섞거나 덮어쓰지 않게 빈 출력 경로만 허용한다.
    # 단, --resume-from-checkpoint를 명시한 경우에는 기존 출력 경로 사용을 허용한다.
    if args.output_dir.exists() and not args.output_dir.is_dir():
        raise NotADirectoryError(args.output_dir)
    if (
        args.output_dir.exists()
        and any(args.output_dir.iterdir())
        and not args.resume_from_checkpoint
    ):
        raise FileExistsError(
            f"비어 있지 않은 output-dir입니다: {args.output_dir}. 새 경로를 사용하세요."
        )

    # 2. 학습 전용 의존성은 여기서 지연 import한다. 따라서 기본 AI 런타임과 분리된
    # Python 3.12 환경에서도 --help와 설정 검증을 가볍게 수행할 수 있다.
    import torch
    import transformers
    import trl
    from datasets import load_dataset
    from peft import LoraConfig, prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from trl import SFTConfig, SFTTrainer

    # YAML의 각 섹션을 역할별로 분리해 아래 설정 코드에서 사용한다.
    model_config = config["model"]
    quantization = config["quantization"]
    lora = config["lora"]
    training = config["training"]
    # YAML 문자열을 PyTorch가 실제 연산에 사용하는 dtype 객체로 변환한다.
    # bfloat16은 float16보다 표현 범위가 넓어 지원 GPU에서는 학습 안정성이 좋은 편이다.
    dtype = torch.bfloat16 if quantization["compute_dtype"] == "bfloat16" else torch.float16

    # 3. JSONL을 train/validation 두 split으로 읽는다. 각 레코드에는 대화형 prompt와
    # 정답 completion이 들어 있으며, 원본 분류 label 또는 full expected가 이미 반영되어 있다.
    data = load_dataset(
        "json",
        data_files={"train": str(args.train_data), "validation": str(args.validation_data)},
    )
    if args.max_samples is not None:
        if args.max_samples < 1:
            raise ValueError("max_samples는 1 이상이어야 합니다")
        # 스모크 테스트에서는 각 split의 앞부분만 잘라 전체 파이프라인을 빠르게 확인한다.
        data["train"] = data["train"].select(range(min(args.max_samples, len(data["train"]))))
        data["validation"] = data["validation"].select(
            range(min(args.max_samples, len(data["validation"])))
        )

    # 4. 토크나이저는 텍스트 대화를 Qwen이 처리할 token ID로 변환한다.
    tokenizer = AutoTokenizer.from_pretrained(
        model_config["id"], revision=model_config["revision"], use_fast=True
    )
    # 일부 causal LM에는 별도 padding token이 없다. 배치 길이를 맞추기 위해 EOS token을
    # padding에도 사용하고, prompt 뒤에 completion이 이어지도록 오른쪽 padding을 사용한다.
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    # Qwen3는 기본 채팅 템플릿에서 thinking이 켜져 있다. 운영 분류 추론과 동일하게
    # enable_thinking=False로 렌더링한 일반 prompt/completion 문자열로 바꾼다.
    def render_non_thinking(sample: dict[str, Any]) -> dict[str, str]:
        prompt_messages = sample["prompt"]
        completion_messages = sample["completion"]
        prompt_text = tokenizer.apply_chat_template(
            prompt_messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        full_text = tokenizer.apply_chat_template(
            prompt_messages + completion_messages,
            tokenize=False,
            add_generation_prompt=False,
            enable_thinking=False,
        )
        if not full_text.startswith(prompt_text):
            raise ValueError("Qwen chat template에서 completion 경계를 찾을 수 없습니다")
        completion_text = full_text[len(prompt_text) :]
        if not completion_text:
            raise ValueError("렌더링된 completion이 비어 있습니다")
        return {"id": sample["id"], "prompt": prompt_text, "completion": completion_text}

    data = data.map(
        render_non_thinking,
        remove_columns=data["train"].column_names,
        desc="Qwen3 non-thinking chat template 적용",
    )
    token_length_stats = validate_token_lengths(data, tokenizer, int(model_config["max_length"]))
    data = data.remove_columns(["id"])

    # 5. BitsAndBytes 4bit 양자화 설정이다.
    # - NF4: 정규분포 형태의 사전학습 가중치에 적합한 4bit 표현
    # - double quantization: 양자화 상수까지 다시 양자화해 메모리를 추가 절약
    # - compute dtype: 저장은 4bit지만 실제 행렬 연산에 사용할 정밀도
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=bool(quantization["load_in_4bit"]),
        bnb_4bit_quant_type=quantization["quant_type"],
        bnb_4bit_use_double_quant=bool(quantization["use_double_quant"]),
        bnb_4bit_compute_dtype=dtype,
    )
    if not torch.cuda.is_available():
        raise RuntimeError("QLoRA 학습에는 CUDA GPU가 필요합니다")
    if dtype == torch.bfloat16 and not torch.cuda.is_bf16_supported():
        raise RuntimeError("현재 GPU는 bfloat16을 지원하지 않습니다. config를 float16으로 바꾸세요")

    # 기반 Qwen 모델을 4bit로 불러온다. 학습에서는 Accelerate가 현재 프로세스의 GPU에
    # 배치하므로 추론용 device_map="auto"를 사용하지 않는다.
    # 이 기반 가중치 전체를 수정하는 것이 아니라 아래에서 붙일 LoRA 파라미터만 학습한다.
    model = AutoModelForCausalLM.from_pretrained(
        model_config["id"],
        revision=model_config["revision"],
        quantization_config=bnb_config,
        torch_dtype=dtype,
    )
    # KV cache는 생성 속도를 높이지만 학습 및 gradient checkpointing과 충돌할 수 있어 끈다.
    model.config.use_cache = False
    model = prepare_model_for_kbit_training(
        model,
        use_gradient_checkpointing=bool(training["gradient_checkpointing"]),
    )

    # 6. LoRA 어댑터 설정이다.
    # target_modules에 지정한 attention/MLP 선형 계층에 저랭크 행렬을 추가한다.
    # rank가 클수록 표현력과 학습 파라미터 수가 함께 증가하고, alpha는 LoRA 갱신의
    # 스케일을 조절하며 dropout은 작은 데이터셋에서의 과적합을 줄이는 역할을 한다.
    peft_config = LoraConfig(
        r=int(lora["rank"]),
        lora_alpha=int(lora["alpha"]),
        lora_dropout=float(lora["dropout"]),
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=list(lora["target_modules"]),
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # 7. TRL의 지도 미세조정(SFT) 옵션을 구성한다.
    # completion_only_loss=True이므로 system/user prompt 토큰은 정답 손실 계산에서 제외하고
    # assistant가 출력해야 하는 JSON completion 부분만 학습 대상으로 사용한다.
    eval_steps = (
        min(int(training["eval_steps"]), args.max_steps)
        if args.max_steps > 0
        else int(training["eval_steps"])
    )
    save_steps = (
        min(int(training["save_steps"]), args.max_steps)
        if args.max_steps > 0
        else int(training["save_steps"])
    )
    trainer_config = SFTConfig(
        output_dir=str(args.output_dir),
        max_length=int(model_config["max_length"]),
        completion_only_loss=True,
        learning_rate=float(training["learning_rate"]),
        num_train_epochs=float(training["num_train_epochs"]),
        per_device_train_batch_size=int(training["per_device_train_batch_size"]),
        per_device_eval_batch_size=int(training["per_device_eval_batch_size"]),
        # 작은 GPU batch를 여러 번 누적한 뒤 한 번 optimizer를 갱신한다.
        # 유효 batch 크기 = GPU 수 × train batch size × gradient accumulation steps다.
        gradient_accumulation_steps=int(training["gradient_accumulation_steps"]),
        warmup_ratio=float(training["warmup_ratio"]),
        weight_decay=float(training["weight_decay"]),
        gradient_checkpointing=bool(training["gradient_checkpointing"]),
        bf16=dtype == torch.bfloat16,
        fp16=dtype == torch.float16,
        logging_steps=int(training["logging_steps"]),
        # 일정 step마다 validation loss를 계산하고 checkpoint를 저장한다.
        eval_steps=eval_steps,
        eval_strategy="steps",
        save_strategy="steps",
        save_steps=save_steps,
        save_total_limit=int(training["save_total_limit"]),
        # 학습 종료 시 validation loss가 가장 낮았던 checkpoint를 다시 선택한다.
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        # 현재는 WandB 같은 외부 추적 서비스로 데이터나 메타데이터를 전송하지 않는다.
        report_to="none",
        seed=int(training["seed"]),
        max_steps=args.max_steps,
    )
    # SFTTrainer가 데이터 토큰화, forward/backward, 평가, checkpoint 저장을 담당한다.
    # peft_config를 전달했으므로 Trainer는 전체 모델이 아닌 LoRA 파라미터를 학습한다.
    trainer = SFTTrainer(
        model=model,
        args=trainer_config,
        train_dataset=data["train"],
        eval_dataset=data["validation"],
        processing_class=tokenizer,
        peft_config=peft_config,
    )

    # 8. 실제 학습을 시작한다. checkpoint를 전달하면 optimizer/scheduler 상태까지 복원해
    # 이어서 진행하고, 전달하지 않으면 처음부터 학습한다.
    started_at = datetime.now(UTC)
    train_result = trainer.train(
        resume_from_checkpoint=(
            str(args.resume_from_checkpoint) if args.resume_from_checkpoint else None
        )
    )
    # 선택된 최종 모델로 validation split을 한 번 더 평가해 eval_loss를 기록한다.
    evaluation = trainer.evaluate()

    # 9. 전체 Qwen3-4B 가중치가 아니라 학습된 LoRA 어댑터와 토크나이저만 저장한다.
    # 추론할 때는 Qwen/Qwen3-4B 기반 모델에 이 adapter 디렉터리를 결합해야 한다.
    adapter_dir = args.output_dir / "adapter"
    trainer.save_model(str(adapter_dir))
    tokenizer.save_pretrained(adapter_dir)

    # 10. 같은 실험을 재현하고 결과를 비교할 수 있도록 설정, 데이터 체크섬,
    # 라이브러리 버전과 지표를 남긴다. 상담 transcript 원문은 기록하지 않는다.
    metadata = {
        "started_at": started_at.isoformat(),
        "completed_at": datetime.now(UTC).isoformat(),
        "git_revision": git_revision(),
        "config_path": str(args.config.resolve()),
        "config": config,
        "data": {
            "train": {"path": str(args.train_data.resolve()), "sha256": sha256(args.train_data)},
            "validation": {
                "path": str(args.validation_data.resolve()),
                "sha256": sha256(args.validation_data),
            },
        },
        "limits": {"max_samples": args.max_samples, "max_steps": args.max_steps},
        "task": training_task,
        "token_lengths": token_length_stats,
        "metrics": {"train": train_result.metrics, "evaluation": evaluation},
        "versions": {
            "torch": torch.__version__,
            "transformers": transformers.__version__,
            "trl": trl.__version__,
        },
        "resolved_model_revision": getattr(model.config, "_commit_hash", None),
        "adapter_path": str(adapter_dir.resolve()),
    }
    (args.output_dir / "run_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(metadata, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
