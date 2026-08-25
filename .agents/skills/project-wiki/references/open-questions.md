---
status: 미확정
updated: 2026-08-25
---

# 미해결 질문

| ID | 질문 | 현재 후보·맥락 | 영향 | 결정 주체 |
|---|---|---|---|---|
| OQ-007 | 아직 확정되지 않은 개인정보의 보존 기간과 삭제 절차는 무엇인가? | 기능 및 법률 검토 후 결정. `agent_run.requested_by`와 `ai_decision_feedback.created_by`는 [개인정보 정책](privacy/policy.md)에서 확정했고 인물 성명·연락처, 상담 원문과 임시 음성이 남아 있다 | DB, 로그, 큐, 백업 | 기획·팀 |
| OQ-009 | RDS 작업 polling에서 SQS·DLQ로 전환할 측정 조건과 소비·재시도 계약은 무엇인가? | 1차는 RDS polling이며 독립 재시도·지연 격리·Worker 확장이 어려워질 때만 SQS·DLQ 도입 | backend-ai 계약, 멱등성, DLQ, 배포 | 백엔드·에이전트·인프라 담당·팀 |
| OQ-010 | Claude Code에서 Google Drive·Sheets를 인증된 읽기·쓰기 도구로 사용할 수 있는가? | Codex는 Google Drive 플러그인의 읽기 연결만 확인했다. Claude Code는 별도 연결 방법, 권한과 안전한 읽기 재검증 절차를 확인해야 한다 | Claude Code의 산출물 업로드·관리 시트 자동화 | 에이전트 운영 담당·팀 |

질문이 해결되면 관련 정본 문서 또는 ADR에 결과를 반영하고 이 표에서 제거한다. Git 이력은 토론의 과거 상태를 보존한다.
