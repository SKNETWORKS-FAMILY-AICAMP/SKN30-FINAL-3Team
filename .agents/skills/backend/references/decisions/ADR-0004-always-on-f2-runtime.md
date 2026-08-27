---
status: 결정
updated: 2026-08-27
---

# ADR-0004: F2 runtime 상시 초기화

- 상태: 승인됨
- 결정일: 2026-08-27

## 맥락

음성메모 분석은 Backend의 기본 기능이며 환경별 `F2_ENABLED` 값으로 별도 활성화할 필요가 없다.
플래그가 빠지면 라우트는 남아 있지만 runtime만 생성되지 않아 요청이 503으로 실패하는 구성도 혼동을
만들었다.

## 결정

- Backend는 lifespan 시작 시 F2 runtime과 pipeline을 항상 초기화하고 종료 시 소유한 client를 닫는다.
- `F2_ENABLED` 설정과 Backend 설정 DTO의 활성화 필드는 제거한다.
- 모든 실행 환경은 `AI_VLLM_LLM_BASE_URL`과 `AI_VLLM_STT_BASE_URL`을 제공한다.
- Provider 연결 가능 여부는 실제 분석 요청 시 확인하며, 테스트는 외부 요청 없이 loopback endpoint와
  fake runtime을 사용해 수명주기를 검증한다.

## 결과

음성 분석 API의 활성화 상태가 환경변수에 따라 달라지지 않는다. 대신 필요한 AI endpoint가 누락되면
Backend 시작이 실패하므로 RunPod를 사용하지 않는 개발 환경도 형식상 유효한 endpoint 설정을 유지해야
한다. RunPod가 중지된 동안 일반 Backend 기능은 시작할 수 있지만 실제 F2 요청은 Provider 오류로 실패한다.
