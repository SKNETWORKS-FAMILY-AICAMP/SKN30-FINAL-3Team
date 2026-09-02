# F2 상담 유형 QLoRA 학습

`Qwen/Qwen3-4B`를 `매도의뢰`, `매수문의`, `기타상담` 세 상담 유형으로
분류하도록 미세조정하는 오프라인 도구다. 공동중개·단순문의·불명확한 상담은 `기타상담`으로
합친다. 현재 데이터에는 필드별 정답이 없으므로 이 학습은 **상담 유형 분류만** 다룬다.
현재 운영 F2의 필드 추출·근거·요약 모델을 대체하지 않으며,
그 기능을 학습하려면 별도의 검수 라벨이 필요하다.

모델 ID와 QLoRA 설정은 실험 기본값일 뿐, 승인된 운영 모델 결정이 아니다.
정식 재현 실험 전에는 설정의 `revision: main`을 Hugging Face의 불변 commit hash로 바꾼다.
실행 시 실제로 확인된 모델 revision도 `run_metadata.json`에 기록된다.

## 폴더 역할

```text
ai/training/f2_sLLM/
├── configs/qwen3-4b-qlora.yaml  # 모델·QLoRA·학습 설정
├── prepare_sft_dataset.py       # 분할 데이터를 채팅 학습 형식으로 변환
├── train_qlora.py               # QLoRA 학습 및 어댑터 저장
├── requirements.txt             # RunPod 학습 전용 의존성
└── outputs/                     # 로컬 산출물(Git 제외)
```

데이터 분할은 데이터 계보를 소유하는 `data/scripts/split_f2_sllm_dataset.py`가 담당한다.
동일 `source_group_id`는 항상 같은 split에 배치되며, test는 SFT 변환 단계에서 차단된다.

## 1. 데이터 준비

현재 `data/f2_llm/working/`의 파일은 검수·발행 전 초안이다. 아래 명령은 분할 도구를
검증하는 개발 예시이며, 정식 모델 학습에는 manifest·privacy 문서와 검수를 갖춘
`data/f2_llm/releases/<version>/` 입력을 사용한다. 분할 건수와 seed는 팀 합의 후 명시한다.

```bash
python data/scripts/split_f2_sllm_dataset.py \
  --input data/f2_llm/working/<source>.jsonl \
  --output-dir data/f2_llm/working/<split-name> \
  --validation-per-label 25 \
  --test-per-label 25 \
  --seed 20260820
```

`split-report.json`에서 입력·출력 체크섬, 건수, 라벨 분포를 확인한다. 이 파일은 작업
보고서이며 정식 릴리스 manifest를 대신하지 않는다. 릴리스 시에는 `data/README.md`의 절차와
`manifest.template.yaml`을 따른다.

학습에는 train과 validation만 변환한다. test는 최종 평가 전까지 열어보거나 변환하지 않는다.

```bash
python ai/training/f2_sLLM/prepare_sft_dataset.py \
  --input data/f2_llm/releases/<version>/train.jsonl \
  --output /workspace/datasets/f2-<version>/sft-train.jsonl

python ai/training/f2_sLLM/prepare_sft_dataset.py \
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

```bash
ai/training/f2_sLLM/.venv/bin/python ai/training/f2_sLLM/train_qlora.py \
  --train-data /workspace/datasets/f2-<version>/sft-train.jsonl \
  --validation-data /workspace/datasets/f2-<version>/sft-validation.jsonl \
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
  --task classification \
  --models Qwen/Qwen3-4B \
  --quantization 4bit \
  --adapter-path /workspace/models/f2-qwen3-4b-qlora-v1/adapter
```

같은 test split에서 base 4B와 adapter의 accuracy, macro F1, 클래스별 recall, JSON 파싱 실패,
지연시간과 VRAM을 비교한다. validation 성능만으로 최종 모델을 확정하지 않는다.

## 4. Infra 전달 bundle 생성

학습 담당자는 AWS·RunPod 권한 없이 로컬에서 학습과 평가를 마친다. Infra에는 학습 폴더나
체크포인트가 아니라 아래 명령이 만든 `tar.gz` 파일 하나만 전달한다.

```bash
uv run --locked --project ai python ai/training/f2_sLLM/package_release.py \
  --release-id consultation-v1 \
  --training-output /local/models/f2-consultation-v1 \
  --evaluation-summary ai/eval/f2_sLLM/results/<run-id>/summary.json \
  --dataset-release f2-1.0.0 \
  --output /local/handoff/consultation-v1.tar.gz
```

공유 dev의 `sllm`은 전체 상담분석 capability이므로 `--task full` 평가 결과만 포장된다.
현재 classification-only adapter는 학습 실험에는 사용할 수 있지만 이 전달 절차로 승격할 수 없다.
bundle에는 PEFT adapter, 로컬 경로를 제거한 평가 요약, 기반 모델의 불변 revision과 데이터
checksum만 포함된다. 원본 데이터·전사·예측 JSONL·checkpoint·비밀값은 포함되지 않는다.

학습 담당자의 책임은 bundle 생성과 checksum 전달까지다. S3 게시, RunPod 생성, dev endpoint
변경은 Infra 담당자가 수행한다.
