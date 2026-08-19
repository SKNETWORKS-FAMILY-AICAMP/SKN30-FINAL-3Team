---
status: 결정
updated: 2026-08-19
---

# ADR-0006: 팀 읽기 전용 IAM 그룹

- 상태: 승인됨
- 결정일: 2026-08-19

## 맥락

현재 AWS Organizations 멤버 계정의 IAM Identity Center account instance는 permission set과 AWS 계정 접근을 지원하지 않는다. Organization instance와 위임 관리자 구성이 확정되기 전에도 팀원이 단일 계정의 자원과 설정을 읽을 수단이 필요하다.

## 결정

- `infra/bootstrap`이 `team-readonly` IAM 그룹과 AWS 관리형 `ReadOnlyAccess` 정책 연결을 소유한다.
- IAM 사용자 생성·삭제, 그룹 멤버 추가·제거, console password와 MFA 장치는 Terraform에서 관리하지 않는다.
- 그룹에는 쓰기 정책과 장기 access key 사용 권한을 추가하지 않는다.
- 이 구성은 Identity Center organization instance로 전환하기 전의 임시 계정 접근 모델이다.

## 결과

공통 읽기 권한과 변경 이력은 Terraform plan과 state로 검토할 수 있다. 사용자 수명주기와 MFA 등록은 수동 운영으로 남으며, AWS가 `ReadOnlyAccess` 관리형 정책을 갱신하면 그룹 권한에도 자동 반영된다. Identity Center 전환과 기존 IAM 권한 폐기 순서는 `INFRA-OQ-001`에서 계속 관리한다.
