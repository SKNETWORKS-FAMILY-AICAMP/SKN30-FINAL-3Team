# Infra

Terraform을 AWS 인프라 변경의 정본으로 사용한다. 현재 계정에서는 AWS Budget·Cost Anomaly Detection을 사용할 수 없으므로 Billing 자원을 만들지 않는다. 기존 선택적 Budget 입력은 현재 state 호환을 위해 남아 있지만 `create_budget=false`만 허용하며, 2026-09-23까지 누적 300,000원은 자동 집행 없는 운영 참고 상한이다. workload 자원은 plan과 별도 승인 없이 만들지 않는다.

현재 AWS 계정 bootstrap과 S3 원격 state 이관은 완료됐다. 새 PC에서는 bootstrap을 다시 실행하지 않고 아래의 로컬 연결 스크립트를 사용한다.

Terraform 관리는 다음 세 요소를 함께 사용한다. S3 state에는 Terraform 코드가 저장되지 않으므로 항상 저장소의 최신 승인 코드를 먼저 받아야 한다.

```text
Git의 Terraform 코드 + S3 원격 state + 실제 AWS 자원
```

## 구조와 소유 범위

- `bootstrap/`: 계정 password policy, 계정·bucket public access block, 호환용 비활성 Budget 블록, `TerraformOperatorRole`, `team-readonly` IAM 그룹과 `ReadOnlyAccess` 연결, state bucket
- `environments/dev/`: 계정 guard, 네트워크·보안, S3·ECR·RDS·설정, EC2·ALB·ASG, 관측성과 private S3·CloudFront Frontend; 현재 코드 구현만 완료되고 미적용
- `scripts/setup-local.sh`: 새 PC의 AWS profile, 로컬 backend/dev 변수, Terraform init과 연결 검증
- `scripts/preflight.sh`: 도구 버전, 임시 자격 증명, 계정과 리전 검증
- `scripts/verify-account-link.sh`: state bucket 읽기와 dev init/validate/plan 검증

Terraform은 1.15.x, AWS Provider는 `~> 6.53` 호환 범위를 사용한다. 실제 두 번째 환경이나 반복 자원이 생기기 전에는 module과 workspace를 추가하지 않는다.

현재 runtime 기본값은 AL2023 x86_64, `t3.medium`, encrypted gp3 40 GiB, ASG 1대와 SSM 전용 접속이다. CloudWatch log group 5개는 14일 보존하고 alarm 5개를 subscription 없는 SNS topic에 연결한다. 애플리케이션 artifact·secret·migration delivery와 RunPod Terraform은 아직 포함하지 않는다. 세부 계약은 [Infra ADR-0004](../.agents/skills/infra/references/decisions/ADR-0004-dev-runtime-and-observability-baseline.md)를 따른다.

## 새 PC 빠른 연결

이 절차는 계정 bootstrap을 다시 실행하지 않는다. 사전에 개인 IAM 사용자, console 접근, OTP MFA와 `TerraformOperatorRole` assume 권한이 있어야 한다.

AWS CLI 2.36 이상과 `.terraform-version`의 Terraform을 설치하고 저장소의 최신 승인 코드를 받은 뒤 실행한다.

```bash
infra/scripts/setup-local.sh \
  --account-id 398563707017 \
  --expires-at 2026-09-23
```

스크립트는 다음 작업만 수행한다.

- `skn30-bootstrap`, `skn30-session` profile 설정과 `aws login`
- 로그인 계정·사용자·서울 리전 검증
- 커밋하지 않는 bootstrap/dev `backend.hcl`과 dev `dev.tfvars` 생성
- 두 Terraform root의 `init -reconfigure`
- `TerraformOperatorRole` assume, state bucket 보안 설정과 dev 빈 plan 검증

이미 `aws login` 세션이 유효하면 `--skip-login`을 사용할 수 있다. 기존 로컬 파일과 생성할 내용이 다르면 스크립트는 중단하며, 내용을 직접 검토한 경우에만 `--force`로 교체한다.

```bash
infra/scripts/setup-local.sh \
  --account-id 398563707017 \
  --expires-at 2026-09-23 \
  --skip-login
```

스크립트는 `bootstrap.tfvars`를 만들거나 IAM 권한을 추가하지 않으며 `terraform apply`를 실행하지 않는다. 다른 팀원을 추가하려면 기존 운영자가 전체 `operator_user_arns`를 보존한 bootstrap plan을 별도로 검토하고 적용해야 한다.

팀원의 일반 읽기 권한은 Terraform이 관리하는 `team-readonly` IAM 그룹으로 제공한다. IAM 사용자 생성·삭제, 그룹 멤버 추가·제거, console password와 MFA 등록은 Terraform 범위가 아니며 AWS 콘솔에서 개인별로 수행한다. 장기 access key는 만들지 않는다.

state bucket은 개인 IAM 사용자의 직접 접근을 거부한다. 직접 `aws s3` 명령이 `403`을 반환할 수 있으며, Terraform과 검증 스크립트가 `TerraformOperatorRole`을 assume해 접근하는 것이 정상이다.

## 최초 1회 AWS 계정 설정

현재 계정에서는 완료된 절차다. 새 PC 연결을 위해 다시 수행하지 않는다.

1. root 계정에 MFA, 결제·보안 연락처를 설정하고 root access key가 없음을 확인한다.
2. 공유 계정 대신 팀원별 IAM 사용자를 만들고 console password와 OTP MFA를 등록한다.
3. 최초 Infra 담당자에게만 bootstrap용 관리자 권한과 AWS 관리형 `SignInLocalDevelopmentAccess`를 임시 부여한다.
4. 운영 자원 배포 전 Identity Center 전환 여부를 재검토한다.

MFA 장치를 Terraform으로 생성하면 seed가 state에 남을 수 있으므로 수동으로 등록한다. Terraform은 account password policy와 `aws login`에서 발급된 Sign-In session만 허용하는 역할 trust policy를 관리한다.

## 1. 도구와 임시 로그인

AWS CLI 2.36 이상과 `.terraform-version`의 Terraform을 설치한다. 장기 access key를 만들거나 저장소, shell profile, tfvars에 기록하지 않는다.

```bash
aws configure set region ap-northeast-2 --profile skn30-bootstrap
aws login --profile skn30-bootstrap
aws sts get-caller-identity --profile skn30-bootstrap
```

Terraform AWS SDK가 로그인 자격 증명을 확실히 읽도록 `skn30-session`을 process credential profile로 만든다.

```bash
aws configure set region ap-northeast-2 --profile skn30-session
aws configure set credential_process \
  'aws configure export-credentials --profile skn30-bootstrap --format process' \
  --profile skn30-session
```

bootstrap 전에는 `AWS_PROFILE=skn30-bootstrap`, 역할 생성 후에는 `AWS_PROFILE=skn30-session`을 사용한다. `preflight.sh`는 환경변수나 profile의 정적 access key를 거부한다.

## 2. 실제 변수 파일 준비

예시를 복사하고 실제 값은 커밋하지 않는다.

```bash
cp infra/bootstrap/example.tfvars infra/bootstrap/bootstrap.tfvars
cp infra/environments/dev/example.tfvars infra/environments/dev/dev.tfvars
```

- `target_account_id`: 전용 계정의 12자리 ID
- `operator_user_arns`: 공유 사용자가 아닌 승인된 개인 IAM 사용자 ARN
- `create_budget`: 현재 계정에서는 반드시 `false`
- `budget_notification_email`: 기존 bootstrap 입력 호환용이며 `create_budget=false`에서는 사용하지 않음
- `monthly_budget_amount`: 기존 bootstrap 입력 호환용이며 운영 비용 한도로 해석하지 않음
- `expires_at`: 임시 IAM 방식과 개발 환경의 종료 예정일

## 3. local state로 bootstrap

최초 계정 구축에서 한 번만 실행한다. S3 bucket은 자기 자신을 backend로 만들 수 없으므로 `backend.tf`를 제외한 임시 사본에서 최초 apply한다. 이 단계만 bootstrap 담당자의 직접 권한을 사용한다.

```bash
bootstrap_tmp="$(mktemp -d)"
bootstrap_vars="$(pwd)/infra/bootstrap/bootstrap.tfvars"

for bootstrap_file in versions providers variables locals account-baseline operator-access team-readonly-access state-storage budget outputs; do
  cp "infra/bootstrap/${bootstrap_file}.tf" "$bootstrap_tmp/"
done

terraform -chdir="$bootstrap_tmp" init
AWS_PROFILE=skn30-bootstrap terraform -chdir="$bootstrap_tmp" plan \
  -var-file="$bootstrap_vars" \
  -var='use_operator_role=false' \
  -out=bootstrap.tfplan
```

plan에서 다음만 생성되는지 검토하고 승인을 받은 뒤 apply한다.

- account password policy와 account-level S3 public access block
- 현재 계정에서는 Billing 자원을 생성하지 않으며 `create_budget=false` validation이 이를 차단함
- `TerraformOperatorRole`과 승인 사용자용 assume/login policy 연결
- `team-readonly` IAM 그룹과 AWS 관리형 `ReadOnlyAccess` 정책 연결; 사용자와 그룹 멤버십은 포함하지 않음
- Terraform state bucket과 versioning, SSE-S3, ownership, public access, TLS, 90일 noncurrent version 정책

```bash
AWS_PROFILE=skn30-bootstrap terraform -chdir="$bootstrap_tmp" apply bootstrap.tfplan
cp "$bootstrap_tmp/terraform.tfstate" infra/bootstrap/terraform.tfstate
```

bootstrap plan에는 RDS/VPC/EC2/ECS/ECR/SQS/RunPod 또는 업무용 S3가 없어야 한다. 이런 workload 자원이 보이면 apply하지 않는다.

## 4. 운영 역할과 원격 state로 전환

두 backend root마다 커밋하지 않는 `backend.hcl`을 만든다.

```hcl
bucket  = "skn30-final-3team-tfstate-<account-id>-ap-northeast-2"
profile = "skn30-session"
assume_role = {
  role_arn     = "arn:aws:iam::<account-id>:role/TerraformOperatorRole"
  session_name = "terraform-state"
  duration     = "1h"
}
```

동일한 내용을 `infra/bootstrap/backend.hcl`과 `infra/environments/dev/backend.hcl`에 저장한 뒤 MFA로 역할 assume이 가능한지 확인한다.

```bash
target_account_id="123456789012"
AWS_PROFILE=skn30-session aws sts assume-role \
  --role-arn "arn:aws:iam::${target_account_id}:role/TerraformOperatorRole" \
  --role-session-name account-link-check >/dev/null

AWS_PROFILE=skn30-session terraform -chdir=infra/bootstrap init \
  -migrate-state \
  -backend-config=backend.hcl
```

이관 승인을 확인한 뒤 원격 state가 읽히고 로컬 state가 남지 않았는지 검사한다.

```bash
AWS_PROFILE=skn30-session terraform -chdir=infra/bootstrap state pull >/dev/null
find infra/bootstrap -maxdepth 1 -name '*.tfstate*' -print
```

이관과 원격 조회가 모두 성공한 다음에만 임시 사본과 발견된 local state를 삭제한다. 최초 담당자의 직접 관리자 권한도 이 시점 이후 제거한다.

## 5. bootstrap drift와 dev 계정 연결

```bash
export AWS_PROFILE=skn30-session
export TARGET_ACCOUNT_ID="123456789012"
export EXPIRES_AT=2026-09-23

infra/scripts/preflight.sh
terraform -chdir=infra/bootstrap validate
terraform -chdir=infra/bootstrap plan -var-file=bootstrap.tfvars

infra/scripts/verify-account-link.sh
```

dev root에는 현재 네트워크·보안·S3·ECR·RDS·설정, EC2·ALB·ASG와 관측성이 구현돼 있으므로 plan은 비용 발생 자원을 포함한다. 마지막 검토 plan은 96개 추가, 변경 0개, 삭제 0개였으며 사람의 별도 승인 전에는 apply하지 않는다.

잘못된 계정 ID나 `ap-northeast-2` 외 리전을 넣으면 provider/variable guard가 plan을 중단해야 한다.

## 6. 변경 절차

모든 변경은 다음 순서로 수행한다.

```text
terraform fmt → terraform validate → terraform plan → 사람 승인
→ terraform apply → AWS 조회 검증 → 빈 후속 plan으로 drift 확인
```

Terraform 밖에서 관리 자원을 변경하지 않는다. 긴급 수동 변경이 있었다면 다음 작업 전에 코드와 state를 일치시킨다. plan, state, 실제 tfvars, backend 설정, 자격 증명과 이메일은 커밋하지 않는다.

## 7. 종료와 복구

```bash
aws logout --profile skn30-bootstrap
unset AWS_PROFILE TARGET_ACCOUNT_ID EXPIRES_AT
```

- 세션 만료: `aws login --profile skn30-bootstrap` 후 다시 실행한다.
- state lock: 다른 실행이 끝났음을 확인하고 lock ID를 기록한 뒤에만 `terraform force-unlock`한다.
- state 복구: S3 object version을 먼저 확인하고 복원 계획을 승인받는다.
- backend 이관 실패: 임시 사본과 local state를 보존하고 원격 object 상태를 확인한 뒤 `terraform init -migrate-state`를 재시도한다.
- state bucket은 `prevent_destroy` 대상이다. 프로젝트 종료 시에도 별도 백업·폐기 승인을 거친다.
