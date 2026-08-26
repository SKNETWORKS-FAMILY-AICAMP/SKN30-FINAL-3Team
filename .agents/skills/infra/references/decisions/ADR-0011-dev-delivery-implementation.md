---
status: 결정
updated: 2026-08-24
---

# ADR-0011: 개발환경 delivery 구현 기준

- 상태: 승인됨
- 결정일: 2026-08-20
- 대체 범위: [ADR-0002](ADR-0002-dev-demo-aws-runpod-architecture.md)의 단일 수동 Pipeline 세부 결정
- 부분 대체: 환경 설정 materialization과 Discord 비밀 입력 방식은 [ADR-0013](ADR-0013-dev-environment-materialization.md)에서 대체
- 상위 결정: [프로젝트 ADR-0011](../../../project-wiki/references/decisions/ADR-0011-dev-cicd-pipeline-modes.md)

## 결정

### 공통 delivery 자원

- 기존 `AVAILABLE` 상태 `SKN30_FINAL` GitHub Connection을 Terraform resource와 import block으로 관리한다.
- Backend, Frontend와 통합 Pipeline의 source branch는 개발 통합 정본인 `dev`로 고정한다. `main`은 `dev → main` 릴리스 PR로만 갱신한다.
- 기존 Pipeline artifact S3를 Pipeline 이름별 prefix와 `frontend-releases/` backup prefix로 분리한다.
- Backend Verify, Backend image Build, Frontend Verify, Frontend release Build, Frontend deploy와 상호 상태 검사용 CodeBuild project를 역할별로 공유한다. Verify project는 output artifact를 만들지 않고 Build project는 테스트 DB를 시작하지 않는다.
- Pipeline service role은 세 개로 분리하고 CodeBuild와 CodeDeploy 역할은 기능별 최소 권한으로 공유한다.
- ECR tag는 전체 commit SHA이며 immutable repository에서 기존 SHA digest가 있으면 재사용한다. CodeDeploy artifact는 항상 repository URL과 digest를 함께 고정한다.
- Backend Verify의 PostgreSQL 15+pgvector image는 Docker Hub를 사용하지 않는다. ECR Public의 PostgreSQL base와 commit으로 고정한 pgvector source로 만들고 전용 private ECR에 immutable tag로 캐시한다. 이 repository 권한은 Backend Verify role에만 둔다.
- Pipeline 종류, revision, 실행 ID, image digest와 migration 검증 결과를 release manifest와 실행 이력에 남긴다.

### Backend 배포

- Verify는 AI·Backend lock 설치, format/lint/type/test, 빈 DB migration과 두 번째 no-op migration, lifecycle 계약 검사를 수행한다. image Build는 Verify 성공 후 별도 project에서 실행한다.
- root context multi-stage image는 Backend와 `brokerage-ai`를 각 lockfile로 non-editable 설치하고 비루트 UID 10001로 실행한다.
- CodeDeploy lifecycle은 graceful stop, revision 설치, digest 검증과 pull, runtime 설정 조립, IAM DB 인증 전진 migration, Compose 시작, local health 순서다.
- host config directory는 root `0700`, env 파일은 `0600`을 유지한다. 컨테이너에는 config directory 전체가 아니라 공개 RDS CA bundle 파일만 `/etc/ssl/certs/aws-rds-global-bundle.pem`으로 read-only mount하고 migration 전에 container readability를 검사한다.
- migration은 PostgreSQL advisory lock을 잡고 Yoyo를 실행한다. 실패하면 API·Worker를 시작하지 않으며 rollback에서 down migration을 실행하지 않는다.
- API, Worker와 one-shot migrate는 같은 digest를 사용한다. Worker는 비활성 계약만 배포한다.
- Launch Template은 Docker, Compose plugin, CodeDeploy agent와 CloudWatch agent를 설치하고 기동을 검증한다.
- 초기 검증 중 ASG health는 `EC2`이며 전체 배포 검증 후 `ELB`로 전환한다.

### Frontend 배포

- Verify는 clean install, 환경변수 우선순위 계약, typecheck와 원장 테스트까지만 수행한다. 별도 Build가 다시 clean install한 뒤 Vite release와 release 계약 검사를 수행하고 artifact를 만든다.
- Frontend는 runtime Dockerfile 없이 Vite `dist/client` artifact를 만든다.
- 현재 Backend의 CloudFront `/health/ready`를 먼저 확인한다.
- release manifest에 entry document, asset 목록, 크기와 SHA-256을 기록한다.
- hashed asset을 먼저 올리고 기존 asset을 즉시 삭제하지 않는다. `index.html`은 no-cache로 마지막에 교체한다.
- 이전 index와 manifest는 Pipeline artifact bucket에 저장한다. 배포 또는 invalidation 실패 시 이전 index를 복원한다.

### 충돌·알림·권한

- 첫 CodeBuild action이 다른 두 Pipeline의 최근 상태를 조회한다. `InProgress` 또는 `Stopping`이면 현재 실행을 실패시킨다.
- 상태 확인과 다음 action 사이 race는 남으며 DynamoDB lock은 도입하지 않는다.
- EC2 role에는 artifact read, ECR pull, runtime Secret/Parameter read와 `app_migrator`의 `rds-db:connect`만 추가한다. `GetParametersByPath`에는 prefix 하위 ARN뿐 아니라 API가 평가하는 prefix 자체 ARN도 허용한다.
- Discord webhook의 container와 값 반영 경계는 ADR-0013을 따른다.
- EventBridge Pipeline/CodeDeploy 상태 이벤트를 기존 SNS에 게시하고 Lambda가 revision, 실패 action과 Console 링크를 조립한다.

## 적용 gate

1. [Infra ADR-0012](ADR-0012-existing-iam-operators.md)의 기존 IAM 운영자 목록과 policy attachment를 plan에서 확인한다.
2. `integrated_pipeline_detect_changes=false`, `app_asg_health_check_type=EC2`로 최초 적용한다.
3. Backend, Frontend, 통합 수동 실행과 실패 주입 rollback·복원·Discord 알림을 검증한다.
4. 후속 승인 plan에서 통합 변경 감지만 켜고 ASG health를 `ELB`로 전환한다.
5. 실제 apply는 저장소 구현과 별도 승인 작업이다.

## 제외

- Terraform apply Pipeline
- DynamoDB 분산 잠금
- Frontend runtime container
- 운영 Worker 활성화
- DB 자동 down migration
