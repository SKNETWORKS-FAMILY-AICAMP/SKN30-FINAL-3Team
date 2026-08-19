---
status: 결정
updated: 2026-08-19
---

# Infra 결정 인덱스

| ADR | 상태 | 결정 |
|---|---|---|
| [ADR-0001](ADR-0001-terraform-layout-and-state.md) | 승인됨 | 계정 bootstrap과 환경별 root, S3 native state 잠금 사용 |
| [ADR-0002](ADR-0002-dev-demo-aws-runpod-architecture.md) | 승인됨 | NAT 없는 EC2·RDS·S3·RunPod와 수동 CodePipeline 개발·시연 구성 |
| [ADR-0003](ADR-0003-dev-storage-database-and-configuration.md) | 승인됨 | 개발 환경 RDS·업무용 S3·설정 저장소와 보존 기준 |
| [ADR-0004](ADR-0004-dev-runtime-and-observability-baseline.md) | 승인됨 | 개발 환경 EC2·ALB·ASG runtime과 최소 권한·14일 관측 기준 |
| [ADR-0005](ADR-0005-dev-frontend-origin-and-api-routing.md) | 승인됨 | private S3·CloudFront OAC와 `/api/*` 동일 origin routing 기준 |
| [ADR-0006](ADR-0006-team-readonly-iam-group.md) | 승인됨 | `team-readonly` IAM 그룹과 `ReadOnlyAccess` 연결만 Terraform으로 관리 |
