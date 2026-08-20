---
name: infra
description: "`infra/`의 Terraform 기반 AWS·RunPod 인프라, 계정 bootstrap, 네트워크, IAM, 배포, 관측성과 비용 구성을 개발하거나 운영 환경을 변경할 때 사용한다. AWS 계정 연결, Terraform state, RDS·ECS·SQS·S3·RunPod 자원 검토와 비밀값 주입도 포함하며 프로젝트 공통 지식은 project-wiki와 함께 확인한다."
---

# 인프라 작업 지침

## 시작 절차

1. project-wiki의 `references/index.md`에서 현재 작업과 관련된 결정·환경·개인정보 문서를 읽는다.
2. [references/index.md](references/index.md)에서 현재 인프라 작업에 필요한 문서만 읽는다.
3. 아키텍처 문서의 상태를 확인하고 `결정`, `구현됨`, `계획됨`, `제안`, `미확정`을 구분한다.
4. AWS 작업 전 계정 ID, 리전, 자격 증명 주체와 비용 한도를 확인한다.
5. Terraform 변경은 `fmt → validate → plan → 승인 → apply → 검증 → drift plan` 순서로 수행한다.

## 기본 원칙

- 작업 위치는 `infra/`다.
- Terraform을 IaC 정본으로 사용한다. AWS CLI는 로그인, 조회, SSM 세션과 검증에만 사용하고 자원을 생성·변경·삭제하지 않는다.
- Terraform 밖에서 만들어진 관리 대상 자원은 그대로 재생성하지 말고 import 또는 명시적 예외를 검토한다.
- 한 번에 하나의 검토 가능한 환경 root와 state만 변경한다.
- 비밀값, 접근 키, 세션 토큰과 전체 접속 URL을 코드, 변수 기본값, plan, state 출력 또는 로그에 기록하지 않는다.
- 애플리케이션에는 비밀 저장소 클라이언트를 요구하지 않고 Infra가 프로세스 환경변수로 주입한다.
- 계정·환경 guard와 최소 권한 IAM을 적용하고, 파괴적 변경은 대상과 복구 방법을 plan에서 확인한다.
- 비용이 생기는 자원은 예상 월 비용, 종료 조건과 소유자를 PR에 기록한다.
- 개인정보가 DB, S3, 큐, 로그, 백업 또는 외부 모델로 이동하면 저장 위치·접근·보존·삭제 정책을 먼저 확인한다.

## 현재 확정 범위

- Terraform 기반 계정 bootstrap과 S3 원격 state는 결정됐다.
- AWS 대상 리전은 별도 결정 전까지 `ap-northeast-2`다.
- 개발·시연 기간에는 기존 개인 IAM 사용자, OTP MFA, `aws login`과 `TerraformOperatorRole`을 유지하며 Identity Center로 전환하지 않는다.
- RDS PostgreSQL 15 Single-AZ, EC2·ALB·ASG, 업무용 S3와 DB migration은 dev에 적용됐다. CodePipeline delivery는 코드 구현 후 apply 승인 전이며 RunPod Terraform은 보류 상태다.
- ECS Fargate·Cloud Map, SQS·DLQ, Route 53·ACM과 RunPod custom image·Network Volume은 조건이 충족될 때만 도입한다.
- GitHub Actions OIDC, NAT Gateway, Multi-AZ RDS와 Terraform 배포 Pipeline은 1차 범위에서 제외한다.

## 검증과 기록

- 적용 전 `infra/scripts/preflight.sh`로 계정·리전·도구를 검증한다.
- Terraform plan에 예상하지 않은 자원, 교체, 삭제와 민감정보가 없는지 확인한다.
- 적용 후 출력과 AWS 조회 결과를 대조하고 같은 구성의 후속 plan이 비어 있는지 확인한다.
- 영구적인 프로젝트 공통 결정은 project-wiki에, Infra 내부 결정은 `references/decisions/`에 기록한다.
- 미확정 항목은 소유 범위의 `open-questions.md`에 남기며 후보를 승인된 사실로 표현하지 않는다.
