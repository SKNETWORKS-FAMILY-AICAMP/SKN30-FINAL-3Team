# Data

프로젝트의 AI 파이프라인(F2 상담 분석, F3 중개 판단)을 위한 원천 데이터, 합성 시나리오, 라벨링 산출물, 그리고 검증된 학습·평가 데이터셋 릴리스를 관리합니다.

---

## 데이터셋 현황

최신 데이터셋 목록 및 검증 상태는 [`registry.yaml`](registry.yaml)에서 관리합니다.

| 데이터셋 ID | 디렉터리 | 주요 목적 | 최신 릴리스 및 상태 |
|---|---|---|---|
| `f2-llm-analysis` | `f2_llm/` | Qwen SLLM 상담 유형 분류·필드 추출·요약 SFT 학습 및 평가 | `f2-handwritten-v0.5` (Train, Val, Test 분할 완료) |
| `f2-sell-request-privacy-safe` | `f2_sell_request/` | F2 매도의뢰 대화 분석을 위한 합성 시나리오 | `v0.2.0` (비식별화 및 품질 검증 완료) |

---

## 디렉터리 구조

```text
data/
├── README.md
├── registry.yaml                     # 데이터셋 등록 및 버전 관리 레지스트리
├── manifest.template.yaml            # 신규 릴리스용 메타데이터 템플릿
├── scripts/                          # 시나리오 생성, 병합, 데이터셋 분할 스크립트
│   ├── generate_f2_sell_request_scenarios.py
│   ├── generate_f2_buy_request_scenarios.py
│   ├── generate_f2_auxiliary_intent_scenarios.py
│   ├── generate_f2_handwritten_dialogue_scenarios.py
│   ├── generate_f2_full_output_scenarios.py
│   ├── merge_f2_intent_scenarios.py
│   ├── merge_f2_full_output_scenarios.py
│   └── split_f2_sllm_dataset.py
├── f2_llm/
│   ├── working/                      # 정제 및 검수 중인 중간 산출물
│   └── releases/
│       └── f2-handwritten-v0.5/      # 품질 검증 완료된 SFT 학습·평가 불변 릴리스
└── f2_sell_request/
    ├── working/
    └── releases/
```

---

## 산출물 관리 원칙

Git에 관리되는 모든 데이터 산출물은 다음 세 가지 파일이 한 세트로 유지됩니다.

| 산출물 파일 | 설명 |
|---|---|
| `<name>.jsonl` | 대화 시나리오, 추출 정답, 증강 데이터셋 본문 |
| `<name>.manifest.yaml` | 출처, 라이선스, 건수 및 분포, 데이터 분할(Split) 기준, 체크섬(SHA-256) |
| `<name>.privacy.md` | 데이터 생성 방식, 비식별화(De-identification) 처리 내역, 개인정보 검증 결과 |

---

## 데이터셋 분할 및 누수 방지 원칙

1. **불변 식별자 (`sample_id`)**: 모든 데이터 레코드는 영구적이고 고유한 식별자를 가집니다.
2. **그룹 기준 분할 (`source_group_id`)**: 동일한 원천에서 파생되거나 증강(Augmentation)된 시나리오는 반드시 동일한 데이터 분할(Train / Validation / Test)에 포함되어 데이터 누수(Data Leakage)를 방지합니다.
3. **불변 릴리스**: 한 번 `releases/`에 발행된 버전은 내용을 수정하지 않으며, 수정이 필요한 경우 새 버전 번호를 부여합니다.

---

## 주요 스크립트 실행

```bash
# 1) 시나리오 병합
python3 scripts/merge_f2_full_output_scenarios.py

# 2) SFT 데이터셋 분할 (Train/Val/Test 분할 및 split-report 생성)
python3 scripts/split_f2_sllm_dataset.py
```

---

## 개인정보 보호 원칙

- 실제 고객의 실명, 전화번호, 상세 주소(동·호수), 금융 정보는 절대 Git에 커밋하지 않습니다.
- 모든 대화 데이터는 검증된 가상의 합성 데이터(Synthetic Data) 또는 엄격하게 비식별화된 데이터를 사용합니다.
