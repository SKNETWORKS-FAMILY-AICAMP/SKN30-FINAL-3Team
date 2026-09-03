# F2 분류·full-output QLoRA 학습

`Qwen/Qwen3-4B`를 상담 유형 분류 또는 F2 전체 구조화 출력으로 미세조정하는
오프라인 도구다. `classification`은 상담 유형만 출력하고, `full`은 현재
장부 종류와 STT 텍스트를 받아 상담 유형, 장부 불일치, 필드, 원문 근거,
불확실성과 상담 로그 초안의 6-key JSON을 출력한다. 운영 승격 대상은 검수된
full-output 정답으로 학습·평가한 adapter다.

모델 ID와 QLoRA 설정은 실험 기본값일 뿐, 승인된 운영 모델 결정이 아니다.
정식 재현 실험 전에는 설정의 `revision: main`을 Hugging Face의 불변 commit hash로 바꾼다.
실행 시 실제로 확인된 모델 revision도 `run_metadata.json`에 기록된다.

## 폴더 역할

```text
ai/training/f2_sLLM/
├── configs/qwen3-4b-qlora.yaml       # 분류 실험 설정
├── configs/qwen3-4b-qlora-full.yaml  # full-output 실험 설정
├── prepare_sft_dataset.py       # 분할 데이터를 채팅 학습 형식으로 변환
├── train_qlora.py               # QLoRA 학습 및 어댑터 저장
├── requirements.txt             # RunPod 학습 전용 의존성
└── outputs/                     # 로컬 산출물(Git 제외)
```

데이터 분할은 Data 모듈이 담당한다. 동일 `source_group_id`는 항상 같은 split에
배치되어야 하며, test는 SFT 변환 단계에서 차단된다. full-output은
`sample_id`, `ledger_type`, `expected`를 보존한 분할 산출물을 사용한다.

## 1. 데이터 준비

현재 `data/f2_llm/working/`의 파일은 검수·발행 전 초안이다. 정식 모델 학습에는
manifest·privacy 문서와 검수를 갖춘 `data/f2_llm/releases/<version>/` 입력을 사용한다.
분할은 `data/scripts/split_f2_sllm_dataset.py`가 분류 스키마(`scenario_id`)와
full-output 스키마(`sample_id`, `ledger_type`, `expected`)를 모두 처리한다. Data 모듈에서
분할한 결과를 받은 뒤 아래 SFT 변환을 실행한다. 분할 보고서의 장부·셀 분포와
`ledger_mismatch_count`로 특정 split에 쏠림이 없는지 먼저 확인한다.

학습에는 train과 validation만 변환한다. test는 최종 평가 전까지 열어보거나 변환하지 않는다.

```bash
python ai/training/f2_sLLM/prepare_sft_dataset.py \
  --task full \
  --input data/f2_llm/releases/<version>/train.jsonl \
  --output /workspace/datasets/f2-<version>/sft-train.jsonl

python ai/training/f2_sLLM/prepare_sft_dataset.py \
  --task full \
  --input data/f2_llm/releases/<version>/validation.jsonl \
  --output /workspace/datasets/f2-<version>/sft-validation.jsonl
```

## 2. RunPod 학습 환경

RunPod SSH 터미널에서 저장소 루트를 기준으로 실행한다. 학습 환경은 운영 AI와 평가 환경에서
분리한다. Python 3.12는 현재 학습 도구용 실행 예시이며 프로젝트 공통 버전 결정은 아니다.

```bash
uv venv --python 3.12 ai/training/f2_sLLM/.venv
uv pip install \
  --python ai/training/f2_sLLM/.venv/bin/python \
  -r ai/training/f2_sLLM/requirements.txt
```

먼저 8건·2 step으로 모델 로딩부터 저장까지 확인한다. 학습기는 Qwen3 채팅 템플릿을
`enable_thinking=False`로 렌더링해 현재 분류 평가 조건과 맞춘다.

```bash
ai/training/f2_sLLM/.venv/bin/python ai/training/f2_sLLM/train_qlora.py \
  --train-data /workspace/datasets/f2-<version>/sft-train.jsonl \
  --validation-data /workspace/datasets/f2-<version>/sft-validation.jsonl \
  --output-dir /workspace/models/f2-qwen3-4b-smoke \
  --max-samples 8 \
  --max-steps 2
```

정상 완료 후 새 출력 경로로 전체 학습을 실행한다. SSH 연결 종료에 대비해 `tmux` 안에서
실행하고, Network Volume이 연결되지 않은 Pod이라면 종료 전에 산출물을 내려받는다.

full-output 학습은 별도 설정을 명시한다. 학습기는 Qwen 채팅 템플릿을 적용한
`prompt + completion` 토큰 수가 `max_length` 2048을 넘으면 정답 JSON을 잘라 학습하지
않고 실행을 중단한다.

```bash
ai/training/f2_sLLM/.venv/bin/python ai/training/f2_sLLM/train_qlora.py \
  --train-data /workspace/datasets/f2-<version>/sft-train.jsonl \
  --validation-data /workspace/datasets/f2-<version>/sft-validation.jsonl \
  --config ai/training/f2_sLLM/configs/qwen3-4b-qlora-full.yaml \
  --output-dir /workspace/models/f2-qwen3-4b-qlora-v1
```

VRAM 부족 시 설정 파일에서 `per_device_train_batch_size`를 4→2→1 순서로 줄이고,
유효 배치 크기를 유지하려면 `gradient_accumulation_steps`를 반대로 늘린다. 결과는
`adapter/`, step별 checkpoint, `run_metadata.json`이다. 전체 기반 모델이 아니라 작은 LoRA
어댑터가 저장되므로 추론 시 동일한 기반 모델과 함께 로드해야 한다. 상담 전문은 메타데이터나
콘솔에 기록하지 않는다.

## 3. 학습 어댑터 평가

학습과 설정 선택에 사용하지 않은 test JSONL로 기반 모델과 어댑터를 결합해 평가한다.

```bash
ai/eval/f2_sLLM/.venv/bin/python ai/eval/f2_sLLM/evaluate.py \
  --dataset data/f2_llm/releases/<version>/test.jsonl \
  --task full \
  --dataset-release f2-<version> \
  --models Qwen/Qwen3-4B \
  --model-revision <40자리-Hugging-Face-commit> \
  --quantization 4bit \
  --adapter-path /workspace/models/f2-qwen3-4b-qlora-v1/adapter
```

`--model-revision`에는 학습 `run_metadata.json`의 `resolved_model_revision`을 전달한다. `main`을
다시 해석해 다른 기반 가중치로 평가하지 않도록 단일 모델 평가는 항상 불변 commit에 고정한다.

같은 test split에서 base 4B와 adapter의 JSON 파싱, 상담 유형, 장부 불일치,
필드 키·값, evidence 근거와 금지된 필드 제안을 비교한다. validation loss만으로
최종 모델을 확정하지 않는다.

## 4. Infra 전달 bundle 생성

학습 담당자는 AWS·RunPod 권한 없이 로컬에서 학습과 평가를 마친다. Infra에는 학습 폴더나
체크포인트가 아니라 아래 명령이 만든 `tar.gz` 파일 하나만 전달한다.

현재 정량 승격 임계값은 고정하지 않는다. 파인튜닝 담당자는 `full` 평가 지표를 검토하고 공유 dev에
올릴 모델 하나를 선택한 뒤 다음 `promotion-approval:v2` 승인 파일을 만든다. `evaluation_run_id`는
평가 요약의 `run_id`, `selected_model`은 같은 요약의 `models[].label`, `release_mode`는 평가 실행의
`lora|base`와 같아야 한다.

```json
{
  "schema_version": 2,
  "status": "approved",
  "release_mode": "lora",
  "evaluation_run_id": "20260902T010203Z",
  "selected_model": "qwen3-4b",
  "decision_owner": "fine-tuning-owner",
  "rationale": "전체 상담분석 지표와 오류 사례를 검토해 공유 dev 승격을 승인함"
}
```

`rationale`에는 평가 판단 요약만 쓰고 상담 원문, 예측 원문, 로컬 경로와 비밀값을 넣지 않는다.

```bash
uv run --locked --project ai python ai/training/f2_sLLM/package_release.py \
  --release-id consultation-v2 \
  --release-mode lora \
  --training-output /local/models/f2-consultation-v2 \
  --evaluation-summary ai/eval/f2_sLLM/results/<run-id>/summary.json \
  --promotion-approval /local/approvals/consultation-v2.json \
  --dataset-release f2-1.0.0 \
  --output /local/handoff/consultation-v2.tar.gz
```

공개 Hugging Face 기반 모델을 adapter 없이 승격할 때도 tar를 없애지 않는다. 같은 검증 metadata
bundle을 만들되 `--training-output`을 전달하지 않는다. 기반 모델 ID와 40자리 commit은 승인된 평가
결과에서 파생된다.

```bash
uv run --locked --project ai python ai/training/f2_sLLM/package_release.py \
  --release-id consultation-base-v2 \
  --release-mode base \
  --evaluation-summary ai/eval/f2_sLLM/results/<run-id>/summary.json \
  --promotion-approval /local/approvals/consultation-base-v2.json \
  --dataset-release f2-1.0.0 \
  --output /local/handoff/consultation-base-v2.tar.gz
```

공유 dev의 `sllm`은 전체 상담분석 capability이므로 `--task full` 평가 결과만 포장된다.
현재 classification-only adapter는 학습 실험에는 사용할 수 있지만 이 전달 절차로 승격할 수 없다.
package 단계는 metric 임계값을 판정하지 않고 승인 상태·평가 실행·선택 모델 연결을 검증한다.
LoRA에서는 선택 모델의 ID·실제 commit·adapter tree checksum을 학습 metadata, adapter config와 실제
파일에 대조한다. bundle에는 mode에 따른 PEFT adapter, aggregate allowlist로 다시 만든 평가 요약과
승인, 기반 모델의 불변 revision과 데이터 checksum만 포함된다. 원본 데이터·전사·예측 JSONL·로컬
경로·checkpoint·비밀값은 포함되지 않는다. `training_args.bin`은 정상 Trainer 산출물이지만 서빙에
필요하지 않은 pickle이므로 checksum과 bundle에서 제외하고, 알려진 PEFT·tokenizer 파일 외의 adapter
파일은 패키징을 거부한다.

학습 담당자의 책임은 bundle 생성과 checksum 전달까지다. S3 게시, RunPod 생성, dev endpoint
변경은 Infra 담당자가 수행한다.

### 평가 전 dev bundle

공유 개발 환경에서 기동과 API 연결만 먼저 확인해야 할 때는 `dev` stage를 명시해 평가·승인 파일
없이 bundle을 만들 수 있다. 이 경로는 품질 검증이나 정식 승격을 대체하지 않는다. release ID는
반드시 `dev-`로 시작하며 기반 모델 commit, 학습 metadata와 실제 adapter checksum 검사는 그대로 수행된다.

```bash
uv run --locked --project ai python ai/training/f2_sLLM/package_release.py \
  --release-id dev-f2-handwritten-v05-qwen3-4b-full-v1 \
  --release-stage dev \
  --release-mode lora \
  --training-output /local/models/f2-handwritten-v05-qwen3-4b-full-v1 \
  --dataset-release f2-handwritten-v0.5 \
  --output /local/handoff/dev-f2-handwritten-v05-qwen3-4b-full-v1.tar.gz
```

`dev` bundle에는 `evaluation-summary.json`과 `promotion-approval.json`이 없고 manifest에
`evaluation.status=not-evaluated`가 남는다. Infra의 일반 create는 이를 거부하므로 반드시 전용 dev
plan/create 절차를 사용한다.
