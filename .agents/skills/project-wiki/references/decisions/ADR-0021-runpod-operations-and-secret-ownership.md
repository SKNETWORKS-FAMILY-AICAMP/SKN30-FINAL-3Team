---
status: 결정
updated: 2026-09-01
---

# ADR-0021: RunPod 운영 제어와 비밀값 정본

- 상태: 승인됨·코드 구현, 외부 자원 미적용
- 결정일: 2026-09-01
- 부분 대체: [ADR-0015](ADR-0015-environment-configuration-ownership.md)의 Terraform 수동 비밀값 소유 방식
- 유지: [ADR-0020](ADR-0020-sllm-release-handoff.md)의 create/delete와 active/offline 계약
- 확장: release v2·base-only·bootstrap image generation guard는
  [ADR-0022](ADR-0022-sllm-release-v2-base-only.md)를 적용한다.

## 결정

- Terraform은 AI Provider, delivery Discord, Alarm Discord, RunPod 운영·감시 key와 GHCR credential의
  Secrets Manager 컨테이너만 관리한다. 값과 version은 운영 명령이 관리하며 기존 Terraform Secret
  version은 `removed`와 `destroy=false`로 state에서만 분리한다.
- AI Provider 값은 renderer가 읽는 평면 `AI_*_API_KEY` JSON을 유지한다. 운영자가 제공하는 값은
  TTY 비표시 입력으로만 받고 F2 key 두 개는 도구가 생성한다.
- 성공한 GHCR image digest 하나를 `plan → 확인 → bootstrap`에 전달한다. bootstrap은 RunPod Secret,
  registry auth와 private immutable Template을 검증·생성하며 비민감 SSM 제어 문서의
  `provisioning|ready` 상태로 중단 지점 재개와 소유 자원 ID를 기록한다.
- 30분 기본 주기의 읽기 전용 감시가 RunPod 제어면, 공유 Pod, endpoint 일치, 인증 health, 실행 시간과
  시간당 비용을 기존 CloudWatch namespace에 기록한다. 8시간 실행 경고를 포함한 알람은 기존 Alarm
  SNS·Discord 경로를 사용한다.
- 감시는 endpoint나 Pod를 변경하지 않는다. `runpod-reconcile`도 기본 dry-run이며, Pod가 사라진
  active endpoint만 별도 확인 후 offline으로 전환할 수 있다. 자동 Pod 생성·삭제와 무인 endpoint
  전환은 하지 않는다.

## 결과

Terraform plan/state와 개인 `.env`가 운영 비밀값의 운반 경로가 아니게 된다. 장기 실행과 drift를
주기적으로 발견하지만 비용·가용성 조정은 운영자의 상태 확인과 명시적 명령을 거친다. Backend의
offline F2 503과 기존 공개 API·F2 응답 계약은 바뀌지 않는다.
