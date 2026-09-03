---
status: 결정
updated: 2026-09-03
---

# ADR-0017: RunPod 임시 SLLM dev 서빙

- 상태: 부분 대체됨·코드 구현, S3 dev release 게시 완료·RunPod/Terraform 미적용
- 대체: [ADR-0016](ADR-0016-runpod-shared-f2-serving.md)
- 확장: 최초 구축·비밀 회전·관측과 reconcile은 [ADR-0018](ADR-0018-runpod-bootstrap-secrets-monitoring.md)이 대체한다.
- 확장: LoRA·base release v2, S3 cross-hash와 모델명 health는
  [프로젝트 ADR-0022](../../../project-wiki/references/decisions/ADR-0022-sllm-release-v2-base-only.md)를 적용한다.
- 확장: 미평가 개발 실행은
  [프로젝트 ADR-0023](../../../project-wiki/references/decisions/ADR-0023-sllm-dev-unevaluated-release.md)의
  `dev-*` bundle과 전용 create 명령만 사용한다.

## 결정

- 공유 Pod lifecycle은 stop/start가 아니라 create/delete다. 이름은
  `skn30-f2-serving-dev`, Secure Cloud, GPU 1개이며 자동 중지는 두지 않는다.
- Team Template v2는 image digest, 8001·8002 HTTP port, 30 GiB container disk, 서로 다른
  SLLM·STT Secret, STT model revision과 자원 기본값만 소유한다. SSH와 Volume은 사용하지 않는다.
- SLLM 기반 모델·revision·adapter는 private S3 release manifest가 소유한다. Infra 도구는 bundle을
  검증해 불변 게시하고 1시간 presigned URL만 새 Pod에 전달한다. AWS credential은 Pod에 주입하지
  않는다.
- vLLM은 내부 loopback에서 실행하고 route allowlist 인증 proxy가 `sllm`과 `stt` 이름으로 외부
  요청을 받는다. 실제 기반 모델명은 애플리케이션 계약이 아니다.
- 생성은 두 모델 health 성공 후 endpoint를 active로 바꾸고 API·Worker를 targeted recreate한다.
  삭제는 endpoint를 offline으로 바꾼 후 정확한 Pod ID를 삭제한다. AWS refresh 실패 시 이전
  endpoint를 복원한다.

## 결과

S3가 모델 정본이므로 Pod 삭제에 데이터 손실이 없고 유휴 Volume 비용이 없다. 대신 새 Pod마다
모델 weight를 다시 받아 시작 시간이 늘어난다. tmux, uv archive 복구와 개인 SSH key는 운영
경로에서 제거된다.
