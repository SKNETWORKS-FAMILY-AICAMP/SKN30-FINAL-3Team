---
status: 결정
updated: 2026-09-04
---

# AI 결정 인덱스

| ADR | 상태 | 결정 |
|---|---|---|
| [ADR-0001](ADR-0001-ai-runtime-foundation.md) | 부분 대체됨 | Python 3.13·uv 독립 library와 Provider/config/runtime 경계 사용; env profile 조항은 프로젝트 ADR-0015에서 대체 |
| [ADR-0002](ADR-0002-langgraph-adoption.md) | 승인됨 | F3 멀티에이전트 workflow에 LangGraph를 채택하되 F2에는 강제하지 않음 |
| [ADR-0003](ADR-0003-structured-output-repair.md) | 승인됨 | 계약을 어긴 구조화 출력은 검증 지적을 되먹여 최대 3회까지 다시 만들고, 실패 등급은 바꾸지 않음 |
| [ADR-0004](ADR-0004-aliased-llm-endpoint-routing.md) | 부분 대체됨·코드 구현 | 범용 생성 endpoint를 provider·alias exact match로 routing하고 llama.cpp JSON Schema 출력을 로컬 재검증; Bedrock은 ADR-0005 적용 |
| [ADR-0005](ADR-0005-bedrock-sigv4-structured-generation.md) | 승인됨·코드 구현, AWS 미검증 | Bedrock Responses를 Instance Role SigV4로 호출하고 schema 지시·Pydantic 재검증 적용 |

실제 모델, 역할별 route, 운영 Provider와 checkpoint는 [open-questions.md](../open-questions.md)에서 관리한다.
