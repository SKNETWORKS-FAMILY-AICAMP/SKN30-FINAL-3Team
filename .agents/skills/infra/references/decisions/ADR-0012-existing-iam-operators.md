---
status: 결정
updated: 2026-08-20
---

# ADR-0012: 기존 IAM 운영자에 delivery 권한 연결

- 상태: 승인됨
- 결정일: 2026-08-20
- 상위 결정: [프로젝트 ADR-0012](../../../project-wiki/references/decisions/ADR-0012-retain-iam-access.md)
- 대체 범위: [ADR-0006](ADR-0006-team-readonly-iam-group.md)의 Identity Center 전환 전 임시 접근 설명

## 결정

- `infra/bootstrap`의 개인 IAM 사용자, MFA, `TerraformOperatorRole`과 `team-readonly` 그룹 구성을 프로젝트 종료까지 유지한다.
- dev root는 `pipeline_operator_user_names` 입력으로 승인된 기존 IAM 사용자 이름을 받는다.
- dev root가 세 Pipeline의 조회·실행·중지 권한만 가진 `pipeline_operator` 관리형 policy와 사용자 attachment를 소유한다.
- 현재 승인된 Pipeline 운영자는 bootstrap의 기존 운영자 `student`다.
- `student`의 `TerraformOperatorRole` assume 권한은 Infra plan/apply 용도로 유지한다. Pipeline 운영에 관리자 역할 assume을 요구하지 않는다.
- `team-readonly`에는 Pipeline 쓰기 policy를 연결하지 않는다.
- IAM 사용자 자체, MFA, console password와 그룹 멤버십은 Terraform 소유 범위로 가져오지 않는다.

## 검증과 종료

- plan에서 기존 IAM 사용자나 역할의 생성·교체·삭제가 없어야 한다.
- delivery plan에는 기존 사용자에 대한 policy attachment 추가만 나타나야 한다.
- 프로젝트 종료 시 attachment 제거, `TerraformOperatorRole` 접근 회수, state와 final snapshot 보존 결정을 함께 확인한다.
