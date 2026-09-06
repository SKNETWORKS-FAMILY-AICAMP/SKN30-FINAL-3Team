---
status: 미확정
updated: 2026-09-02
---

# AI 미해결 질문

| ID | 질문 | 현재 맥락 | 영향 |
|---|---|---|---|
| AI-OQ-001 | 실제 생성·임베딩 모델 ID를 무엇으로 사용할 것인가? | F3를 로컬 vLLM으로 돌릴 경로는 열렸으나(`AI_VLLM_F3_BASE_URL`) 모델은 합성 케이스 A~I 평가로 선택해야 함 | 품질, 비용, 지연, 개인정보 전송 |
| AI-OQ-002 | F2/F3 역할별 `ModelRoute`를 어떻게 배정할 것인가? | Backend는 Provider·모델을 고르지 않고 AI workflow가 route를 소유함 | workflow 설정과 평가 slice |
| AI-OQ-003 | 운영 기본 Provider를 무엇으로 할 것인가? | adapter 구현과 F3 로컬 vLLM 경로는 운영 Provider 승인을 의미하지 않음. F3 기본값은 DB `ai_model_config`의 `openai`로 유지 | 배포, 장애 대응, 비용 |
| AI-OQ-004 | LangGraph checkpoint를 어디에 어떤 계약으로 저장할 것인가? | F3에서 재개가 필요하지만 Backend에 LangGraph 타입을 노출할 수 없음 | 실행 복구, 보존, Backend facade |

F3를 로컬 vLLM으로 평가하는 절차는 [infra/runpod/f3-vllm-runbook.md](../../../../infra/runpod/f3-vllm-runbook.md)에 있다. F3용 endpoint는 Infra가 F2용으로 한 쌍으로 제공하는 `AI_VLLM_SLLM_BASE_URL`·`AI_VLLM_STT_BASE_URL`과 별개이므로 `AI_F2_PROVIDER_STATUS`의 지배를 받지 않는다. 다만 vLLM adapter는 provider 종류당 하나뿐이라 F2용과 F3용 LLM endpoint를 동시에 설정하면 구성 오류로 막는다.

비밀 저장소와 환경별 주입 방식은 [프로젝트 ADR-0015](../../project-wiki/references/decisions/ADR-0015-environment-configuration-ownership.md)에서 해결했다. 실제 Provider 선택은 AI-OQ-003으로 유지한다.
