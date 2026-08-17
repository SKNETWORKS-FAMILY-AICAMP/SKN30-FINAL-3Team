---
status: 결정
updated: 2026-08-18
---

# 인프라 자원 인벤토리

선택 정본은 [Infra ADR-0002](decisions/ADR-0002-dev-demo-aws-runpod-architecture.md)다. 모든 자원은 아직 생성 전이므로 채택 여부와 구현 상태를 구분한다.

| 영역 | 자원 | 선택 상태 | 구현 상태 | 도입 조건·제약 |
|---|---|---|---|---|
| 계정 기반 | IAM, Terraform state S3 | 결정 | 구현됨 | state는 업무·Pipeline artifact와 혼용 금지 |
| 비용 | Budget, SNS | 결정 | 계획됨 | 조직 SCP가 막으면 조직 관리자 제공 필요 |
| 네트워크 | VPC, IGW, route table, ALB public subnet 2개 AZ | 결정 | 계획됨 | ALB 두 AZ, NAT 없음 |
| 네트워크 | EC2 app public subnet, RDS private subnet 2개, security group | 결정 | 계획됨 | EC2 inbound는 ALB SG만, RDS inbound는 App SG만 |
| 네트워크 | S3 Gateway Endpoint | 결정 | 계획됨 | 업무용 S3 접근 경로 |
| 컴퓨팅 | EC2, Launch Template, ASG desired 1, ALB | 결정 | 계획됨 | API·Worker 논리 분리, 같은 호스트 |
| 운영 접속 | SSM Session Manager | 결정 | 계획됨 | SSH 차단 |
| 이미지 | ECR | 결정 | 계획됨 | Backend와 설치형 brokerage-ai 이미지 digest |
| 데이터베이스 | RDS PostgreSQL 15, pgvector, Single-AZ | 결정 | 계획됨 | private 배치; class·보존기간 미확정 |
| Frontend | CloudFront, private S3 origin, OAC | 결정 | 계획됨 | S3 public website 금지 |
| 업무 파일 | 임시 음성 S3 | 결정 | 계획됨 | 성공·취소 즉시, 실패 1시간 이내 애플리케이션 삭제 |
| 데이터·모델 | 데이터셋·평가·모델 artifact S3 | 결정 | 계획됨 | exact lifecycle 미확정 |
| 비밀·설정 | Secrets Manager, Parameter Store | 결정 | 계획됨 | 프로세스 환경변수로 주입 |
| 관측성 | CloudWatch logs·metrics·alarms | 결정 | 계획됨 | 원문 개인정보·프롬프트 로깅 금지 |
| 전달 | CodeConnections, CodePipeline V2, CodeBuild, CodeDeploy | 결정 | 계획됨 | DetectChanges=false, 수동 최신 main 또는 COMMIT_ID |
| 전달 저장소 | Pipeline artifact S3 | 결정 | 계획됨 | 업무용 S3·Terraform state와 분리 |
| 모델 실행 | RunPod 공용 Template, 개발자별 Pod | 결정 | 계획됨 | 가용 GPU 선택, 개발 후 삭제, 시연 기간 상시 유지 |
| 공개 TLS | Route 53, ACM | 조건부 | 미확정 | 도메인 확정 후 |
| 큐 | SQS, DLQ | 조건부 | 미확정 | RDS polling이 독립 재시도·확장을 충족하지 못할 때 |
| AI 분리 | ECS Fargate, Cloud Map | 조건부 | 미확정 | 경합·지연·독립 배포·장애 격리 필요 측정 후 |
| 모델 배포 | RunPod custom image, Network Volume | 조건부 | 미확정 | 기본 vLLM·다운로드 방식이 부족할 때 |
| 제외 | GitHub Actions OIDC, NAT Gateway, Multi-AZ RDS | 제외 | 제외 | 1차 개발·시연 범위 |
| 제외 | WAF, ElastiCache, AWS Backup, EKS, Step Functions | 제외 | 제외 | 별도 요구·승인 전 |
| 제외 | Terraform 배포 Pipeline | 제외 | 제외 | 수동 Terraform 절차 유지 |

## 현재 구현 경계

- 현재 계정 bootstrap은 워크로드 자원을 만들지 않는다.
- `infra/environments/dev`는 계정·리전 조회만 수행한다.
- 이 인벤토리의 계획 자원은 승인됐지만 아직 Terraform state나 AWS·RunPod에 생성되지 않았다.
- 실제 구현은 비용·보안 검토가 포함된 별도 Terraform PR에서 수행한다.
- Terraform state bucket은 애플리케이션 파일 저장소가 아니며 다른 용도로 재사용하지 않는다.
