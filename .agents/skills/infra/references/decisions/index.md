---
status: 결정
updated: 2026-09-03
---

# Infra 결정 인덱스

| ADR | 상태 | 결정 |
|---|---|---|
| [ADR-0001](ADR-0001-terraform-layout-and-state.md) | 승인됨 | 계정 bootstrap과 환경별 root, S3 native state 잠금 사용 |
| [ADR-0002](ADR-0002-dev-demo-aws-runpod-architecture.md) | 부분 대체됨 | NAT 없는 EC2·RDS·S3 유지; 전달은 ADR-0011, RunPod 운영은 프로젝트 ADR-0020이 대체 |
| [ADR-0003](ADR-0003-dev-storage-database-and-configuration.md) | 부분 대체됨 | 개발 환경 RDS·업무용 S3·설정 저장소와 보존 기준 |
| [ADR-0004](ADR-0004-dev-runtime-and-observability-baseline.md) | 부분 대체됨 | 개발 환경 EC2·ALB·ASG runtime과 최소 권한·14일 관측 기준 |
| [ADR-0005](ADR-0005-dev-frontend-origin-and-api-routing.md) | 부분 대체됨 | private S3·CloudFront OAC와 `/api/*` 동일 origin routing 기준 |
| [ADR-0006](ADR-0006-team-readonly-iam-group.md) | 부분 대체됨 | `team-readonly` IAM 그룹과 `ReadOnlyAccess` 연결 관리 |
| [ADR-0007](ADR-0007-dev-db-tunnel-access.md) | 승인됨 | `team-db-tunnel` 그룹과 태그 제한 SSM remote-host 포트 포워딩 권한 관리 |
| [ADR-0008](ADR-0008-dev-database-access-management.md) | 승인됨 | runtime Secret, IAM DB migration과 개인 개발자 DB 역할 운영 기준 |
| [ADR-0009](ADR-0009-dev-power-lifecycle.md) | 부분 대체됨 | 지정 Infra 운영자의 ASG 0↔1·RDS start/stop 운영과 Terraform 소유권 경계 |
| [ADR-0010](ADR-0010-dev-ec2-instance-class.md) | 승인됨 | 개발 환경 EC2 instance class를 `t3.small`로 축소 |
| [ADR-0011](ADR-0011-dev-delivery-implementation.md) | 부분 대체됨 | 통합·Backend·Frontend Pipeline, CodeDeploy, rollback과 Discord delivery 구현 |
| [ADR-0012](ADR-0012-existing-iam-operators.md) | 승인됨 | 기존 IAM 운영자에 최소 권한 Pipeline policy 직접 연결 |
| [ADR-0013](ADR-0013-dev-environment-materialization.md) | 부분 대체됨 | Terraform 공개 설정 정본, 초기 write-only 수동 비밀과 프로세스별 환경파일 사용 |
| [ADR-0014](ADR-0014-dev-deep-power-lifecycle.md) | 승인됨 | ALB 삭제·CloudFront 비활성화를 포함한 검토 가능한 dev deep 전원 운영 |
| [ADR-0015](ADR-0015-cloudwatch-alarm-discord-delivery.md) | 부분 대체됨·코드 구현, 미적용 | CloudWatch Alarm을 전용 SNS·Lambda와 새 Discord webhook Secret으로 분리 전달 |
| [ADR-0016](ADR-0016-runpod-shared-f2-serving.md) | 대체됨 | 영속 Volume과 stop/start 기반 RunPod 공유 F2 서빙 운영 |
| [ADR-0017](ADR-0017-runpod-ephemeral-sllm-serving.md) | 부분 대체됨·코드 구현, S3 dev release 게시 완료·RunPod/Terraform 미적용 | private S3 SLLM release와 RunPod create/delete, active/offline endpoint로 공유 dev 서빙; release v2와 미평가 dev 경로는 프로젝트 ADR-0022·0023 적용 |
| [ADR-0018](ADR-0018-runpod-bootstrap-secrets-monitoring.md) | 승인됨·코드 구현, 외부 자원 미적용 | RunPod 단일 bootstrap, AWS 값 정본·회전, 읽기 전용 감시와 수동 reconcile |
