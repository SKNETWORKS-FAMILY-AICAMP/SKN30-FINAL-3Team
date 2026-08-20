# Field Proposal Review Risk Model 실험 요약

## 1. 실험 목적

F2 sLLM이 생성한 필드 제안 중 사용자의 추가 검토가 필요한 제안을 간단한 머신러닝 모델로 구분할 수 있는지 확인하였다.

## 2. 데이터

기존 프로젝트의 합성 상담 시나리오에서 규칙 기반 Feature와 대리 Target을 파생한 소규모 합성 데이터 150건을 사용하였다. Train 120건, Test 30건이며 `needs_review=1` 비율은 46.7%이다. 데이터 생성 및 세부 전처리 과정은 별도 「데이터 전처리 결과서」에서 기술한다.

`needs_review`는 실제 사용자 수락·수정·거절 결과가 아니라 제출용 PoC를 위한 대리 라벨이다. `confidence` 역시 실제 운영 sLLM에서 관측한 값이 아니라 규칙과 고정 난수로 모사한 값이다.

## 3. 모델

- DummyClassifier (다수 클래스 기준선)
- Logistic Regression
- Random Forest

## 4. 평가 지표

`needs_review=1`을 positive class로 두고 Accuracy, Precision, Recall, F1을 계산하였다. 검토 필요 항목의 누락을 줄이는 것이 중요하므로 Recall을 첫 번째 선정 지표로 사용하였다.

## 5. 결과

| Model | Train Accuracy | Test Accuracy | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|
| Dummy | 0.5333 | 0.5333 | 0.0000 | 0.0000 | 0.0000 |
| Logistic Regression | 0.7917 | 0.8000 | 0.9000 | 0.6429 | 0.7500 |
| Random Forest | 0.9750 | 0.8000 | 0.9000 | 0.6429 | 0.7500 |

## 6. 최종 모델 선정

**선정 모델: Logistic Regression**

Recall과 F1이 같아 Train/Test 성능 차이가 더 작은 Logistic Regression을 선택하였다.

## 7. 한계

- 실제 사용자 데이터가 아닌 합성 상담 시나리오와 규칙 기반 대리 라벨을 사용하였다.
- 데이터 규모가 150건으로 작고 Test Set도 30건에 불과하다.
- 실제 F2 sLLM의 confidence 및 오류 분포와 차이가 있을 수 있다.
- 현재 실험은 모델 적용 가능성을 확인하기 위한 제출용 PoC 수준이다.
- 본 결과는 소규모 합성 Test Set의 결과이며 실서비스 성능을 의미하지 않는다.
- 향후 F2 서비스에서 축적되는 실제 사용자 수락·수정·거절 데이터를 Target으로 전환하여 재학습해야 한다.
- 딥러닝 모델은 이번 PoC 범위에서 학습하지 않았다.
