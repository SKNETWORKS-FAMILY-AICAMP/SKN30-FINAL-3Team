---
status: 결정
updated: 2026-08-17
---

# 결정 인덱스

| ADR | 상태 | 결정 |
|---|---|---|
| [ADR-0001](ADR-0001-agent-wiki.md) | 승인됨 | 프로젝트 지식을 저장소 스킬 위키로 관리 |
| [ADR-0002](ADR-0002-root-boundaries.md) | 대체됨 | 다섯 개 루트 모듈과 독립 환경 경계 사용; ADR-0006에서 대체 |
| [ADR-0003](ADR-0003-main-pr-flow.md) | 승인됨 | `develop` 없이 작업 브랜치에서 `main`으로 PR |
| [ADR-0004](ADR-0004-cross-agent-instructions.md) | 승인됨 | 공용 에이전트 지침과 스킬을 Claude Code에서도 재사용 |
| [ADR-0005](ADR-0005-requirements-management.md) | 승인됨 | 제품 요구사항을 분할 정본과 얇은 라우터로 관리 |
| [ADR-0006](ADR-0006-ai-backend-boundary.md) | 승인됨 | AI와 Backend의 프레임워크·영속성 경계 분리 |
| [ADR-0007](ADR-0007-terraform-iac.md) | 승인됨 | Terraform을 AWS 인프라 변경의 IaC 정본으로 사용 |

이 인덱스에는 프로젝트 공통 및 모듈 간 ADR만 둔다. 모듈 내부 결정은 각 모듈 스킬의 `references/decisions/index.md`에서 관리한다.

LangGraph의 AI 모듈 내부 채택 범위는 [AI ADR-0002](../../../ai/references/decisions/ADR-0002-langgraph-adoption.md)에서 관리한다. Terraform의 루트·state 세부 기준은 [Infra ADR-0001](../../../infra/references/decisions/ADR-0001-terraform-layout-and-state.md)에서 관리한다. ECS Fargate는 아직 승인된 프로젝트 결정이 아니므로 [open-questions.md](../open-questions.md)에서 관리한다.
