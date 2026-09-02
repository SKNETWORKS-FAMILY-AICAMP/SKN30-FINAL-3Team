---
status: 결정
updated: 2026-09-01
---

# ADR-0005: Infra endpoint 상태에 따른 F2 offline runtime

- 상태: 승인됨
- 대체: [ADR-0004](ADR-0004-always-on-f2-runtime.md)의 Backend 시작 시 F2 runtime 항상 초기화 조항

## 결정

- F2 route는 항상 공개하고 별도 사용자 기능 플래그는 두지 않는다.
- Infra가 원자적으로 제공하는 `AI_F2_PROVIDER_STATUS`가 `active`일 때만 F2 runtime을 초기화한다.
- `offline`이면 Backend와 Worker는 정상 기동하고 F2 요청은 기존 `F2_UNAVAILABLE` 503 계약을
  반환한다. 다른 API와 F3 OpenAI provider에는 영향을 주지 않는다.

## 결과

임시 RunPod가 삭제된 동안에도 Backend 배포와 일반 기능이 정상 동작한다. endpoint가 active인데
필수 URL이 누락되면 구성 오류로 기동을 막아 잘못된 부분 활성화를 허용하지 않는다.
