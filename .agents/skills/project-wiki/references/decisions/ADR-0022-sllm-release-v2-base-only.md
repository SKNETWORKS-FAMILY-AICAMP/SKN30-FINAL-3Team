---
status: 결정
updated: 2026-09-03
---

# ADR-0022: SLLM release v2와 base-only 서빙

- 상태: 부분 대체됨·코드 구현, S3 dev release 게시 완료·RunPod/Terraform 미적용
- 결정일: 2026-09-02
- 부분 대체: [ADR-0020](ADR-0020-sllm-release-handoff.md)의 LoRA 전용 release·승인·검증 계약
- 유지: ADR-0020의 private S3 정본, Secure Cloud Pod create/delete, active/offline과 Backend F2 503 계약
- 후속 예외: 미평가 개발 실행은 [ADR-0023](ADR-0023-sllm-dev-unevaluated-release.md)의 명시적 `dev` 경로만 허용

## 맥락

기존 release는 PEFT LoRA adapter와 최소 검증 메타데이터를 전달했지만 평가 결과가 실제 기반 모델
commit·adapter bytes·dataset release에 충분히 결속되지 않았다. 공개 평가 요약의 중첩 로컬 경로,
S3 두 객체 사이의 부분 게시, `/v1/models`의 모델명 미확인도 운영 오판 가능성을 남겼다. 한편
adapter가 필요 없는 기반 모델 후보도 같은 승인·평가 경계로 검증할 수 있어야 한다.

## 결정

- 새 패키저는 `release.json:v2`만 만든다. `release_mode`는 `lora|base`이며 공통
  `base_model.id`와 40자리 Hugging Face commit을 가진다. `lora`는 adapter·training이 필수이고
  `base`는 둘 다 `null`이다. 기존 v1 LoRA bundle과 이미 게시된 v1 객체는 마이그레이션 없이 계속
  읽는다.
- `promotion-approval:v2`는 `release_mode`, 평가 `run_id`, 선택 모델 label과 승인 사유를 결속한다.
  평가 요약은 dataset release/checksum, 실제 해석된 모델 commit, adapter 사용 여부와 tree checksum을
  기록한다. release manifest에는 원본 전체 평가 요약 SHA-256과 bundle에 넣는 공개 요약 SHA-256을
  구분해 기록한다. 패키저는 선택 모델·기반 모델·adapter config·학습 metadata·실제 adapter bytes가
  모두 일치할 때만 bundle을 만든다.
- 외부 전달용 평가 요약은 aggregate metric allowlist로 다시 만들며 데이터·adapter 로컬 경로,
  예측·원문·checkpoint·비밀 후보 필드를 포함하지 않는다.
- v2 S3 `bundle.tar.gz`와 `release.json`은 자기 SHA-256과 상대 객체 SHA-256을 user metadata로
  양방향 결속한다. 같은 release ID의 재실행은 기존 객체 metadata가 완전히 같을 때만 누락 객체를
  이어서 게시한다. v1은 과거 자기 SHA metadata만 허용한다.
- base-only도 adapter가 없는 metadata tar bundle을 사용한다. Pod는 공개 Hugging Face 기반 모델을
  불변 commit으로 내려받으며 base mode에서는 LoRA 옵션 없이 `sllm` 이름으로 기동한다. gated/private
  모델과 HF token 주입은 이 결정 범위가 아니다.
- Template과 자식 프로세스에서 Hugging Face token 계열 환경변수를 거부·제거한다. gated/private
  다운로드는 health 전에 실패하고 새 Pod가 정리된다. health는 HTTP 200뿐 아니라 각 응답의 모델 ID가
  `sllm`, `stt`인지 확인한다.
- `runpod-create-plan`은 Pod 생성과 presign 전에 control ready, 공유 Pod 부재, S3 두 객체 checksum,
  Backend EC2와 API·Worker health를 확인한다. 새 image generation bootstrap은 endpoint offline과
  공유 Pod 부재에서만 허용한다.
- health·Backend refresh·F2 smoke 실패는 이전 endpoint 복원과 새 Pod 삭제를 시도한다. rollback
  refresh 또는 삭제까지 실패하면 완료로 보고하지 않고 상태 확인·수동 reconcile 지침을 출력한다.
  삭제 후 `runpod-offline-smoke`는 503 `F2_UNAVAILABLE`을 검증한다.

## 결과

LoRA와 base-only가 같은 평가·승인·불변 게시 경계를 사용하고, 평가 대상과 실제 서빙 bytes 사이의
drift를 비용 발생 전에 더 많이 차단한다. 기반 가중치는 bundle이나 GHCR image에 넣지 않아 image
세대와 release를 분리한다. 공개 모델 다운로드 시간은 매 Pod 생성 시 계속 발생하며 정량 승격
임계값과 운영 모델 선택은 미확정으로 유지한다.
