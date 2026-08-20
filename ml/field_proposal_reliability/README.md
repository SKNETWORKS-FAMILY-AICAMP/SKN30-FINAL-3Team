# Field Proposal Review Risk Model PoC

F2의 sLLM 필드 제안 중 사용자의 추가 검토가 필요한 제안을 구분할 수 있는지 확인하는 임시 제출용 이진 분류 PoC입니다. 실제 서비스 연동이나 실사용자 데이터 학습을 포함하지 않습니다.

## 중요한 해석 범위

- 원천은 프로젝트에 이미 있는 **합성 상담 시나리오**입니다.
- 3개 원천 파일은 총 1,250행이지만, 50행 파일 전체가 200행 파일에 중복되어 `scenario_id`, `source_group_id`, transcript SHA-256으로 중복 제거하면 1,200건입니다.
- 최종 CSV의 150행은 서로 다른 원천 그룹과 서로 다른 transcript를 사용합니다.
- `needs_review`는 실제 사용자 피드백이 아니라 규칙 기반 대리 라벨입니다.
- `confidence`도 실제 운영 sLLM 점수가 아니라 모사한 값입니다.
- 결과는 소규모 합성 Test Set의 PoC 결과이며 실서비스 성능을 뜻하지 않습니다.

## 폴더

```text
field_proposal_reliability/
├── README.md
├── requirements.txt
├── scripts/
│   ├── build_dataset.py
│   └── run_experiment.py
├── notebooks/
│   ├── field_proposal_review_risk_poc.ipynb
│   └── field_proposal_review_risk_poc_output.ipynb  # 실행 후 생성
├── data/
├── reports/
└── artifacts/
```

## 로컬 재현

저장소 루트에서 실행합니다.

```bash
python3 ml/field_proposal_reliability/scripts/build_dataset.py
python3 ml/field_proposal_reliability/scripts/run_experiment.py
```

필수 라이브러리가 없는 환경에서는 별도 가상환경에 `requirements.txt`를 설치합니다. 생성기는 원천 `data/`를 읽기만 하며, 모든 출력은 이 PoC 폴더 안에 저장합니다.

데이터 생성기는 다음을 강제 검증합니다.

- 총 150행, 10개 `field_type`별 15행
- `needs_review=0` 80행 / `needs_review=1` 70행
- 결측·proposal ID·source group·transcript 중복 0건
- 수치 범위와 이진 컬럼 계약
- `RANDOM_STATE=42`와 동일 CSV SHA-256

학습 스크립트는 Target 층화(`stratify=needs_review`) 80:20 분할을 사용하고 Test에 10개 `field_type`이 모두 포함되는지 검사합니다. 또한 원천 group/transcript 누수 0건, 저장 모델 재로딩 및 알 수 없는 `field_type` 예측을 검증합니다.

## Colab CLI 실행

현재 저장된 지표·모델·출력 Notebook은 `local_notebook_verification` 실행 결과입니다. 이 작업 환경에서는 Colab CLI 인증이 설정되지 않아 원격 Colab 실행을 수행하지 않았으며, `reports/colab_execution_status.json`에 그 상태를 기록했습니다. 원격 실행 결과로 해석하지 마세요.

개인정보와 불필요한 원문 반출을 피하기 위해 Colab에는 원천 JSONL을 업로드하지 않습니다. 먼저 로컬에서 `build_dataset.py`를 실행한 뒤 다음 세 파일만 세션에 올립니다.

- `data/synthetic_field_proposals.csv`
- `scripts/run_experiment.py`
- `notebooks/field_proposal_review_risk_poc.ipynb`

예시 순서입니다. CPU면 충분합니다.

```bash
colab new -s f2-field-review-risk-poc
colab upload -s f2-field-review-risk-poc ml/field_proposal_reliability/data/synthetic_field_proposals.csv /content/f2_poc/data/synthetic_field_proposals.csv
colab upload -s f2-field-review-risk-poc ml/field_proposal_reliability/scripts/run_experiment.py /content/f2_poc/scripts/run_experiment.py
colab exec -s f2-field-review-risk-poc -f ml/field_proposal_reliability/notebooks/field_proposal_review_risk_poc.ipynb
colab download -s f2-field-review-risk-poc /content/f2_poc_outputs.zip ml/field_proposal_reliability/colab/f2_poc_outputs.zip
colab log -s f2-field-review-risk-poc -o ml/field_proposal_reliability/reports/colab_execution_log.txt
colab stop -s f2-field-review-risk-poc
```

Notebook 실행 결과는 입력 Notebook 옆의 `field_proposal_review_risk_poc_output.ipynb`에 자동 저장됩니다. 실패해도 세션을 반드시 종료해야 합니다.

실행 완료 Notebook은 다음 검증을 통과해야 합니다. 모든 코드 셀이 실행됐고 Jupyter `error` 출력이 0개인지 확인합니다.

```bash
python3 ml/field_proposal_reliability/scripts/run_experiment.py --verify-notebook-output ml/field_proposal_reliability/notebooks/field_proposal_review_risk_poc_output.ipynb
```

`metrics.json`과 `model_metadata.json`에는 단순 `execution_label` 외에도 `google.colab` import 가능 여부, 실행 당시 cwd, platform, Python 실행 파일과 판정된 `runtime_env`가 기록됩니다.

## 생성 산출물

데이터:

- `data/synthetic_field_proposals.csv`
- `data/source_inventory.json`
- `data/data_generation_metadata.json`

모델과 메타데이터:

- `artifacts/field_proposal_review_risk_model.joblib`
- `artifacts/model_metadata.json`

결과:

- `reports/eda_summary.json`
- `reports/model_comparison.csv`
- `reports/metrics.json`
- `reports/confusion_matrix_logistic_regression.png`
- `reports/confusion_matrix_random_forest.png`
- `reports/random_forest_feature_importance.png`
- `reports/experiment_summary.md`
- `reports/local_execution_log.txt` 또는 `reports/colab_execution_log.txt`
- `reports/colab_execution_status.json`

최종 모델은 `needs_review=1` Recall, F1, Train/Test Accuracy 차이, 단순성 순으로 고릅니다. 두 학습 모델의 Recall·F1·성능 차이가 모두 0.03 이내면 Logistic Regression을 선택합니다.
