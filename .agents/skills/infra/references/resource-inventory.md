---
status: 결정
updated: 2026-08-31
---

# 인프라 자원 인벤토리

선택 정본은 [Infra ADR-0002](decisions/ADR-0002-dev-demo-aws-runpod-architecture.md), [Infra ADR-0003](decisions/ADR-0003-dev-storage-database-and-configuration.md), [Infra ADR-0004](decisions/ADR-0004-dev-runtime-and-observability-baseline.md), [Infra ADR-0005](decisions/ADR-0005-dev-frontend-origin-and-api-routing.md)와 [Infra ADR-0015](decisions/ADR-0015-cloudwatch-alarm-discord-delivery.md)다. Terraform 코드 구현과 실제 생성 여부를 구분한다. dev workload, DB migration과 기존 delivery 자원은 적용됐고 Alarm 전용 전달과 Verify/Build 분리는 plan 검증 후 apply 승인 전이다.

| 영역 | 자원 | 선택 상태 | 구현 상태 | 도입 조건·제약 |
|---|---|---|---|---|
| 계정 기반 | IAM, Terraform state S3 | 결정 | 구현됨 | state는 업무·Pipeline artifact와 혼용 금지 |
| 비용 | AWS Budget, Cost Anomaly Detection | 제외 | 제외 | 계정에서 사용 불가; 2026-09-23까지 누적 300,000원은 운영 참고 상한 |
| 네트워크 | VPC, IGW, route table, public subnet 2개 AZ | 결정 | 적용됨 | NAT·IPv6 없음 |
| 네트워크 | EC2 app public subnet, RDS private subnet 2개, security group | 결정 | 적용됨 | ALB HTTP는 CloudFront origin-facing prefix에서만, EC2 inbound는 ALB SG만, RDS inbound는 App SG만 |
| 네트워크 | S3 Gateway Endpoint | 결정 | 적용됨 | public/app route table의 업무용 S3 접근 경로 |
| 컴퓨팅 | EC2, Launch Template, ASG desired 1, ALB | 결정 | 기존 자원 적용·deep lifecycle 코드 구현 미적용 | AL2023 x86_64, t3.small, gp3 40 GiB; deep suspend는 ASG 0·ALB 삭제, target group 유지 |
| 운영 접속 | SSM Session Manager | 결정 | 적용됨 | SSH 차단, IMDSv2 강제 |
| 이미지 | Backend ECR | 결정 | 적용됨 | immutable tag, untagged image만 7일 후 만료; 배포는 digest 고정 |
| 검증 이미지 | CI pgvector ECR | 결정 | 코드 구현됨·미적용 | Backend Verify 전용 immutable cache; Docker Hub 미사용, runtime role 접근 없음 |
| 데이터베이스 | RDS PostgreSQL 15.18, pgvector, Single-AZ | 결정 | 적용됨 | `db.t4g.small`, gp3 20→50 GiB, 백업 7일, IAM DB 인증; `vector`는 최초 DB migration 소유 |
| Frontend | CloudFront, private S3 origin, OAC, ALB custom origin | 결정 | 기존 자원 적용·deep lifecycle 코드 구현 미적용 | deep suspend는 distribution ID·domain을 유지하고 비활성화하며 ALB origin·API behavior를 제거 |
| 업무 파일 | 임시 음성 S3 | 결정 | 적용됨 | 앱이 성공·취소 즉시, 실패 1시간 이내 삭제; lifecycle 1일 안전망 |
| 데이터·모델 | 데이터셋·평가·모델 artifact S3 | 결정 | 적용됨 | `releases/`는 2026-09-24 00:00 UTC 만료, 그 외 자동 만료 없음 |
| 비밀·설정 | Secrets Manager, Parameter Store | 결정 | 기존 자원 적용됨·환경 materialization 미적용 | runtime DB·migration IAM·RDS master 자동 경계 유지; AI·delivery Discord와 새 Alarm Discord 입력은 각각 ignored tfvars→write-only 전환 후 plan·apply |
| 관측성 | CloudWatch logs·metrics·alarms, SNS·Lambda | 결정 | 기존 6개 alarm 적용·전용 전달과 2개 app alarm 코드 구현 미적용 | 적용 후 별도 SNS/Lambda가 기존 6개와 Backend 500·AI terminal alarm을 새 Discord Secret으로 전달; notifier log 14일, 기존 delivery notifier 무변경 |
| 전달 | CodeConnections, CodePipeline V2, CodeBuild, CodeDeploy | 결정 | 기존 main source 적용됨·dev/분리 변경 미적용 | Terraform 적용 후 통합 dev 자동, Backend·Frontend 수동, 모두 QUEUED |
| 전달 저장소 | Pipeline artifact S3 | 결정 | 적용됨 | non-versioned, 객체 14일 만료; 업무용 S3·Terraform state와 분리 |
| 모델 실행 | RunPod 공용 Template, 개발자별 Pod | 결정 | 보류 | 운영 구조는 결정됐으나 Terraform 소유 범위는 재개 전 결정 |
| 공개 TLS | Route 53, ACM, ALB HTTPS | 제외 | 제외 | 현재 환경에는 도메인이 없고 실제 개인정보 사용 금지; 운영 승격 시 별도 결정 |
| 큐 | SQS, DLQ | 조건부 | 미확정 | RDS polling이 독립 재시도·확장을 충족하지 못할 때 |
| AI 분리 | ECS Fargate, Cloud Map | 조건부 | 미확정 | 경합·지연·독립 배포·장애 격리 필요 측정 후 |
| 모델 배포 | RunPod custom image, Network Volume | 조건부 | 미확정 | 기본 vLLM·다운로드 방식이 부족할 때 |
| 제외 | GitHub Actions OIDC, NAT Gateway, Multi-AZ RDS | 제외 | 제외 | 1차 개발·시연 범위 |
| 제외 | WAF, ElastiCache, AWS Backup, EKS, Step Functions | 제외 | 제외 | 별도 요구·승인 전 |
| 제외 | Terraform 배포 Pipeline | 제외 | 제외 | 수동 Terraform 절차 유지 |

## 현재 구현 경계

- 현재 계정 bootstrap은 워크로드 자원을 만들지 않는다.
- `infra/environments/dev`의 네트워크·보안, S3·ECR·RDS·설정, EC2·ALB·ASG, 관측성과 DB migration은 적용됐다.
- CloudWatch Alarm 전용 SNS·Lambda·Secret, 기존 6개 alarm action 전환과 애플리케이션 alarm 2개는 코드·fixture 검증만 완료했으며 AWS에는 적용하지 않았다.
- ALB 삭제·CloudFront 비활성화 deep lifecycle은 코드와 운영 명령을 구현했으나 AWS saved plan 검토·apply 전이다.
- 세 Pipeline, 기존 CodeBuild/CodeDeploy, Discord 알림과 기존 IAM 운영자 policy attachment는 적용됐다. Verify/Build 분리 변경은 검증됐지만 승인 전에는 apply하지 않는다.
- RunPod Terraform은 사용자 지시에 따라 보류했고 AWS provider 밖의 자원은 추가하지 않았다.
- Terraform state bucket은 애플리케이션 파일 저장소가 아니며 다른 용도로 재사용하지 않는다.
