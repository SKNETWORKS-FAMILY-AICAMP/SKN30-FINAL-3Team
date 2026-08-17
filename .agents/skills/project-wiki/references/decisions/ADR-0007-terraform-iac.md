---
status: 결정
updated: 2026-08-17
---

# ADR-0007: Terraform을 AWS IaC 정본으로 사용

## 맥락

AWS 계정 연결과 이후 인프라 변경을 팀원이 같은 절차로 재현해야 한다. AWS CLI 기반 수동 생성은 변경 이력, 검토, drift 확인과 복구가 어렵다.

## 결정

- AWS 인프라 변경의 정본은 Terraform으로 관리한다.
- AWS CLI는 로그인, 조회, SSM 접속과 배포 결과 검증에만 사용한다.
- state는 버전 관리·암호화·공개 차단·잠금이 적용된 전용 S3 bucket에 저장한다.
- 계정 부트스트랩과 환경별 워크로드는 서로 다른 Terraform root와 state key로 분리한다.
- 개인 IAM 사용자와 MFA, AWS CLI `aws login`은 초기 프로젝트 기간의 임시 접근 방식으로 사용한다.
- Identity Center 전환 시점은 운영 배포 전에 다시 결정한다.

세부 루트 구조와 state 운영 기준은 [Infra ADR-0001](../../../infra/references/decisions/ADR-0001-terraform-layout-and-state.md)을 따른다.

## 결과

- 변경은 `fmt → validate → plan → 승인 → apply → 검증 → drift 확인` 순서로 수행한다.
- Terraform 밖에서 관리 자원을 변경하지 않는다. 긴급 변경은 즉시 코드와 state에 반영한다.
- 계정과 리전 guard를 모든 Terraform root에 둔다.
- 반복이 실제로 생기기 전에는 공유 module이나 workspace를 만들지 않는다.

## 제외 범위

이 결정은 RDS, VPC, EC2, ECS, ECR, SQS, 업무용 S3 또는 RunPod 도입을 승인하지 않는다. 각 자원은 요구사항, 비용과 보안 조건을 확인한 별도 결정 후 추가한다.
