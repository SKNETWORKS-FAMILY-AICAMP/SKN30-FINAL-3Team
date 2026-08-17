---
status: 미확정
updated: 2026-08-17
---

# AI 미해결 질문

| ID | 질문 | 현재 맥락 | 영향 |
|---|---|---|---|
| AI-OQ-001 | 실제 생성·임베딩 모델 ID를 무엇으로 사용할 것인가? | OpenAI·vLLM adapter만 구현했으며 모델은 평가로 선택해야 함 | 품질, 비용, 지연, 개인정보 전송 |
| AI-OQ-002 | F2/F3 역할별 `ModelRoute`를 어떻게 배정할 것인가? | Backend는 Provider·모델을 고르지 않고 AI workflow가 route를 소유함 | workflow 설정과 평가 slice |
| AI-OQ-003 | 운영 기본 Provider를 무엇으로 할 것인가? | adapter 구현은 운영 Provider 승인을 의미하지 않음 | 배포, 장애 대응, 비용 |
| AI-OQ-004 | LangGraph checkpoint를 어디에 어떤 계약으로 저장할 것인가? | F3에서 재개가 필요하지만 Backend에 LangGraph 타입을 노출할 수 없음 | 실행 복구, 보존, Backend facade |

비밀 저장소 제품과 환경별 주입 방식은 project-wiki의 OQ-010에서 관리한다.
