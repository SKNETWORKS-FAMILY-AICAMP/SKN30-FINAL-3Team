# F2 STT 평가 도구

동일한 음성과 정답 전사로 여러 faster-whisper 모델의 정확도와 실행 시간을 비교하는 독립 실행 도구다.

현재 실제 F2 STT 데이터 평가는 보류되어 있으며 저장소의 `data/` 아래에 STT 데이터셋을 두지 않는다.
평가를 재개할 때 승인된 로컬 또는 외부 저장 위치를 `--data-dir`과 `--manifest`로 명시한다.

## 구조

평가 데이터는 저장소 밖에도 둘 수 있으며 다음 구조를 사용한다.

```text
<stt-dataset>/
├── audio/                    # AI Hub 음성 50개, Git 제외
├── labels/                   # 대응하는 원본 TXT 50개, Git 제외
└── labels.jsonl              # 평가용 음성·정답 연결 목록, Git 제외

ai/eval/f2_stt/
├── README.md
├── prepare_manifest.py       # WAV/TXT 50쌍 선정 및 manifest 생성
├── evaluate.py
└── results/                  # 예측과 비교 결과, Git 제외
```

`labels.jsonl`의 `audio`는 manifest가 위치한 디렉터리를 기준으로 한 상대 경로다.

```json
{"id":"sample_001","audio":"audio/sample_001.wav","reference":"평가용 정답 전사"}
```

원본 음성, 라벨과 모델 예측 전문은 저장소에 커밋하지 않는다. 실제 개인정보가 포함된 데이터는
저장 위치, 접근 권한, 보존 기간과 삭제 정책이 승인되기 전에는 사용하지 않는다.

## 1. 평가 manifest 생성

평가를 재개할 때 WAV/TXT 짝에서 난수 시드가 고정된 샘플을 선정한다. 원본 파일은 삭제하지 않고
명시한 데이터 디렉터리의 `labels.jsonl`에 선택된 항목만 기록한다.

```bash
python ai/eval/f2_stt/prepare_manifest.py \
  --data-dir /absolute/path/to/stt-dataset \
  --count 50 \
  --seed 42 \
  --force
```

## 2. 모델별 평가

평가기는 `faster-whisper` 모델 ID를 여러 개 받아 순서대로 실행한다. 모델 선택은 아직 확정된
프로젝트 결정이 아니며, 아래 ID는 실행 형식을 보여주기 위한 예시다.

`faster-whisper`는 선택 평가 의존성이므로 기존 Python 3.13 AI 런타임 의존성에는 추가하지 않았다.
로컬 평가 전용 Python 3.12 환경을 만들고 설치한다.

```bash
uv venv --python 3.12 ai/eval/f2_stt/.venv
uv pip install \
  --python ai/eval/f2_stt/.venv/bin/python \
  faster-whisper==1.2.1
```

CPU에서 실행하려면 다음 명령을 사용한다.

```bash
ai/eval/f2_stt/.venv/bin/python ai/eval/f2_stt/evaluate.py \
  --models small medium \
  --manifest /absolute/path/to/stt-dataset/labels.jsonl \
  --device cpu \
  --compute-type int8
```

CUDA 환경에서는 해당 장비에 맞는 `device`와 `compute-type`을 명시한다.

```bash
ai/eval/f2_stt/.venv/bin/python ai/eval/f2_stt/evaluate.py \
  --models small medium \
  --manifest /absolute/path/to/stt-dataset/labels.jsonl \
  --device cuda \
  --compute-type float16
```

모든 모델은 한국어, beam size 5, VAD 비활성화 조건으로 실행된다. 비교 조건을 바꾸려면 CLI
옵션을 사용하고 모든 모델에 같은 값을 적용한다.

## 결과

```text
results/
├── small_predictions.jsonl
├── medium_predictions.jsonl
└── summary.csv
```

`summary.csv`에는 성공·실패 건수, 한국어 CER, WER, 평균 지연시간, 전체 RTF와 모델 로딩 시간이
기록된다. CER은 공백과 문장부호를 제외한 글자 단위, WER은 공백 기준 어절 단위로 계산한다.
