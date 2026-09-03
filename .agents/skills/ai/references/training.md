# AI 오프라인 학습

## F2 상담 분류·full-output 학습

- 학습 코드는 `ai/training/f2_sLLM/`에 둔다.
- 학습 코드는 운영 `src` 패키지에 포함하지 않는다. AI pytest는 모듈 루트를 import 경로에
  추가해 `tests/unit/training/`에서 `training.f2_sLLM`을 직접 검증한다.
- 데이터 분할과 계보는 Data가 소유하며 `data/scripts/split_f2_sllm_dataset.py`로
  `source_group_id` 단위 train·validation·test 분할한다. 이 도구는 분류 스키마와
  full-output 스키마를 모두 받고, full-output 행은 장부·라벨 정합과 필드 제안 금지 구간을
  분할 전에 검사한다. 분할 보고서에는 split별 장부·셀 분포와 장부 불일치 건수가 남는다.
- AI 학습 입력 변환, QLoRA 실행과 어댑터 산출물은 AI가 소유한다.
- 학습 담당자는 Infra 권한 없이 실험하며, 전체 상담분석 `full` 평가 지표를 검토한 뒤 선택한
  모델의 공유 dev 승격을 명시적으로 승인한다. 정량 임계값은 아직 고정하지 않고 담당자가 승인
  사유를 남기며, `package_release.py`는 평가 실행·선택 모델과 연결된 승인만 받아 경로가 제거된
  SLLM bundle을 만든다. 비교 모델 전체의 통과는 요구하지 않는다. 이 bundle이 Infra와의 유일한
  모델 전달 계약이다.
- 운영 AI Python 환경과 학습 환경은 분리한다. 학습 README의 Python 3.12는 실행 예시이며
  공통 Python 버전 결정이 아니다.
- 체크포인트, 어댑터와 실행 결과는 Git에 커밋하지 않는다. Infra가 검증한 공유 dev bundle의
  정본은 private S3이며 개인 학습 산출물 저장 방식은 학습 담당자 범위다.
- 실행 메타데이터에는 설정, 입력 체크섬, 코드 revision과 지표를 남기되 상담 전문은 남기지 않는다.
- 학습 입력 변환은 `classification`과 `full`을 지원한다. `full`은 현재 장부 종류와
  STT 텍스트를 prompt로, 상담 유형·장부 불일치·필드·근거·불확실성·요약의
  6-key `expected`를 completion으로 사용한다.
- full-output 변환은 장부·라벨 불일치, fields/evidence 키 대응, evidence의 원문 포함과
  필드 제안 금지 구간을 학습 전에 검사한다.
- full-output 학습은 별도 2048 토큰 설정을 사용하며, 채팅 템플릿 적용 후 전체
  prompt+completion이 설정 길이를 넘으면 잘라지 않고 학습을 중단한다.
- test split은 SFT 변환 입력에서 차단하고 최종 비교에만 사용한다.
- `Qwen/Qwen3-4B` 선택과 QLoRA 설정은 팀 승인 전까지 실험 설정이며 승인된 운영 결정이 아니다.
- classification-only adapter는 상담분석 `sllm` release로 승격하지 않는다.
