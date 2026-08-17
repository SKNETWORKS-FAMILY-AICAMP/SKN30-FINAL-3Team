---
status: 결정
updated: 2026-08-17
---

# ADR-0001: Terraform 레이아웃과 state

- 상태: 승인됨
- 결정일: 2026-08-17

## 맥락

AWS 계정 연결을 재현하고 이후 RDS와 실행 자원을 검토 가능한 변경으로 추가하려면 IaC와 공동 state 기준이 필요하다. 현재는 단일 개발 환경만 필요하며 워크로드 자원 선택은 아직 확정되지 않았다.

## 결정

- `infra/bootstrap`과 `infra/environments/dev`를 독립 Terraform root로 사용한다.
- bootstrap은 계정 보안 기본값, 비용 예산, 임시 Terraform 운영자 역할과 state bucket만 소유한다.
- dev root에는 첫 워크로드 결정 전까지 계정·리전 data source만 둔다.
- state는 versioning과 암호화를 적용한 S3 bucket에 root별 key로 분리한다.
- S3 native lockfile을 사용하고 DynamoDB 잠금, workspace와 공통 module은 도입하지 않는다.
- AWS provider account allowlist와 서울 리전 validation을 모든 root에 적용한다.
- AWS CLI는 인증·조회·검증에만 사용한다.

## 결과

첫 AWS 연결은 작은 범위로 검증할 수 있고 이후 워크로드를 dev root에 추가할 수 있다. state bucket 자체를 만들 때만 local state에서 S3로 한 번 이관해야 한다. Identity Center와 워크로드 구조는 별도 결정 전까지 이 ADR이 확정하지 않는다.
