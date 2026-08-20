---
status: 미확정
updated: 2026-08-20
---

# Infra 미해결 질문

| ID | 질문 | 영향 | 결정 시점 |
|---|---|---|---|
| INFRA-OQ-003 | 조건부 ECS AI 내부 호출의 인증·암호화·service discovery와 외부 모델 egress를 어떻게 구성할 것인가? | 보안, 재시도, 비용, 장애 격리 | ECS 도입 ADR 전 |
| INFRA-OQ-007 | `t3.small`과 EBS 40 GiB를 다시 조정할 CPU·메모리·디스크 부하 임계값은 무엇인가? | 비용, 지연, 가용성 | runtime Terraform 적용 후 부하 측정 시 |
| INFRA-OQ-008 | 환경 종료 시 생성한 RDS final snapshot의 소유자, 보존 근거, 폐기 승인일은 무엇인가? | 비용, 복구, 개인정보 삭제 | 환경 종료 승인 전 |
| INFRA-OQ-009 | RunPod Template·Pod·Secret 중 무엇을 Terraform이 소유하고 수동 운영과 어떤 경계로 나눌 것인가? | 비밀값, state, GPU 가용성, 재현성 | RunPod IaC 재개 전 |
| INFRA-OQ-010 | Versioned Terraform state bucket의 비운영자 Deny에 `GetObjectVersion`·`DeleteObjectVersion`·`ListBucketVersions`를 언제 추가하고 policy change를 적용할 것인가? | 이전 state version 기밀성·무결성 | 다음 bootstrap 보안 변경 전 |

프로젝트 공통 미해결 질문인 업무 데이터 보존기간과 큐 전환 계약은 project-wiki `open-questions.md`를 정본으로 사용한다. Identity Center 전환은 폐기하고 기존 IAM 접근을 유지하기로 결정했다. 첫 런타임, 예산·비밀 저장, RDS·S3·설정, EC2·관측성과 Frontend origin 기준은 [ADR-0008](../../project-wiki/references/decisions/ADR-0008-dev-demo-runtime-and-delivery.md), [Infra ADR-0002](decisions/ADR-0002-dev-demo-aws-runpod-architecture.md), [Infra ADR-0003](decisions/ADR-0003-dev-storage-database-and-configuration.md), [Infra ADR-0004](decisions/ADR-0004-dev-runtime-and-observability-baseline.md), [Infra ADR-0005](decisions/ADR-0005-dev-frontend-origin-and-api-routing.md)에서 해결됐다.
