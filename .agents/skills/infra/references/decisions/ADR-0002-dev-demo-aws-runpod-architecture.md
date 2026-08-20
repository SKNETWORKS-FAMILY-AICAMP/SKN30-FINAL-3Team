---
status: 결정
updated: 2026-08-18
---

# ADR-0002: 개발·시연용 AWS·RunPod 인프라 구성

- 상태: 승인됨
- 결정일: 2026-08-18
- 보완 결정: [프로젝트 ADR-0009](../../../project-wiki/references/decisions/ADR-0009-dev-demo-operating-constraints.md)

## 맥락

공유 개발·시연 환경은 제한된 기간과 비용 안에서 Frontend, Backend, PostgreSQL과 외부 GPU 모델을 제공해야 한다. 공개 접근과 배포 복구는 필요하지만, 아직 운영 수준의 고가용성·private egress·다중 환경은 필요하지 않다. Terraform state, 전달 artifact와 업무 데이터를 섞지 않는 경계도 필요하다.

## 결정

- `ap-northeast-2`의 단일 VPC에 ALB용 두 AZ public subnet, public EC2 app subnet과 두 AZ private RDS subnet을 둔다.
- ALB는 두 public subnet을 사용하고 EC2 inbound는 ALB security group만 허용한다. SSH는 차단하고 SSM Session Manager만 사용한다.
- ASG는 Launch Template 기반 `desired=1`이며 EC2는 public IPv4와 Internet Gateway로 제한된 outbound를 수행한다. 1차에는 NAT Gateway를 두지 않는다.
- RDS PostgreSQL 15와 pgvector는 private subnet의 Single-AZ 인스턴스로 운영한다.
- S3 Gateway Endpoint를 사용하고 Frontend origin, 임시 음성, 데이터·모델, Pipeline artifact와 Terraform state bucket을 분리한다.
- Frontend S3는 public website로 열지 않고 CloudFront Origin Access Control만 허용한다. CloudFront `/api/*`는 ALB custom origin으로 전달한다.
- ECR, CodeConnections, CodePipeline V2, CodeBuild와 CodeDeploy를 애플리케이션 전달 자원으로 사용한다. Pipeline source는 `DetectChanges=false`이고 수동 최신 `main` 또는 `COMMIT_ID` override로만 실행한다.
- CodeDeploy agent, ALB health check, CloudWatch alarm과 자동 rollback을 구성한다. DB migration 실패는 배포 실패로 처리한다.
- Secrets Manager는 비밀값, Parameter Store는 비민감 설정을 소유하고 EC2 프로세스 환경변수로 주입한다.
- CloudWatch logs·metrics·alarms와 SNS로 상태를 추적한다. AWS Billing 관련 자원은 만들지 않는다.
- RunPod는 팀 공용 Template에서 개발자별 Pod를 생성·삭제한다. 개발 실험 후에는 stop 대신 결과를 반출하고 삭제하며, 시연 운영 기간에는 선택한 Pod를 실행 상태로 유지한다.

## 조건부 자원

- 현재 환경에는 Route 53·ACM·ALB HTTPS를 만들지 않는다. 운영 승격 시 도메인과 종단 간 TLS를 별도 결정한다.
- SQS·DLQ는 RDS 작업 polling으로 독립 재시도, 지연 격리와 Worker 확장이 어려워진다는 측정 결과가 있을 때 도입한다.
- ECS Fargate·Cloud Map은 AI 실행부의 독립 확장·배포·장애 격리가 필요할 때 도입한다.
- RunPod custom image·Network Volume은 기본 vLLM, 일반 모델 다운로드와 Pod volume 방식이 요구를 충족하지 못할 때 도입한다.

## 보안과 개인정보 제약

- 모든 업무용 S3와 RDS는 저장 암호화, public access 차단과 최소 권한을 적용한다.
- 실제 음성, 전사, 프롬프트와 개인정보를 CloudWatch·Build·RunPod 로그에 남기지 않는다.
- 도메인·ACM과 ALB HTTPS가 검증되기 전에는 합성·비식별 데이터만 사용하고 실제 개인정보 트래픽을 금지한다.
- public EC2와 NAT 없는 구조는 개발·시연 전용이다. 운영 승격 시 private app subnet과 egress 통제를 별도 결정한다.

## 결과

ALB와 ASG 교체 복구, private RDS, 비공개 정적 origin과 수동 승인 배포를 유지하면서 NAT·Multi-AZ 비용을 피한다. 대신 단일 EC2·RDS 장애와 EC2 public egress를 수용하며, 운영 환경으로 그대로 승격할 수 없다.

자원별 상태와 상세 흐름은 [resource inventory](../resource-inventory.md), [인프라 개요](../../../../../docs/architecture/infra/overview.md)와 [배포·운영 구조](../../../../../docs/architecture/infra/deployment-and-operations.md)를 따른다.

## 1차 제외

- GitHub Actions OIDC, NAT Gateway, Multi-AZ RDS, WAF, ElastiCache, AWS Backup, EKS, Step Functions
- Terraform 배포 Pipeline
- 조건이 충족되지 않은 SQS·DLQ, ECS Fargate·Cloud Map, RunPod custom image·Network Volume
