---
status: 결정
updated: 2026-08-24
---

# ADR-0011: 개발환경 통합·Backend·Frontend CI/CD 모드

- 상태: 부분 대체됨
- 결정일: 2026-08-20
- 대체 범위: [ADR-0008](ADR-0008-dev-demo-runtime-and-delivery.md)의 수동 시작·Manual approval 전달 결정
- 후속 대체: [ADR-0013](ADR-0013-dev-integration-pr-flow.md)이 Pipeline source 기준을 `dev`로 대체하고, [ADR-0015](ADR-0015-environment-configuration-ownership.md)가 Discord webhook의 수동 주입 방식을 ignored tfvars와 Terraform write-only version으로 대체

## 맥락

일상적인 개발 통합 변경은 Frontend와 Backend를 호환되는 한 revision으로 자동 배포해야 하고, 장애 복구와 부분 재배포에는 특정 전체 commit SHA를 선택할 수 있는 독립 도구가 필요하다. 한 대의 ASG에 대한 인플레이스 Backend 배포와 정적 Frontend 교체가 동시에 실행되면 순서와 호환성이 깨질 수 있다. 현재 source branch는 [ADR-0013](ADR-0013-dev-integration-pr-flow.md)의 `dev`를 따른다.

## 결정

- CodePipeline V2 `QUEUED` Pipeline을 `dev-integrated`, `dev-backend`, `dev-frontend` 세 개 둔다.
- 통합 Pipeline만 `dev` 변경을 자동 감지한다. Backend와 Frontend 독립 Pipeline은 `DetectChanges=false`인 운영자 수동 실행이며 최신 `dev` 또는 전체 `COMMIT_ID` override를 받는다.
- Pipeline 내부 Manual approval은 두지 않는다. 독립 Pipeline 시작 권한 자체를 운영자 승인으로 본다.
- 통합 Pipeline은 같은 Source artifact에서 Backend+AI와 Frontend의 `Verify`를 병렬 실행한 뒤, Backend image와 Frontend release의 `Build`를 병렬 실행한다. 검증 단계는 배포 artifact를 만들지 않으며 Build 단계는 테스트 DB를 사용하지 않는다. 배포는 DB 전진 migration, Backend와 Worker, health, Frontend index-last 순서다.
- Backend 독립 Pipeline은 migration과 Backend만 변경한다. Frontend 독립 Pipeline은 현재 Backend readiness를 확인한 뒤 S3와 CloudFront만 변경한다.
- 모든 Pipeline은 첫 단계에서 다른 두 Pipeline의 최근 실행 상태를 조회하고 `InProgress` 또는 `Stopping`이면 실패한다. 조회와 실제 배포 사이의 짧은 race는 수용하며, 독립 실행 전 운영자가 통합 Pipeline 상태를 확인한다.
- Backend 실패는 마지막 정상 CodeDeploy revision으로 자동 롤백하고 DB down migration은 실행하지 않는다.
- Frontend는 기존 `index.html`과 release manifest를 보관하고 asset-first/index-last로 배포한다. 교체 또는 invalidation 실패 시 이전 index를 복원하고 다시 invalidation한다.
- Pipeline과 CodeDeploy 결과는 EventBridge, 기존 SNS, Lambda를 통해 Discord로 전달한다. webhook 값의 현재 주입 방식은 [ADR-0015](ADR-0015-environment-configuration-ownership.md)를 따른다.
- Terraform apply는 애플리케이션 Pipeline에 포함하지 않는다.

## 안전 조건

- Breaking API 변경은 호환되는 단계적 변경 또는 통합 Pipeline으로만 배포한다.
- Worker는 `WORKER_ENABLED=false`에서 DB readiness와 graceful shutdown만 제공하고 작업을 claim하지 않는다. F3 handler 코드는 `true` polling을 지원하지만 현재 배포 Parameter 기본값은 `false`로 유지하며, 운영 Provider 선택과 활성화는 별도 적용한다.
- Backend Verify는 disposable PostgreSQL의 `TEST_DB_URL`을 필수로 주입해 DB 통합 검사를 skip 없이 실행한다. Frontend Verify는 typecheck와 원장 테스트를 수행하고, 별도 Frontend Build가 Vite release와 release 계약 테스트를 수행한다.
- 통합 자동 감지는 독립 Pipeline, rollback, Frontend 복원과 알림 실패 주입 검증 후에만 켠다.
- Pipeline 수동 운영 권한은 [ADR-0012](ADR-0012-retain-iam-access.md)에 따라 승인된 기존 IAM 사용자에게 최소 권한 policy로 연결한다.
- 도메인과 origin TLS가 없는 동안 합성·비식별 데이터만 사용한다.

## 결과

일상 변경은 `dev` 기준 자동 통합 배포가 되고, Backend 또는 Frontend만 복구할 수 있는 명시적 수동 경로가 생긴다. `main`은 별도 릴리스 기준으로 유지한다. 세 Pipeline의 `QUEUED` 모드는 같은 Pipeline 내부 실행을 직렬화하지만 Pipeline 간 완전한 원자 잠금은 제공하지 않는다. DynamoDB lock 비용과 운영 복잡도를 추가하지 않는 대신 짧은 race와 운영자 사전 확인을 수용한다.

세부 IAM, lifecycle, artifact와 단계 구성은 [Infra ADR-0011](../../../infra/references/decisions/ADR-0011-dev-delivery-implementation.md)을 따른다.
