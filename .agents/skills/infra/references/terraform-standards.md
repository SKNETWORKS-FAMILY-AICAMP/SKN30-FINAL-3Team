---
status: 결정
updated: 2026-08-17
---

# Terraform 기준

## 버전과 root

- Terraform `1.15.x`와 HashiCorp AWS Provider `~> 6.53` 호환 범위를 사용한다.
- `infra/bootstrap`은 계정 기본 설정과 state bucket을 소유한다.
- `infra/environments/dev`는 공유 개발 환경 root이며 현재는 data source만 가진다.
- 두 번째 환경이나 반복되는 자원이 생기기 전에는 공통 module과 workspace를 만들지 않는다.

## State

- S3 backend의 `use_lockfile=true`를 사용하고 DynamoDB 잠금 테이블은 만들지 않는다.
- bootstrap과 dev는 각각 `bootstrap/terraform.tfstate`, `environments/dev/terraform.tfstate` key를 사용한다.
- state bucket에는 versioning, SSE-S3, public access block, TLS-only 정책과 `prevent_destroy`를 적용한다.
- 실제 backend bucket 이름은 `terraform init -backend-config`로 전달한다. 자격 증명은 backend 설정에 넣지 않는다.
- local state, plan, 실제 tfvars와 `.terraform/`은 Git에 저장하지 않는다.

## 계정·변수·출력

- AWS provider의 `allowed_account_ids`와 변수 validation으로 계정·리전 오적용을 차단한다.
- 실제 이메일, 사용자 ARN과 계정 ID는 커밋하지 않고 로컬 tfvars 또는 프로세스 변수로 전달한다.
- 비밀값과 전체 접속 URL은 Terraform output으로 만들지 않는다.
- 모든 지원 자원에는 가능한 경우 `Project`, `Environment`, `ManagedBy`, `Owner`, `ExpiresAt` 태그를 적용한다.

## 변경 절차

1. `terraform fmt -check -recursive infra`
2. 각 root의 `terraform init`과 `terraform validate`
3. `infra/scripts/preflight.sh`로 도구·계정·리전을 확인한다.
4. 저장한 plan을 검토하고 예상 자원·교체·삭제·비용을 PR에 기록한다.
5. 승인된 plan만 적용한다.
6. AWS 조회로 자원 속성을 확인하고 후속 plan이 비어 있는지 검증한다.
