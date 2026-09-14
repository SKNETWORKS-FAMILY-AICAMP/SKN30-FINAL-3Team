---
status: 결정
updated: 2026-08-17
---

# Terraform 기준

## 버전과 root

- Terraform `1.15.x`와 HashiCorp AWS Provider `~> 6.53` 호환 범위를 사용한다.
- `infra/bootstrap`은 계정 기본 설정과 state bucket을 소유한다.
- `infra/environments/dev`는 공유 개발 환경 root다. 적용 여부는 [인벤토리](resource-inventory.md)를 따른다.
- 두 번째 환경이나 반복되는 자원이 생기기 전에는 공통 module과 workspace를 만들지 않는다.

## State

- S3 backend의 `use_lockfile=true`를 사용하고 DynamoDB 잠금 테이블은 만들지 않는다.
- bootstrap과 dev는 각각 `bootstrap/terraform.tfstate`, `environments/dev/terraform.tfstate` key를 사용한다.
- state bucket에는 versioning, SSE-S3, public access block, TLS-only 정책과 `prevent_destroy`를 적용한다.
- 실제 backend bucket 이름은 `terraform init -backend-config`로 전달한다. 자격 증명은 backend 설정에 넣지 않는다.
- local state, plan, 실제 tfvars와 `.terraform/`은 Git에 저장하지 않는다.
- just의 saved plan은 600 권한·입력 fingerprint·24시간 유효기간으로 관리한다. 입력 변경·만료 시 새 plan을 검토한다.
- fingerprint는 선택한 bootstrap/dev root와 `infra/scripts`를 재귀 순회하고 `infra/justfile`을 포함한다.
  dev는 `serving`·`deploy`·`runpod`·`delivery`도 포함한다. 입력 확장자는 `.tf`, `.tfvars`, `.json`, `.hcl`,
  `.py`, `.sh`, `.tftpl`, `.tpl`, `.policy`, `.txt`, `.sql`, `.toml`, `.yml`, `.yaml`, `.Dockerfile`이며
  `Dockerfile`, `Dockerfile.*`, `.dockerignore`, `.terraform.lock.hcl`, `justfile`도 명시 포함한다.
  숨김 파일·디렉터리(위 명시 파일 제외), tests·__pycache__·dist·node_modules·plan sidecar는 제외한다.
  범위 안의 symlink 입력 파일·디렉터리는 거부한다. 외부 module 경로를 자동 추적하는 의존성 해석기는 아니다.
- 새 입력 형식을 도입하면 `plan_guard.py` 수집 규칙과 stale 회귀 테스트를 함께 갱신한다.
  metadata schema 2 이전에 seal한 기존 plan은 재생성·재검토한다. sidecar만 다시 seal해 승인을 이전하지 않는다.
- `dev-first-deploy.tfplan`은 seal/check 모두 saved plan JSON의 실제 변수와 예정 CodeDeploy 대상을 검사한다.
  `maintenance`, edge/GPU 활성화, ASG 연결 해제, 정확한 앱 Project·Environment·Name AND 태그가 필수다.
  JSON 원문은 메모리에서만 검사한다. 일상 plan의 `automatic` 기본값은 유지하며 seal은 적용 승인이 아니다.
- GPU 프로필은 ignored `gpu-profiles.auto.tfvars.json`, 생성 대상은 `serving-capacity.auto.tfvars.json`이다. 검증용 auto 입력을 중복으로 남기지 않는다.

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
