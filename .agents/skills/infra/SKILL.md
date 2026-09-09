---
name: infra
description: "`infra/`의 Terraform·AWS·RunPod 자원, 계정·state·IAM, 배포·관측·비용과 비밀값 주입을 개발하거나 운영할 때 사용한다."
---

# 인프라 작업

코드 구현, 실제 적용과 승인 상태를 구분한다. 현재 자원·배포·검증 이력은 운영 정본에서 확인하며 이 스킬에 복제하지 않는다.

## 필요한 문서 선택

공통 탐색·결정 확인·지식 갱신은 루트 `AGENTS.md`와 project-wiki를 따른다. [참조 인덱스](references/index.md)에서 해당 작업의 문서만 읽는다.

| 변경 | 읽을 정본 |
|---|---|
| Terraform root·state·변수·출력·검증 | [Terraform 기준](references/terraform-standards.md) |
| AWS 계정 연결·bootstrap·IAM·비용 | [계정 bootstrap](references/aws-account-bootstrap.md) |
| 자원 도입·배치·적용 상태 | [자원 인벤토리](references/resource-inventory.md)와 해당 결정·검증 기록 |
| 배포·rollback·관측·비용 운영 | 참조 인덱스의 인프라 아키텍처·배포 운영·장애 대응 문서 |
| RunPod Console·Template·release·Pod 운영 | `infra/runpod/README.md` |
| AWS·RunPod F2/general 전환·GPU·검증 | `infra/serving/README.md`와 해당 운영·검증 기록 |
| 구조·운영 방식 변경 또는 미확정 선택 | [결정 인덱스](references/decisions/index.md)와 관련 ADR, [미해결 질문](references/open-questions.md) |

## 반드시 지킬 기준

- 작업 위치는 `infra/`다. Terraform이 AWS IaC 정본이며 AWS CLI는 로그인·조회·SSM 세션·검증에만 사용한다. 관리 대상 자원을 CLI로 생성·변경·삭제하지 않는다. Terraform 밖 기존 자원은 재생성보다 import 또는 명시적 예외를 검토한다.
- 한 번에 하나의 검토 가능한 환경 root와 state만 변경한다. RunPod 자원 자체는 Terraform이 소유하지 않으며 별도 운영 정본을 따른다.
- AWS 작업 전 계정 ID·리전·자격 증명 주체·비용 한도를 확인한다. 기본 리전은 `ap-northeast-2`다. 개발·시연 기간의 개인 IAM·OTP MFA·`aws login`·`TerraformOperatorRole`을 유지하며 Identity Center로 전환하지 않는다.
- 비밀값·접근 키·세션 토큰·전체 접속 URL을 코드·변수 기본값·plan·state 출력·로그에 기록하지 않는다. 애플리케이션에 비밀 저장소 클라이언트를 요구하지 않고 Infra가 프로세스 환경변수로 주입한다.
- 계정·환경 guard와 최소 권한 IAM을 적용한다. 개인정보가 DB·S3·큐·로그·백업·외부 모델로 이동하면 저장 위치·접근·보존·삭제 정책을 먼저 확인한다.
- 비용 자원은 예상 월 비용·종료 조건·소유자를 PR에 기록한다. 조건부·제외 자원의 범위를 승인 없이 확대하지 않는다.

## 적용과 검증

Terraform 변경은 `fmt → validate → plan → 승인 → apply → 검증 → drift plan` 순서로 수행한다. 적용 전 `infra/scripts/preflight.sh`로 계정·리전·도구를 검증하고 plan의 예상하지 않은 자원·교체·삭제·민감정보, 파괴적 변경의 대상·복구 방법을 확인한다. 승인된 plan만 적용하고 출력과 AWS 조회 결과를 대조한 뒤 같은 구성의 후속 plan이 비어 있는지 확인한다.
