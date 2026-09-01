# F2 분류·full-output QLoRA 학습

`Qwen/Qwen3-4B`를 F2 상담 유형 분류 또는 전체 구조화 출력으로 미세조정하는 오프라인
도구다. `classification`은 `매도의뢰`, `매수문의`, `기타상담`만 출력하고, `full`은 현재
장부 종류와 STT를 받아 상담 유형, 장부 불일치, 필드, 원문 근거, 불확실성과 상담 로그
초안을 출력한다. full-output 데이터는 사람 검수를 마친 별도 정답을 사용해야 한다.

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
  --task classification \
  --input data/f2_llm/releases/<version>/train.jsonl \
  --output /workspace/datasets/f2-<version>/sft-train.jsonl

python ai/training/f2_sLLM/prepare_sft_dataset.py \
  --task classification \
  --input data/f2_llm/releases/<version>/validation.jsonl \
  --output /workspace/datasets/f2-<version>/sft-validation.jsonl
```

full-output 데이터는 `--task full`로 변환한다. 이 모드는 `sample_id`, `ledger_type`과
`expected` 전체 계약을 검사하고, 장부 불일치·기타상담의 금지된 필드 제안과 원문에 없는
evidence를 거부한다.

```bash
python ai/training/f2_sLLM/prepare_sft_dataset.py \
  --task full \
  --input /workspace/datasets/f2-full-<version>/raw/train.jsonl \
  --output /workspace/datasets/f2-full-<version>/sft-train.jsonl

python ai/training/f2_sLLM/prepare_sft_dataset.py \
  --task full \
  --input /workspace/datasets/f2-full-<version>/raw/validation.jsonl \
  --output /workspace/datasets/f2-full-<version>/sft-validation.jsonl
```

## 2. RunPod 학습 환경

RunPod SSH 터미널에서 저장소 루트를 기준으로 실행한다. 학습 환경은 운영 AI와 평가 환경에서
분리한다. Python 3.12는 현재 학습 도구용 실행 예시이며 프로젝트 공통 버전 결정은 아니다.

```bash
uv venv --python 3.12 ai/training/f2_sLLM/.venv
uv pip install \
  --python ai/training/f2_sLLM/.venv/bin/python \
  --torch-backend=auto \
  -r ai/training/f2_sLLM/requirements.txt
```

`--torch-backend=auto`는 Pod의 NVIDIA 드라이버에 맞는 CUDA 빌드를 고르게 한다. 생략하면
드라이버보다 새로운 CUDA용 torch가 설치되어 `torch.cuda.is_available()`이 false가 되고
학습이 `QLoRA 학습에는 CUDA GPU가 필요합니다`로 중단된다.

RunPod PyTorch 템플릿은 `HF_HUB_ENABLE_HF_TRANSFER=1`을 설정하지만 새로 만든 venv에는
`hf_transfer`가 없다. 기반 모델을 내려받기 전에 함께 설치한다.

```bash
uv pip install --python ai/training/f2_sLLM/.venv/bin/python hf_transfer
```

기반 모델 캐시는 Pod 재시작 후에도 남도록 볼륨에 둔다.

```bash
export HF_HOME=/workspace/hf-cache
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

full-output 학습에는 `configs/qwen3-4b-qlora-full.yaml`을 사용한다. 분류용 설정과 달리
`max_length`가 2048이다. 현재 full-output 데이터의 prompt+completion 최대 길이가 2,436자라
분류용 1024로는 정답 JSON 끝부분(`summary`)이 조용히 잘린다. 길이를 늘린 만큼 활성 메모리가
늘어나므로 `per_device_train_batch_size`는 2, `gradient_accumulation_steps`는 16으로 두어
유효 배치 32를 유지한다. 실제 토큰 길이는 학습 전에 기반 모델 토크나이저로 확인한다.

기존 분류 adapter를 초기값으로 full-output을 추가학습할 때는 새 출력 경로와
`--init-adapter`를 사용한다. 기반 모델 ID·revision과 LoRA 구성이 기존 adapter와 다르면
실행을 중단한다. 기존 adapter 가중치만 불러오고 optimizer와 scheduler는 새로 만든다.
기존 실행의 `run_metadata.json`에 기록된 `resolved_model_revision`은 `--model-revision`으로
전달해 YAML의 mutable `main`을 실행 시점에 덮어쓴다.

```bash
ai/training/f2_sLLM/.venv/bin/python ai/training/f2_sLLM/train_qlora.py \
  --train-data /workspace/datasets/f2-full-<version>/sft-train.jsonl \
  --validation-data /workspace/datasets/f2-full-<version>/sft-validation.jsonl \
  --config ai/training/f2_sLLM/configs/qwen3-4b-qlora-full.yaml \
  --model-revision <기존-run의-resolved_model_revision> \
  --init-adapter /workspace/models/f2-qwen3-4b-classification/adapter \
  --output-dir /workspace/models/f2-qwen3-4b-full-output-<version>
```

`--resume-from-checkpoint`는 위 추가학습 자체가 중단된 경우에만 같은 `output-dir` 내부의
checkpoint와 함께 사용한다. 이전 분류 checkpoint를 새 full-output 학습 재개 경로로 쓰지 않는다.

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
