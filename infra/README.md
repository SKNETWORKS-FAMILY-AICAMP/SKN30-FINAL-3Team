# Infra

Terraform을 AWS 인프라 변경의 정본으로 사용한다. 현재 계정에서는 AWS Budget·Cost Anomaly Detection을 사용할 수 없으므로 Billing 자원을 만들지 않는다. 기존 선택적 Budget 입력은 현재 state 호환을 위해 남아 있지만 `create_budget=false`만 허용하며, 2026-09-23까지 누적 300,000원은 자동 집행 없는 운영 참고 상한이다. workload 자원은 plan과 별도 승인 없이 만들지 않는다.

`environments/dev`는 prod를 대신하는 운영 환경이 아니라 공유 애플리케이션 dev 환경이다. CloudFront 주소는 공개되어 있으며 합성·비식별 데이터만 허용한다.

현재 AWS 계정 bootstrap과 S3 원격 state 이관은 완료됐다. 새 PC에서는 bootstrap을 다시 실행하지 않고 아래의 로컬 연결 스크립트를 사용한다.

Terraform 관리는 다음 세 요소를 함께 사용한다. S3 state에는 Terraform 코드가 저장되지 않으므로 항상 저장소의 최신 승인 코드를 먼저 받아야 한다.

```text
Git의 Terraform 코드 + S3 원격 state + 실제 AWS 자원
```

## 구조와 소유 범위

- `bootstrap/`: 계정 password policy, 계정·bucket public access block, 호환용 비활성 Budget 블록, `TerraformOperatorRole`, `team-readonly` IAM 그룹과 `ReadOnlyAccess` 연결, state bucket
- `environments/dev/`: 계정 guard, 네트워크·보안, S3·ECR·RDS·설정, EC2·ALB·ASG, 관측성, private S3·CloudFront Frontend와 `team-db-tunnel` 개발 DB 터널 접근; 기존 dev 자원은 적용됐고 deep lifecycle과 이번 환경설정·delivery 변경은 plan·apply 전
- `justfile`: 반복되는 검증, plan/apply와 DB 운영 명령의 진입점
- `scripts/setup-local.sh`: 새 PC의 AWS profile, 로컬 backend/dev 변수, Terraform init과 연결 검증
- `scripts/preflight.sh`: 도구 버전, 임시 자격 증명, 계정과 리전 검증
- `scripts/verify-account-link.sh`: state bucket·원격 state 읽기와 dev init/validate 검증
- `scripts/manage_db_access.py`: DB 역할, runtime Secret, IAM migration과 검증 관리
- `scripts/manage_dev_power.py`: 지정 Infra 운영자의 dev RDS·ASG start/stop/status 관리

Terraform은 1.15.x, AWS Provider는 `~> 6.53` 호환 범위를 사용한다. 실제 두 번째 환경이나 반복 자원이 생기기 전에는 module과 workspace를 추가하지 않는다.

## 사전 요구 사항
- [just](https://github.com/casey/just)
- uv
- [aws cli](https://docs.aws.amazon.com/ko_kr/cli/latest/userguide/getting-started-install.html)
- [session manager](https://docs.aws.amazon.com/systems-manager/latest/userguide/install-plugin-debian-and-ubuntu.html): cli 설치 후 세션 매니저 플러그인 설치
- PostgreSQL 15 `psql`: 공유 dev F3 합성 seed 적용에 필요
- python 3.13
- [terraform](https://developer.hashicorp.com/terraform/install)

```
# python
python3 -m venv .venv
source .venv/bin/activate

# uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# just
uv tool install rust-just
```

## 일상 사용

DB 명령에는 Session Manager plugin도 필요하다. 모든 `just` 명령은 `infra/`에서 실행한다.

계정 ID는 명령마다 전달하지 않고 Git에서 제외되는 `.env`로 관리한다. 실제 자격 증명, access key와 Secret은 넣지 않는다.

```bash
cd infra
cp .env.example .env
```

`.env`의 `TARGET_ACCOUNT_ID`를 실제 12자리 AWS 계정 ID로 바꾼 뒤 사용 가능한 명령을 확인한다.

```bash
just
```

### 새 PC 연결

이 절차는 계정 bootstrap을 다시 실행하지 않는다. 사전에 개인 IAM 사용자, console 접근, OTP MFA와 `TerraformOperatorRole` assume 권한이 있어야 한다.

```bash
just setup 2026-09-23
```

유효한 `aws login` 세션을 재사용하려면 다음 명령을 사용한다.

```bash
just setup-existing 2026-09-23
```

이 명령은 AWS profile, 커밋하지 않는 `backend.hcl`과 `dev.tfvars`, Terraform init과 읽기 전용 연결 검증만 수행한다. AWS 자원을 생성하거나 변경하지 않는다. 기존 `dev.tfvars`가 있으면 `target_account_id`와 `expires_at`이 요청값과 같은지만 검증하고 계정 블록을 포함한 전체 내용을 보존한다. 두 기본값이 다르면 `--force`로도 자동 수정하지 않고 중단한다.

### 수동 비밀값 준비

Setup과 `just verify-account`는 비밀값 없이 실행할 수 있다. 실제 dev plan 전에 AI provider key와
delivery·Alarm용으로 각각 만든 Discord webhook처럼 사람이 제공하는 비밀값을 별도 ignored
tfvars에 준비한다.

```bash
cp environments/dev/secrets.example.tfvars environments/dev/secrets.auto.tfvars
chmod 600 environments/dev/secrets.auto.tfvars
```

- `ai_provider_api_keys`: `AI_OPENAI_API_KEY`, `AI_VLLM_LLM_API_KEY`, `AI_VLLM_STT_API_KEY`는 필수이고 Embedding 등 다른 vLLM API key는 필요할 때 추가한다.
- `discord_webhook_url`: 기존 CodePipeline·CodeDeploy 알림용 Discord webhook HTTPS URL을 입력한다.
- `alarm_discord_webhook_url`: 사람이 Discord에서 CloudWatch Alarm 전용 webhook을 새로 생성한 뒤 그 HTTPS URL을 입력한다. 기존 delivery webhook을 복사하거나 재사용하지 않는다.
- 각 `*_secret_version`: 비밀값을 바꿀 때 함께 1씩 증가시킨다.

Terraform은 `.auto.tfvars`를 plan과 saved-plan apply에서 자동으로 다시 읽는다. Ephemeral 비밀값은 plan/state에 저장되지 않으므로 승인된 plan과 apply 사이에 이 파일을 수정하지 않는다.

### Terraform 변경

```bash
just check
just dev-plan
just dev-show
just dev-apply
just dev-drift
just dev-deep-stop-plan
just dev-deep-stop-show
just dev-deep-stop
just dev-deep-drift
just dev-deep-start-plan
just dev-deep-start-show
just dev-deep-start
just dev-deep-status
just dev-destroy-plan
just dev-destroy-show
just dev-destroy
```

`dev-show`로 저장된 plan의 자원, 교체, 삭제와 비용을 검토하고 승인을 받은 뒤에만 `dev-apply`를 실행한다. deep 전원 명령도 전용 saved plan을 먼저 만들고 `show`로 전체 변경을 검토해야 하며, 실행 시 다른 시점에 만든 일반 `dev.tfplan`을 사용하지 않는다. dev root가 소유한 환경을 영구 삭제할 때는 `dev-destroy-plan`으로 `dev-destroy.tfplan`을 생성하고 `dev-destroy-show`로 삭제 대상과 보존 대상을 검토한 뒤 `dev-destroy`를 실행한다. bootstrap root의 state bucket과 계정 baseline은 이 destroy plan의 대상이 아니다. bootstrap root 변경에는 같은 순서의 `bootstrap-plan`, `bootstrap-show`, `bootstrap-apply`, `bootstrap-drift`를 사용한다. apply와 destroy recipe는 실행 전에 추가 확인을 요구한다.

`dev-plan`, `dev-apply`, `dev-drift`, 모든 deep plan/apply/drift 명령, `dev-destroy-plan`, `dev-destroy`는 `secrets.auto.tfvars`가 비어 있지 않은 일반 파일이고 group/other 권한 bit가 모두 꺼져 있을 때만 시작한다(`0600` 또는 `0400` 계열). Setup, `verify-account`, 저장된 plan의 `show`와 상태 조회에는 이 gate를 적용하지 않는다. AI·Discord 평문이 `dev.tfplan`, `terraform show -json` 또는 state에 나타나면 apply하지 않는다.

`just fmt`는 Terraform 파일을 수정하므로 포맷이 필요할 때만 실행한다. `just verify-account`는 state와 AWS 계정 연결을 읽기 전용으로 검증한다.

다른 팀원을 추가하려면 기존 운영자가 전체 `operator_user_arns`를 보존한 bootstrap plan을 검토하고 적용해야 한다. IAM 사용자 생성·삭제, 그룹 멤버 추가·제거, console password와 MFA 등록은 Terraform 범위가 아니며 AWS 콘솔에서 개인별로 수행한다. 장기 access key는 만들지 않는다.

### 개발 환경 시작과 정지

Terraform 적용 후 지정 Infra 운영자만 기존 `TerraformOperatorRole`로 공유 개발 환경을 제어한다. 일반 팀원과 `team-db-tunnel` 그룹에는 start/stop 권한을 추가하지 않으며 AWS 계정 root 자격 증명은 계속 거부한다.

```bash
just dev-status
just dev-stop
just dev-start
```

`dev-stop`은 배포, migration, API 요청과 Worker 작업이 끝났음을 확인한 뒤 실행한다.

1. ASG desired capacity를 0으로 바꾸고 EC2 종료를 기다린다.
2. RDS를 정지하고 `stopped` 상태를 기다린다.

`dev-start`는 역순으로 복구한다.

1. RDS를 시작하고 `available` 상태를 기다린다.
2. ASG desired capacity를 1로 바꾼다.
3. EC2 `InService`와 SSM `Online` 상태를 기다린다.
4. ALB target 상태를 결과에 포함한다.

ASG 축소는 EC2 정지가 아니라 종료이며 다음 시작에는 Launch Template으로 새 인스턴스를 만든다. 로컬 root volume은 보존되지 않는다. 현재 delivery 구현 전에는 새 인스턴스에 애플리케이션이 자동 배포되지 않으므로 ALB target 상태는 정보로만 출력한다.

RDS 정지는 임시 개발 비용 절감 기능이다. 데이터, endpoint와 설정은 유지되지만 스토리지와 백업, ALB, public IPv4 등 잔여 비용은 계속 발생한다. RDS는 7일 연속 정지 후 자동으로 시작되므로 장기 휴무에는 상태를 다시 확인한다. 자세한 제한은 [AWS RDS 정지 문서](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_StopInstance.html)를 따른다.

여러 날 이상 사용하지 않을 때는 별도의 deep lifecycle로 ALB 고정비와 ALB가 사용하는 public IPv4 두 개의 비용까지 중지한다. CloudFront distribution은 삭제하지 않고 비활성화하므로 distribution ID와 기본 domain, private S3 origin은 유지된다. ALB target group, security group, ASG, Launch Template, IAM, CodeDeploy와 저장 데이터도 유지된다.

Deep stop은 다음 순서로 실행한다.

```bash
just dev-deep-stop-plan
just dev-deep-stop-show
just dev-deep-stop
just dev-deep-status
just dev-deep-drift
```

`dev-deep-stop`은 먼저 ASG를 0으로 내리고 RDS를 정지한 다음, 검토한 `dev-deep-stop.tfplan`으로 CloudFront를 비활성화하고 ALB·listener·ALB alarm 두 개를 제거한다. CloudFront의 ALB origin과 API behavior, Backend `HTTP_ALLOWED_HOSTS`의 ALB DNS도 함께 제거되며 ALB service-managed public IPv4는 AWS가 자동 반납한다. 정상 active 상태라면 네 edge 자원이 `destroy`여야 한다. 이미 원격에서 수동 삭제된 자원은 refresh drift로 plan에서 생략될 수 있으므로 실제 존재 여부와 state 정리를 확인하고, 다른 add·change·destroy가 보이면 기존 미적용 root 변경이나 provider의 dependency 재계산인지 `show`에서 개별 검토한다.

Deep start는 다음 순서로 실행한다.

```bash
just dev-deep-start-plan
just dev-deep-start-show
just dev-deep-start
just dev-deep-status
just dev-drift
```

`dev-deep-start`는 검토한 `dev-deep-start.tfplan`으로 ALB·listener·alarm을 만들고 새 ALB DNS를 CloudFront와 Backend 설정에 반영해 distribution 배포가 끝날 때까지 기다린 뒤 RDS·ASG·SSM을 복구한다. 정상 suspended 상태라면 같은 네 edge 자원이 `create`여야 하며, drift로 alarm만 남았다면 alarm은 새 ALB dimension으로 `update`될 수 있다. 새 ALB에는 새 service-managed public IPv4가 할당되며 이전 주소 보존을 전제로 하지 않는다.

Deep suspend 중에는 기본값이 active인 일반 `dev-plan`, `dev-apply`, `dev-drift`를 사용하지 않는다. 일반 plan은 ALB 재생성과 CloudFront 재활성화를 제안한다. suspended 상태 검증에는 `dev-deep-drift`를 사용하고, 통합·Backend·Frontend Pipeline과 DB migration도 실행하지 않는다. 중단이나 timeout이 발생하면 Console에서 임의로 생성·삭제하지 말고 `dev-deep-status`와 해당 모드의 새 plan을 확인한 뒤 실패한 단계만 재시도한다.

중단되거나 예상과 다른 상태가 보이면 start/stop을 반복하기 전에 `just dev-status`로 현재 상태를 확인한다. 전원 전환 중에는 Terraform plan/apply와 DB migration을 병행하지 않는다.

## DB 계정 초기화와 migration

이 절차는 dev Terraform apply와 `team-db-tunnel` 멤버 추가가 끝난 뒤 운영자가 실행한다. Python 3.13, `uv`, AWS CLI와 Session Manager plugin이 필요하다. 장기 비밀번호와 전체 접속 URL은 출력하지 않으며, `just db-info`만 로컬 DB 클라이언트 입력을 위해 15분 IAM DB 토큰을 명시적으로 표시한다.

로컬 PC에서 private RDS에 접근할 팀원은 `team-db-tunnel` 그룹에 수동으로 추가한다. 이 그룹은 태그가 일치하는 dev app EC2를 경유하는 SSM remote-host 포트 포워딩만 제공하며 interactive shell이나 Run Command를 허용하지 않는다.

Infra 운영자가 고정 DB 역할, runtime Secret 값과 현재 그룹 멤버의 개인 DB 역할을 초기화한다.

```bash
just db-init
```

그룹 멤버를 추가하거나 제거한 뒤 DB 권한을 동기화한다. 제거된 사용자는 즉시 `NOLOGIN`으로 바뀌고 활성 DB 세션이 종료된다.

```bash
just db-sync
```

각 팀원은 개인 `aws login` 세션으로 SSM 터널과 IAM DB token을 만들고 커밋된 Yoyo migration을 적용한다.

```bash
just db-migrate
```

공유 dev에 검토된 F3 합성 장부를 재적재할 때는 migration 적용 후 다음 명령을 사용한다.

```bash
just dev-seed-f3
```

이 명령은 개인 IAM 인증과 SSM 터널을 사용해 `F3_SYNTHETIC 합성중개사무소`만 reset하고,
커밋된 seed를 적용한 뒤 29개 검사가 모두 `PASS`인지 확인한다. IAM token과 DB URL은 출력하지
않는다. 기존 F3 실행 결과도 reset되므로 공유 dev에서 실행 중인 API 요청과 Worker 작업이 없을 때
확인 프롬프트를 승인한다. prod 또는 임의 DB를 대상으로 실행할 수 없고 파일 경로도 받지 않는다.

공유 AWS dev DB에 고정 합성 개발 세션 계정을 만들 때는 중개사무소명, 로그인 ID와 표시명을 전달한다.
역할은 생략하면 `OWNER`이며 `OWNER`, `STAFF`, `READ_ONLY` 중 하나를 사용할 수 있다.

```bash
just dev-create-session-account "개발 중개사무소" developer "Developer" OWNER
```

이 명령은 개인 `aws login` 세션으로 SSM 터널과 15분 IAM DB 인증을 만들고 Backend의
`manage.py create-development-user`를 실행한다. IAM token이나 DB URL은 출력·저장하지 않는다.
생성 결과의 `brokerage_id`와 `login_id`는 Git에서 제외된
`environments/dev/dev.tfvars`에 다음과 같이 설정한다.

```hcl
development_auth = {
  brokerage_id = 1
  login_id      = "developer"
}
```

`development_auth = null`이면 Backend의 개발 세션 경로는 식별자 설정 없이
`false`로 주입되고 Frontend 버튼도 숨겨진다. 값이 있으면 하나의 Terraform
변수에서 Backend의 `AUTH_DEVELOPMENT_*`와 Frontend의
`VITE_AUTH_DEVELOPMENT_ENABLED=true`를 함께 파생한다. CloudFront dev 주소는 공개되어
있으므로 이 계정에는 합성·비식별 데이터만 두고, URL을 아는 모든 사용자가
같은 개발 계정 세션을 발급받을 수 있음을 전제한다.

적용 후 운영자는 runtime credential·RDS endpoint metadata와 고정 DB 역할의 로그인 속성 및
필수 role membership을 검증한다.

```bash
just db-verify
```

로컬 DB 클라이언트(DBeaver, DataGrip, psql 등)에서 접속할 때 필요한 호스트, 포트, IAM 사용자명, 임시 IAM DB 인증 토큰 및 SSM 터널 실행 명령어를 한 번에 확인하려면 다음 명령을 사용한다.

```bash
just db-info
```

토큰은 Password 프롬프트나 GUI 비밀번호 필드에만 붙여 넣고 터미널 로그·화면 공유에 노출하지 않으며 사용 후 클립보드를 비운다. 출력되는 psql 명령은 토큰을 셸 히스토리에 넣지 않고 RDS hostname과 로컬 tunnel 주소를 분리해 `verify-full`을 적용한다. localhost로 접속하는 GUI 클라이언트는 제공된 CA bundle과 `verify-ca`를 사용한다.

master secret은 RDS가 관리한다. runtime Secret 값만 도구가 구조화된 JSON으로 주입하며 migration Secret 컨테이너는 Backend 호환을 위해 비어 있는 deprecated 자원으로 유지한다. runtime 비밀번호 수동 회전은 API·Worker를 중지한 maintenance window에서만 `just db-rotate`로 수행한다.

state bucket은 개인 IAM 사용자의 직접 접근을 거부한다. 직접 `aws s3` 명령이 `403`을 반환할 수 있으며, Terraform과 검증 스크립트가 `TerraformOperatorRole`을 assume해 접근하는 것이 정상이다.

<details>
<summary>완료된 최초 AWS 계정 bootstrap과 복구 절차</summary>

## 최초 1회 AWS 계정 설정

현재 계정에서는 완료된 절차다. 새 PC 연결을 위해 다시 수행하지 않는다.

1. root 계정에 MFA, 결제·보안 연락처를 설정하고 root access key가 없음을 확인한다.
2. 공유 계정 대신 팀원별 IAM 사용자를 만들고 console password와 OTP MFA를 등록한다.
3. 최초 Infra 담당자에게만 bootstrap용 관리자 권한과 AWS 관리형 `SignInLocalDevelopmentAccess`를 임시 부여한다.
4. 프로젝트 종료까지 기존 개인 IAM+MFA와 `TerraformOperatorRole`을 유지하고 Identity Center로 전환하지 않는다.

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
- `expires_at`: 기존 IAM 권한과 개발 환경의 종료 예정일

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
cd infra
just bootstrap-plan
just bootstrap-show
just verify-account
cd ..
```

dev root에는 현재 네트워크·보안·S3·ECR·RDS·설정, EC2·ALB·ASG와 관측성이 구현돼 있으므로 plan은 비용 발생 자원을 포함한다. 마지막 검토 plan은 101개 추가, 변경 0개, 삭제 0개였으며 사람의 별도 승인 전에는 apply하지 않는다.

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
```

- 세션 만료: `aws login --profile skn30-bootstrap` 후 다시 실행한다.
- state lock: 다른 실행이 끝났음을 확인하고 lock ID를 기록한 뒤에만 `terraform force-unlock`한다.
- state 복구: S3 object version을 먼저 확인하고 복원 계획을 승인받는다.
- backend 이관 실패: 임시 사본과 local state를 보존하고 원격 object 상태를 확인한 뒤 `terraform init -migrate-state`를 재시도한다.
- state bucket은 `prevent_destroy` 대상이다. 프로젝트 종료 시에도 별도 백업·폐기 승인을 거친다.

</details>
