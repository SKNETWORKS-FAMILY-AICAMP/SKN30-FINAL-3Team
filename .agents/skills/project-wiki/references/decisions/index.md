---
status: 결정
updated: 2026-09-02
---

# 결정 인덱스

| ADR | 상태 | 결정 |
|---|---|---|
| [ADR-0001](ADR-0001-agent-wiki.md) | 승인됨 | 프로젝트 지식을 저장소 스킬 위키로 관리 |
| [ADR-0002](ADR-0002-root-boundaries.md) | 대체됨 | 다섯 개 루트 모듈과 독립 환경 경계 사용; ADR-0006에서 대체 |
| [ADR-0003](ADR-0003-main-pr-flow.md) | 대체됨 | `develop` 없이 작업 브랜치에서 `main`으로 PR; ADR-0013에서 대체 |
| [ADR-0004](ADR-0004-cross-agent-instructions.md) | 승인됨 | 공용 에이전트 지침과 스킬을 Claude Code에서도 재사용 |
| [ADR-0005](ADR-0005-requirements-management.md) | 승인됨 | 제품 요구사항을 분할 정본과 얇은 라우터로 관리 |
| [ADR-0006](ADR-0006-ai-backend-boundary.md) | 승인됨 | AI와 Backend의 프레임워크·영속성 경계 분리 |
| [ADR-0007](ADR-0007-terraform-iac.md) | 부분 대체됨 | Terraform IaC 정본과 초기 IAM 접근 사용 |
| [ADR-0008](ADR-0008-dev-demo-runtime-and-delivery.md) | 부분 대체됨 | EC2 Backend·설치형 AI·RunPod 상위 구조 유지; 전달은 ADR-0011, RunPod 운영은 ADR-0020 적용 |
| [ADR-0009](ADR-0009-dev-demo-operating-constraints.md) | 부분 대체됨 | 2026-09-23 종료, CloudFront 동일 origin, Billing 미사용과 pgvector migration 경계 |
| [ADR-0010](ADR-0010-pr-policy-ai-review-discord.md) | 부분 대체됨 | GitHub Actions 기반 결정적 분할·통합 PR AI 리뷰와 Discord 결과 전달 |
| [ADR-0011](ADR-0011-dev-cicd-pipeline-modes.md) | 부분 대체됨 | dev 자동 통합과 Backend·Frontend 수동 독립 CodePipeline 운영 |
| [ADR-0012](ADR-0012-retain-iam-access.md) | 승인됨 | Identity Center 전환을 폐기하고 기존 개인 IAM·MFA·역할 접근 유지 |
| [ADR-0013](ADR-0013-dev-integration-pr-flow.md) | 승인됨 | `dev` 개발 통합, `main` 릴리스 PR과 Hong1008 기본 승인 책임 사용 |
| [ADR-0014](ADR-0014-f3-prototype-synthetic-input.md) | 승인됨 | F3 프로토타입 합성 입력의 마스킹 생략과 실사용 데이터 연결 전 종료 조건 |
| [ADR-0015](ADR-0015-environment-configuration-ownership.md) | 부분 대체됨 | tracked `.env.local`, 개인 `.env`, Terraform 공개 설정과 초기 write-only 비밀값 소유권 분리 |
| [ADR-0016](ADR-0016-pr-review-cross-chunk-evidence.md) | 승인됨 | 제한된 PR head 전체 파일·동일 PR 정책 근거 공유와 명시적 `high` 오탐 기각 |
| [ADR-0017](ADR-0017-shared-dev-development-session.md) | 승인됨 | 공유 AWS를 애플리케이션 dev로 분류하고 합성 고정 계정의 개발 세션만 허용 |
| [ADR-0018](ADR-0018-f3-save-trigger-anchor-card-scope.md) | 승인됨 | F1 저장 트리거를 앵커 포지션 카드까지로 한정하고 후보 조회·판정은 사용자 요청이 같은 실행을 이어받아 수행 |
| [ADR-0019](ADR-0019-minimal-error-observability.md) | 승인됨 | Backend 미처리 500과 AI 최종 실패만 기존 AWS 경로로 알리고 공개 오류·Frontend 복구 경계를 정규화 |
| [ADR-0020](ADR-0020-sllm-release-handoff.md) | 승인됨·코드 구현, 외부 자원 미적용 | 학습자의 bundle 전달, Infra의 private S3 승격, RunPod create/delete와 F2 offline 계약 사용 |
| [ADR-0021](ADR-0021-runpod-operations-and-secret-ownership.md) | 승인됨·코드 구현, 외부 자원 미적용 | RunPod 단일 bootstrap, Secrets Manager 값 정본, 읽기 전용 감시와 수동 reconcile 사용 |

이 인덱스에는 프로젝트 공통 및 모듈 간 ADR만 둔다. 모듈 내부 결정은 각 모듈 스킬의 `references/decisions/index.md`에서 관리한다.

LangGraph의 AI 모듈 내부 채택 범위는 [AI ADR-0002](../../../ai/references/decisions/ADR-0002-langgraph-adoption.md)에서 관리한다. Terraform의 루트·state 세부 기준은 [Infra ADR-0001](../../../infra/references/decisions/ADR-0001-terraform-layout-and-state.md)에서 관리한다. 개발·시연 자원과 전달 세부 기준은 [Infra ADR-0002](../../../infra/references/decisions/ADR-0002-dev-demo-aws-runpod-architecture.md)에서 관리한다.
