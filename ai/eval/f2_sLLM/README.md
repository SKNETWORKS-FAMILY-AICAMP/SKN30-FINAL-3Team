# F2 sLLM 모델 비교

STT가 생성한 상담 텍스트를 동일한 조건으로 분석해 다음 Qwen3 후보를 비교한다.

- `Qwen/Qwen3-0.6B`
- `Qwen/Qwen3-1.7B`
- `Qwen/Qwen3-4B`
- `Qwen/Qwen3-8B`

이 목록은 **평가 후보**이며 운영 모델로 확정된 결정이 아니다. 1차 비교에서는 원본 Qwen3
체크포인트 네 개를 사용하고, 모든 모델의 thinking을 끈다. 4B가 적합한 후보로 좁혀진 뒤에
`Qwen/Qwen3-4B-Instruct-2507` 같은 후속 체크포인트를 별도 비교한다.

## 구조

```text
ai/eval/f2_sLLM/
├── README.md
├── models.yaml              # 모델 후보와 공통 추론 조건
├── requirements.txt         # 평가 전용 의존성
├── evaluate.py              # 추론, 자동 지표, 자원 사용량 측정
└── results/                 # 모델별 예측과 요약 지표, Git 제외
```

평가 입력과 사람이 검수한 정답은 `data/f2_llm/releases/<version>/`이 소유한다. 모델 실행과
결과는 이 폴더가 소유한다. 실제 고객 개인정보나 상담 원문은 저장소와 결과 로그에 넣지 않는다.

## 평가 데이터 형식

각 줄이 하나의 JSON 객체인 JSONL 파일을 사용한다. 현재 평가는 상담 유형만 비교하는
`classification`과 기존 분류·필드 추출을 함께 비교하는 `full` 두 가지 모드를 지원한다.

### 상담 유형 분류

`--task classification`은 다음 필드만 모델 입력과 정답으로 사용한다. 그 밖의 데이터셋
메타데이터는 평가 입력에 전달하지 않는다.

```json
{
  "scenario_id": "f2_sell_001",
  "transcript": "아파트를 매도하려고 전화드렸어요.",
  "label": "매도의뢰"
}
```

- `scenario_id`, `transcript`, `label`은 필수다.
- `label`은 `매도의뢰`, `매수문의`, `기타상담` 중 하나다.
- 정확도, macro F1, 클래스별 precision·recall·F1, 혼동 행렬을 계산한다.
- JSON 파싱 실패와 허용되지 않은 라벨 출력은 제외하지 않고 오답으로 계산한다.

### 전체 분류·추출

```json
{
  "sample_id": "f2_eval_001",
  "transcript": "한강아파트 101동 1203호 매매 12억에 내놓으려고요.",
  "ledger_type": "매물장",
  "expected": {
    "consultation_type": "매도의뢰",
    "ledger_mismatch": false,
    "fields": {
      "단지": "한강아파트",
      "동": "101",
      "호": "1203",
      "매매가": "12억"
    },
    "uncertainties": [],
    "summary": "한강아파트 101동 1203호를 12억 원에 매도 의뢰함."
  }
}
```

- `sample_id`, `transcript`, `ledger_type`, `expected`는 필수다. `full`은 기존 행의 장부 불일치까지 검증한다.
- `consultation_type`은 `매도의뢰`, `매수문의`, `기타상담` 중 하나다.
- `fields`에는 음성에서 확인된 값만 넣는다.
- 합성 데이터도 정답과 근거를 사람이 검수한 뒤 평가 릴리스로 발행한다.
- 최종 테스트 릴리스는 프롬프트 수정이나 QLoRA 학습에 사용하지 않는다.

## 실행

평가 의존성은 운영 AI 환경과 분리한다. 모델 다운로드 후 추론은 로컬에서 수행되며 별도의
모델 API 키를 사용하지 않는다.

```bash
uv venv --python 3.12 ai/eval/f2_sLLM/.venv
uv pip install \
  --python ai/eval/f2_sLLM/.venv/bin/python \
  --torch-backend=auto \
  -r ai/eval/f2_sLLM/requirements.txt
uv pip install --python ai/eval/f2_sLLM/.venv/bin/python hf_transfer
```

`--torch-backend=auto`는 Pod의 NVIDIA 드라이버에 맞는 CUDA 빌드를 고르게 한다. 생략하면
드라이버보다 새로운 CUDA용 torch가 설치되어 GPU를 사용하지 못한다. RunPod PyTorch
템플릿이 설정한 `HF_HUB_ENABLE_HF_TRANSFER=1` 때문에 새 venv에도 `hf_transfer`가 필요하다.

네 모델 전체를 실행한다.

```bash
ai/eval/f2_sLLM/.venv/bin/python ai/eval/f2_sLLM/evaluate.py \
  --dataset data/f2_llm/releases/0.2.0/test.jsonl \
  --task classification
```

전체 분류·추출 형식을 평가할 때는 기존 모드를 명시한다.

```bash
ai/eval/f2_sLLM/.venv/bin/python ai/eval/f2_sLLM/evaluate.py \
  --dataset data/f2_llm/releases/0.1.0/test.jsonl \
  --task full
```

VRAM이 부족하면 같은 양자화 조건을 모든 모델에 적용한다.

```bash
ai/eval/f2_sLLM/.venv/bin/python ai/eval/f2_sLLM/evaluate.py \
  --dataset data/f2_llm/releases/0.2.0/test.jsonl \
  --task classification \
  --quantization 4bit
```

특정 후보만 먼저 확인할 수도 있다.

```bash
ai/eval/f2_sLLM/.venv/bin/python ai/eval/f2_sLLM/evaluate.py \
  --dataset data/f2_llm/releases/0.2.0/test.jsonl \
  --task classification \
  --models Qwen/Qwen3-0.6B Qwen/Qwen3-1.7B
```

QLoRA 학습 결과는 기반 모델 하나와 어댑터 경로를 함께 지정한다. 이때 평가 환경에도
`peft`가 설치되어 있어야 한다.

```bash
ai/eval/f2_sLLM/.venv/bin/python ai/eval/f2_sLLM/evaluate.py \
  --dataset data/f2_llm/releases/<version>/test.jsonl \
  --task classification \
  --models Qwen/Qwen3-4B \
  --quantization 4bit \
  --adapter-path /workspace/models/f2-qwen3-4b-qlora-v1/adapter
```

## 결과와 판단 기준

실행마다 `results/<run-id>/`에 다음 파일이 생성된다.

- `<model-name>.jsonl`: 사례별 예측, 오류, 지연시간
- `summary.json`: 모델별 자동 지표와 실행 조건

자동 지표는 JSON 파싱 성공률, 상담 유형 정확도·macro F1, 장부 불일치 정확도, 추출 필드
precision·recall·F1, 원문과 일치하지 않는 근거 수, 평균·p95 지연시간과 최대 CUDA 메모리다. 요약과
불명확 값 처리 품질은 예측 파일을 모델명 없이 섞어 사람이 검수한다. 합격선은 아직 정하지
않으며, 품질 요구를 만족하는 후보 중 가장 작은 모델을 우선 선택한다.
