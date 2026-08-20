---
status: 결정
updated: 2026-08-20
---

# ADR-0012: 기존 IAM 사용자·역할 접근 모델 유지

- 상태: 승인됨
- 결정일: 2026-08-20
- 대체 범위: [ADR-0007](ADR-0007-terraform-iac.md)과 [ADR-0009](ADR-0009-dev-demo-operating-constraints.md)의 Identity Center 전환·재검토 결정

## 맥락

개발·시연 계정은 개인 IAM 사용자, OTP MFA, `aws login`, `TerraformOperatorRole`과 `team-readonly` 그룹으로 이미 운영되고 있다. Delivery 적용을 앞두고 Identity Center permission set과 역할 trust 전환을 선행 조건으로 두었으나, 팀은 프로젝트 기간에 Identity Center로 전환하지 않기로 결정했다.

## 결정

- 2026-09-23 개발환경 종료까지 기존 개인 IAM 사용자와 MFA 접근 모델을 유지한다.
- Infra 변경은 승인된 IAM 사용자가 `TerraformOperatorRole`을 assume해 수행한다.
- Pipeline 수동 실행은 승인된 기존 IAM 사용자에게 세 dev Pipeline만 조회·시작·중지할 수 있는 최소 권한 관리형 정책을 직접 연결한다.
- `team-readonly` 그룹은 AWS `ReadOnlyAccess`만 유지하며 Pipeline 쓰기 권한을 추가하지 않는다.
- IAM 사용자 생성·삭제, console password, MFA와 그룹 멤버십은 계속 수동 운영한다.
- 장기 access key는 만들지 않고 `aws login` 임시 자격 증명을 사용한다.
- 기존 IAM 사용자와 역할에는 `ExpiresAt=2026-09-23` 운영 종료 절차를 적용한다.

## 결과

Identity Center 설계와 trust 전환은 delivery 적용 gate에서 제거된다. 대신 사용자 수명주기와 MFA 감사는 수동 운영으로 남고, 프로젝트 종료 시 Pipeline 정책 연결, IAM 사용자·역할과 state 접근을 별도 종료 체크리스트로 회수해야 한다.

운영자 이름과 정책 연결의 Terraform 세부 기준은 [Infra ADR-0012](../../../infra/references/decisions/ADR-0012-existing-iam-operators.md)를 따른다.
