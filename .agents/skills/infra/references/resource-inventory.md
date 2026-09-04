---
status: 결정
updated: 2026-09-04
---

# 인프라 자원 인벤토리

선택 정본은 [Infra ADR-0002](decisions/ADR-0002-dev-demo-aws-runpod-architecture.md), [Infra ADR-0003](decisions/ADR-0003-dev-storage-database-and-configuration.md), [Infra ADR-0004](decisions/ADR-0004-dev-runtime-and-observability-baseline.md), [Infra ADR-0005](decisions/ADR-0005-dev-frontend-origin-and-api-routing.md), [Infra ADR-0015](decisions/ADR-0015-cloudwatch-alarm-discord-delivery.md), [Infra ADR-0017](decisions/ADR-0017-runpod-ephemeral-sllm-serving.md), [Infra ADR-0018](decisions/ADR-0018-runpod-bootstrap-secrets-monitoring.md), [Infra ADR-0019](decisions/ADR-0019-bedrock-luna-dev-poc.md)과 [프로젝트 ADR-0027](../../project-wiki/references/decisions/ADR-0027-bedrock-gpt56-luna-dev-poc.md)다. Terraform 코드 구현과 실제 생성 여부를 구분한다. dev workload, DB migration과 기존 delivery 자원은 적용됐고 S3 dev release는 게시됐다. Alarm 전용 전달, Verify/Build 분리, RunPod와 Bedrock Terraform 변경은 실환경 적용 전이다.

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
| 비밀·설정 | Secrets Manager, Parameter Store | 결정 | 기존 컨테이너 적용·값 소유권 분리 코드 미적용 | Terraform은 컨테이너만 소유; AI·Discord·RunPod·GHCR 값은 TTY 명령과 AWSCURRENT, RunPod ID·digest·동기화 version은 비민감 SSM 제어 문서가 소유 |
| 관측성 | CloudWatch logs·metrics·alarms, SNS·Lambda | 결정 | 기존 6개 alarm 적용·전용 전달, 2개 app alarm과 RunPod 감시 코드 구현, AWS 미적용 | RunPod 30분 read-only heartbeat·API·Pod·endpoint·health·runtime·cost metric과 8개 alarm도 기존 전용 SNS/Lambda 사용 |
| 전달 | CodeConnections, CodePipeline V2, CodeBuild, CodeDeploy | 결정 | 기존 main source 적용됨·dev/분리 변경 미적용 | Terraform 적용 후 통합 dev 자동, Backend·Frontend 수동, 모두 QUEUED |
| 전달 저장소 | Pipeline artifact S3 | 결정 | 적용됨 | non-versioned, 객체 14일 만료; 업무용 S3·Terraform state와 분리 |
| 모델 실행 | RunPod shared F2 Pod, private Team Template | 결정 | 코드 구현·RunPod/Terraform 미적용 | Secure Cloud, GPU 1개, create/delete, Volume·SSH 없음 |
| 모델 image | private GHCR custom image | 결정 | 코드 구현·image 미게시 | 고정 base digest와 dependency lock, LoRA·base SLLM 및 STT supervisor, weight·token·adapter 미포함 |
| 모델 artifact | private data-model S3 `releases/sllm/` | 결정 | S3 dev release 게시 완료·이번 Terraform 미적용 | `dev-f2-handwritten-v05-qwen3-4b-full-v1` bundle 불변 게시, Pod에는 presigned URL만 전달 |
| 모델 설정 | RunPod Secret, AWS Secrets Manager, SSM endpoint/control set | 결정 | 코드 구현·AWS/RunPod 미적용 | 별도 SLLM·STT key, active/offline 두 URL, bootstrap generation·immutable resource ID·Secret version sync 관리 |
| 범용 모델 실행 | Bedrock GPT-5.6 Luna Global profile | 결정 | Terraform·runtime 코드 구현·AWS 미적용 | `general-dev-bedrock`, SigV4 Instance Role, 합성 dev 전용, 비스트리밍·`store=false` |
| 범용 모델 인증 | 앱 EC2 role·IMDSv2 | 결정 | Terraform 코드 구현·AWS 미적용 | Luna profile·foundation model·default project 최소 권한, token 필수·hop limit 2; 정적 Bedrock key 없음 |
| 범용 GPU 비교 | 전용 dev GPU EC2·암호화 EBS | 보류 | Terraform·runtime 미구현 | llama.cpp+24GB와 vLLM BnB+48GB 코드·seed 후보만 보존; Bedrock POC 후 필요할 때 별도 승인 |
| 공개 TLS | Route 53, ACM, ALB HTTPS | 제외 | 제외 | 현재 환경에는 도메인이 없고 실제 개인정보 사용 금지; 운영 승격 시 별도 결정 |
| 큐 | SQS, DLQ | 조건부 | 미확정 | RDS polling이 독립 재시도·확장을 충족하지 못할 때 |
| AI 분리 | ECS Fargate, Cloud Map | 조건부 | 미확정 | 경합·지연·독립 배포·장애 격리 필요 측정 후 |
| 제외 | GitHub Actions OIDC, NAT Gateway, Multi-AZ RDS | 제외 | 제외 | 1차 개발·시연 범위 |
| 제외 | WAF, ElastiCache, AWS Backup, EKS, Step Functions | 제외 | 제외 | 별도 요구·승인 전 |
| 제외 | Terraform 배포 Pipeline | 제외 | 제외 | 수동 Terraform 절차 유지 |

## 현재 구현 경계

- 현재 계정 bootstrap은 워크로드 자원을 만들지 않는다.
- `infra/environments/dev`의 네트워크·보안, S3·ECR·RDS·설정, EC2·ALB·ASG, 관측성과 DB migration은 적용됐다.
- CloudWatch Alarm 전용 SNS·Lambda·Secret, 기존 6개 alarm action 전환과 애플리케이션 alarm 2개는 코드·fixture 검증만 완료했으며 AWS에는 적용하지 않았다.
- ALB 삭제·CloudFront 비활성화 deep lifecycle은 코드와 운영 명령을 구현했으나 AWS saved plan 검토·apply 전이다.
- 세 Pipeline, 기존 CodeBuild/CodeDeploy, Discord 알림과 기존 IAM 운영자 policy attachment는 적용됐다. Verify/Build 분리 변경은 검증됐지만 승인 전에는 apply하지 않는다.
- RunPod는 Terraform provider 대신 Git Template 명세와 기본 dry-run bootstrap/reconcile,
  create/status/delete lifecycle 도구를 사용한다. S3에는 dev release bundle과 cross-hash manifest를
  게시했다. custom image·Template·Pod·Secret, SSM endpoint/control, EventBridge monitor와 alarm 자산 및
  이번 Terraform 변경은 아직 적용하지 않았다.
- Bedrock 공개 endpoint 설정, Luna 최소 권한 IAM, IMDSv2 hop limit 2와 추론 없는 doctor는
  코드에 구현했으며 saved plan 검토·apply 전이다. 정적 Bedrock key는 만들지 않는다.
- 범용 dev GPU EC2·EBS와 `dev-start` / `dev-stop` 통합은 보류했고 현재 Terraform에는 없다.
- Terraform state bucket은 애플리케이션 파일 저장소가 아니며 다른 용도로 재사용하지 않는다.
