---
status: 결정
updated: 2026-08-19
---

# AWS 계정 bootstrap

## 수동 선행 작업

- root MFA, 결제·보안 연락처와 root 액세스 키 부재를 확인한다.
- 공유 IAM 사용자를 만들지 않고 Infra 담당자별 IAM 사용자와 OTP MFA를 설정한다.
- 최초 담당자에게만 bootstrap에 필요한 임시 관리자 권한과 `SignInLocalDevelopmentAccess`를 부여한다.
- AWS CLI 로그인 원본 profile은 `skn30-bootstrap`, Terraform credential process profile은 `skn30-session`을 사용한다.
- AWS CLI 2.36 이상에서 `aws login`으로 임시 자격 증명을 사용하고 저장소에 접근 키를 기록하지 않는다.

## Terraform bootstrap

1. `infra/scripts/preflight.sh`로 도구, 세션, 계정 ID와 `ap-northeast-2`를 검증한다.
2. `infra/bootstrap/backend.tf`를 제외한 구성으로 local state plan과 apply를 수행한다.
3. 생성된 state bucket 이름을 사용해 bootstrap root를 S3 backend로 초기화하고 local state를 이관한다.
4. `TerraformOperatorRole` assume이 되는지 확인한 뒤 사용자에게서 임시 관리자 권한을 제거한다.
5. dev root를 별도 state key로 초기화하고 계정 조회 plan을 실행한다.

bootstrap은 `team-readonly` IAM 그룹과 AWS 관리형 `ReadOnlyAccess` 정책 연결을 관리한다. IAM 사용자와 그룹 멤버십, console password와 MFA 장치는 수동으로 관리하며 Terraform state에 넣지 않는다.

현재 계정에서는 AWS Budget과 Cost Anomaly Detection을 사용할 수 없으므로 `create_budget=false`로 고정한다. 비용 상한은 2026-09-23까지 누적 300,000원의 수동 참고값이며 Terraform 밖에서도 Billing 자원을 만들지 않는다.

## 새 PC 연결

- 승인된 IAM 사용자와 MFA가 있는 새 PC에서는 `infra/scripts/setup-local.sh`로 profile, 로컬 backend/dev 변수, Terraform init과 읽기 전용 연결 검증을 수행한다.
- 이 절차는 기존 S3 state에 연결할 뿐 bootstrap apply를 반복하지 않는다.
- 스크립트는 IAM 변경, `bootstrap.tfvars` 생성과 `terraform apply`를 수행하지 않는다.
- 다른 사용자를 추가할 때는 기존 운영자가 전체 `operator_user_arns`를 보존한 별도 bootstrap plan을 승인받아 적용한다.

## 복구와 종료

- local state 이관 전에는 복사본을 만들고 이관 성공 후에만 로컬 원본을 제거한다.
- state lock은 실제 실행이 종료됐음을 확인한 경우에만 `force-unlock`한다.
- state bucket은 일반 destroy 대상이 아니다. 프로젝트 종료 시 state와 복구 필요성을 검토한 별도 절차로 폐기한다.
- 개인 IAM 사용자, OTP MFA, `aws login`과 `TerraformOperatorRole`을 2026-09-23 환경 종료까지 유지한다. Identity Center 전환은 하지 않으며 종료 시 사용자·역할·policy attachment 회수를 확인한다.
