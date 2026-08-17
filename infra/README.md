# Infra

Terraform을 AWS 인프라 변경의 정본으로 사용한다. 현재 범위는 계정 baseline, 임시 운영 역할, 원격 state와 AWS 계정 연결까지다. 비용 Budget은 코드에 포함하지만 현재 계정에서는 조직 SCP로 비활성화한다. RDS, VPC, EC2, ECS, ECR, SQS, 업무용 S3와 RunPod는 만들지 않는다.

## 구조와 소유 범위

- `bootstrap/`: 계정 password policy, 계정·bucket public access block, 월 예산, `TerraformOperatorRole`, state bucket
- `environments/dev/`: AWS account/region data source와 출력만 포함하며 관리 자원은 없음
- `scripts/preflight.sh`: 도구 버전, 임시 자격 증명, 계정과 리전 검증
- `scripts/verify-account-link.sh`: state bucket 읽기와 dev init/validate/plan 검증

Terraform은 1.15.x, AWS Provider는 `~> 6.53` 호환 범위를 사용한다. 실제 두 번째 환경이나 반복 자원이 생기기 전에는 module과 workspace를 추가하지 않는다.

## 0. 사람의 1회 계정 설정

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
- `create_budget`: AWS Organizations 정책이 Budget 생성을 허용할 때 `true`; SCP가 `budgets:ModifyBudget`을 차단하면 `false`
- `budget_notification_email`: 예산 알림 주소; Terraform state에 포함되므로 state 접근을 제한
- `monthly_budget_amount`: AWS Budgets API의 USD 금액; 300,000원 월 한도는 적용 당일 환율로 USD 환산
- `expires_at`: 임시 IAM 방식과 개발 환경의 종료 예정일

## 3. local state로 bootstrap

S3 bucket은 자기 자신을 backend로 만들 수 없으므로 `backend.tf`를 제외한 임시 사본에서 최초 apply한다. 이 단계만 bootstrap 담당자의 직접 권한을 사용한다.

```bash
bootstrap_tmp="$(mktemp -d)"
bootstrap_vars="$(pwd)/infra/bootstrap/bootstrap.tfvars"

cp infra/bootstrap/versions.tf "$bootstrap_tmp/"
cp infra/bootstrap/providers.tf "$bootstrap_tmp/"
cp infra/bootstrap/variables.tf "$bootstrap_tmp/"
cp infra/bootstrap/main.tf "$bootstrap_tmp/"
cp infra/bootstrap/outputs.tf "$bootstrap_tmp/"

terraform -chdir="$bootstrap_tmp" init
AWS_PROFILE=skn30-bootstrap terraform -chdir="$bootstrap_tmp" plan \
  -var-file="$bootstrap_vars" \
  -var='use_operator_role=false' \
  -out=bootstrap.tfplan
```

plan에서 다음만 생성되는지 검토하고 승인을 받은 뒤 apply한다.

- account password policy와 account-level S3 public access block
- `create_budget=true`인 경우 월 비용 budget과 50/80/100% 이메일 알림
- `TerraformOperatorRole`과 승인 사용자용 assume/login policy 연결
- Terraform state bucket과 versioning, SSE-S3, ownership, public access, TLS, 90일 noncurrent version 정책

```bash
AWS_PROFILE=skn30-bootstrap terraform -chdir="$bootstrap_tmp" apply bootstrap.tfplan
cp "$bootstrap_tmp/terraform.tfstate" infra/bootstrap/terraform.tfstate
```

Terraform plan에는 알림 이메일이 민감 값으로 가려지는지 확인한다. RDS/VPC/EC2/ECS/ECR/SQS/RunPod 또는 업무용 S3가 보이면 apply하지 않는다.

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
export EXPIRES_AT=2026-10-31

infra/scripts/preflight.sh
terraform -chdir=infra/bootstrap validate
terraform -chdir=infra/bootstrap plan -var-file=bootstrap.tfvars

infra/scripts/verify-account-link.sh
```

dev root의 최초 plan은 data source 결과를 output state에 기록하는 변경만 보여야 한다. 검토 후 한 번 apply하고 다시 실행하면 `No changes`여야 한다. 이 과정에서 AWS 관리 자원은 생성되지 않는다.

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
