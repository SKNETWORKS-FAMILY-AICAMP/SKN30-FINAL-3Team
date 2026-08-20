---
status: 미확정
updated: 2026-08-20
---

# 미해결 질문

| ID | 질문 | 현재 후보·맥락 | 영향 | 결정 주체 |
|---|---|---|---|---|
| OQ-007 | 아직 확정되지 않은 개인정보의 보존 기간과 삭제 절차는 무엇인가? | 기능 및 법률 검토 후 결정. `agent_run.requested_by`는 [개인정보 정책](privacy/policy.md)에서 확정했고 인물 성명·연락처, 상담 원문과 임시 음성이 남아 있다 | DB, 로그, 큐, 백업 | 기획·팀 |
| OQ-009 | RDS 작업 polling에서 SQS·DLQ로 전환할 측정 조건과 소비·재시도 계약은 무엇인가? | 1차는 RDS polling이며 독립 재시도·지연 격리·Worker 확장이 어려워질 때만 SQS·DLQ 도입 | backend-ai 계약, 멱등성, DLQ, 배포 | 백엔드·에이전트·인프라 담당·팀 |
| OQ-012 | `negotiation_side` 값 어휘를 무엇으로 확정할 것인가? | migration 005는 컬럼만 정의하고 값을 정하지 않았다. Backend는 앵커 종류를 따라 `LISTING`·`REQUIREMENT`를 내부 임시값으로 쓰고 있고, 실행하지 않는 archive DDL에는 `LISTING`·`CUSTOMER` 표기가 남아 있다 | 포지션 카드 cache key, Backend-AI 공개 계약, 후보 카드 | 백엔드·에이전트 담당·팀 |

질문이 해결되면 관련 정본 문서 또는 ADR에 결과를 반영하고 이 표에서 제거한다. Git 이력은 토론의 과거 상태를 보존한다.
