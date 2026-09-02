# AI 오프라인 학습

## F2 상담 유형 분류

- 학습 코드는 `ai/training/f2_sLLM/`에 둔다.
- 학습 코드는 운영 `src` 패키지에 포함하지 않는다. AI pytest는 모듈 루트를 import 경로에
  추가해 `tests/unit/training/`에서 `training.f2_sLLM`을 직접 검증한다.
- 데이터 분할과 계보는 Data가 소유하며 `data/scripts/split_f2_sllm_dataset.py`로
  `source_group_id` 단위 train·validation·test 분할한다.
- AI 학습 입력 변환, QLoRA 실행과 어댑터 산출물은 AI가 소유한다.
- 학습 담당자는 Infra 권한 없이 실험하며, 전체 상담분석 `full` 평가를 통과한 결과만
  `package_release.py`로 경로가 제거된 SLLM bundle을 만든다. 이 bundle이 Infra와의 유일한
  모델 전달 계약이다.
- 운영 AI Python 환경과 학습 환경은 분리한다. 학습 README의 Python 3.12는 실행 예시이며
  공통 Python 버전 결정이 아니다.
- 체크포인트, 어댑터와 실행 결과는 Git에 커밋하지 않는다. Infra가 검증한 공유 dev bundle의
  정본은 private S3이며 개인 학습 산출물 저장 방식은 학습 담당자 범위다.
- 실행 메타데이터에는 설정, 입력 체크섬, 코드 revision과 지표를 남기되 상담 전문은 남기지 않는다.
- 현재 구현은 `매도의뢰`, `매수문의`, `기타상담` 세 상담 유형 분류용이다.
  기존 공동중개·단순문의와 불명확한 상담은 `기타상담`에 합치며, 필드 추출·근거·요약에는
  검수된 별도 정답이 필요하다.
- test split은 SFT 변환 입력에서 차단하고 최종 비교에만 사용한다.
- `Qwen/Qwen3-4B` 선택과 QLoRA 설정은 팀 승인 전까지 실험 설정이며 승인된 운영 결정이 아니다.
- classification-only adapter는 상담분석 `sllm` release로 승격하지 않는다.
