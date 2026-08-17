---
status: 결정
updated: 2026-08-17
---

# ADR-0002: LangGraph 채택 범위

- 상태: 승인됨
- 결정일: 2026-08-17

## 맥락

F3는 격리된 매물·손님 대리, Backend capability 호출, 중개 판정, 단계 진행과 실패 후 재개가 필요한
멀티에이전트 흐름이다. 반면 F2는 초기 구현에서 단순한 선형 파이프라인으로 충분할 수 있다.

## 결정

- F3 멀티에이전트 workflow의 상태 전이·재개 기반으로 LangGraph를 채택한다.
- F2에는 LangGraph를 강제하지 않고 현재 복잡도에 맞는 선형 orchestration을 허용한다.
- graph 상태와 checkpoint 타입은 AI 내부에 가두고 Backend에는 프레임워크 중립 facade와 진행·결과 계약만 공개한다.
- 이번 기반 작업에서는 Python 3.13에서 최소 graph compile 호환성만 자동 검증하며 production graph와 checkpoint 구현은 만들지 않는다.
- checkpoint 저장소, 보존과 Backend 영속 작업 연결은 실제 F3 workflow 설계에서 별도로 결정한다.

## 결과

F3는 재개 가능한 실행 모델을 기준으로 설계할 수 있으나, 단순 workflow가 불필요한 graph 계층을
부담하지 않는다. LangGraph 채택은 운영 Provider, 모델, queue 또는 checkpoint 제품의 선택을 확정하지 않는다.
