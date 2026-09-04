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
  모델의 공유 dev 승격을 `promotion-approval:v2`로 명시적으로 승인한다. 정량 임계값은 아직
  고정하지 않는다. 평가 요약에는 dataset release/checksum, 실제 Hugging Face commit,
  `release_mode=lora|base`와 adapter tree checksum을 남긴다. `package_release.py`는 이 provenance와
  선택 모델·학습 metadata·실제 adapter를 대조하고 로컬 경로·예측 원문을 제거한
  `release.json:v2` bundle만 만든다. 비교 모델 전체 통과는 요구하지 않는다.
  release 승격용 단일 모델 평가는 학습 metadata의 40자리 commit을 `--model-revision`으로 고정한다.
- 운영 AI Python 환경과 학습 환경은 분리한다. 학습 README의 Python 3.12는 실행 예시이며
  공통 Python 버전 결정이 아니다.
- 체크포인트, 어댑터와 실행 결과는 Git에 커밋하지 않는다. Infra가 검증한 공유 dev bundle의
  정본은 private S3이며 개인 학습 산출물 저장 방식은 학습 담당자 범위다.
- 품질 평가 전 개발 기동이 필요하면 `release_stage=dev`인 v2 bundle만 사용한다. ID는 `dev-`로
  시작하고 평가 요약·승인 파일을 넣지 않으며 `evaluation.status=not-evaluated`를 명시한다. 이 경로는
  평가·승격을 대체하지 않고 전용 `runpod-create-dev(-plan)`에서만 허용된다. 기반 commit과 adapter
  checksum 결속은 생략하지 않는다.
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
- base-only는 공개 Hugging Face 모델의 불변 commit만 지원하며 adapter·training이 `null`인 metadata
  bundle을 사용한다. private/gated 모델과 HF token 주입은 승인된 범위가 아니다.
