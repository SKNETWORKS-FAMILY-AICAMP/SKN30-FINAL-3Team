---
status: 미확정
updated: 2026-09-04
---

# AI 미해결 질문

| ID | 질문 | 현재 맥락 | 영향 |
|---|---|---|---|
| AI-OQ-001 | prod 생성·임베딩 모델 ID를 무엇으로 사용할 것인가? | local Luna와 합성 dev Bedrock Luna POC만 승인됐으며 prod 모델은 평가로 선택해야 함 | 품질, 비용, 지연, 개인정보 전송 |
| AI-OQ-002 | F2/F3 역할별 `ModelRoute`를 어떻게 배정할 것인가? | capability별 단일 활성 route와 DB 기반 선택은 구현됐지만 prod 배정은 미확정 | workflow 설정과 평가 slice |
| AI-OQ-003 | prod 기본 Provider를 무엇으로 할 것인가? | Bedrock은 합성 dev POC에 한해 승인됐으며 adapter 구현은 prod 승인을 의미하지 않음 | 배포, 장애 대응, 비용 |
| AI-OQ-004 | LangGraph checkpoint를 어디에 어떤 계약으로 저장할 것인가? | F3에서 재개가 필요하지만 Backend에 LangGraph 타입을 노출할 수 없음 | 실행 복구, 보존, Backend facade |

비밀 저장소와 환경별 주입 방식은 [프로젝트 ADR-0015](../../project-wiki/references/decisions/ADR-0015-environment-configuration-ownership.md)에서,
합성 dev의 Bedrock Provider 선택은 [프로젝트 ADR-0027](../../project-wiki/references/decisions/ADR-0027-bedrock-gpt56-luna-dev-poc.md)에서 해결했다.
prod Provider 선택은 AI-OQ-003으로 유지한다.
