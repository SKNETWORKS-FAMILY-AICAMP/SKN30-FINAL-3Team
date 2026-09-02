---
status: 결정
updated: 2026-08-20
---

# ADR-0004: 개발 환경 runtime·관측성 구현 기준

- 상태: 부분 대체됨
- 결정일: 2026-08-18
- 대체 관계: ASG 최소·희망 용량과 용량 알람 결정은 [ADR-0009](ADR-0009-dev-power-lifecycle.md)가, EC2 instance class 결정은 [ADR-0010](ADR-0010-dev-ec2-instance-class.md)이, SNS 사람 수신 구독 제외는 [ADR-0015](ADR-0015-cloudwatch-alarm-discord-delivery.md)가 대체한다.

## 맥락

NAT 없는 개발·시연 VPC에서 Backend API와 Worker를 한 EC2 호스트에 배치하려면 public egress, 인스턴스 수명주기, 최소 권한, readiness와 로그·알람의 경계를 고정해야 한다. 애플리케이션 delivery는 별도 단계이고 RunPod Terraform은 보류 상태다.

## 결정

### EC2와 ALB

- Amazon Linux 2023 x86_64 최신 SSM public parameter, `t3.medium`, standard CPU credit를 기본값으로 사용한다.
- root volume은 암호화된 gp3 40 GiB이며 인스턴스 종료 시 삭제한다.
- NAT가 없고 subnet 자동 public IP가 꺼져 있으므로 Launch Template network interface에 public IPv4를 명시한다.
- ASG는 `min=desired=max=1`이며 두 public subnet을 사용한다. 애플리케이션이 아직 배포되지 않았으므로 health type은 `EC2`로 두고 lifecycle hook과 instance refresh는 사용하지 않는다.
- ALB는 CloudFront origin-facing managed prefix에서만 HTTP 80을 받고 App SG의 8000번으로 전달한다. Target Group readiness는 `/health/ready`다.
- SSH key와 22번 ingress를 만들지 않고 SSM Session Manager만 사용한다. IMDSv2 token을 강제하고 hop limit 1, metadata tag endpoint 비활성화를 적용한다.

### 부팅과 권한

- user data는 SSM을 먼저 활성화하고 Docker와 CloudWatch Agent 설치를 제한적으로 재시도한다. 애플리케이션 artifact, secret value와 접속 URL은 내려받거나 파일로 만들지 않는다.
- runtime IAM은 Backend runtime DB secret과 AI provider secret만 읽는다. migration DB secret과 Pipeline artifact 권한은 delivery 단계 전까지 허용하지 않는다.
- 업무용 임시 음성·data/model S3, Backend ECR pull, 비민감 SSM parameter, 사전 생성된 runtime log stream과 프로젝트 metric namespace만 최소 범위로 허용한다.

### 로그와 알람

- API, Worker, CloudWatch Agent, RDS PostgreSQL, RDS upgrade log group을 사전 생성하고 14일 보존한다.
- RDS는 `postgresql`, `upgrade` 로그 export를 활성화하며 DB 생성은 두 log group 생성 뒤에 진행한다.
- ALB unhealthy target·target 5xx, ASG in-service capacity, RDS CPU·free storage 알람을 SNS topic에 연결한다.
- SNS subscription은 만들지 않는다. 현재 topic은 후속 전달 연결점이며 사람에게 알림을 보낸다고 간주하지 않는다. 알람 메타데이터만 취급하므로 별도 KMS key는 만들지 않는다.

## Delivery 선행 계약

- Backend API와 Worker의 일반 startup 설정에서 `DB_MIGRATION_URL` 필수 요구를 분리하고 migration은 별도 delivery identity가 실행한다.
- artifact 설치, 8000번 프로세스 시작, `DB_URL`과 비민감 설정 조립, DB role·schema·최초 pgvector migration을 완료해야 한다.
- ALB health check의 동적 target private-IP Host header가 `TrustedHostMiddleware`에서 거부되지 않도록 Backend 계약을 정한다. 단순 hostname 목록 주입만으로 해결됐다고 가정하지 않는다.
- 이 계약을 완료하기 전 Target Group unhealthy는 예상 상태이며 ASG를 `ELB` health로 전환하지 않는다.

## 결과와 비용

- runtime·observability 단계까지의 read-only plan은 당시 `89 add / 0 change / 0 destroy`였다. 이후 Frontend 단계의 현재값은 ADR-0005와 자원 인벤토리의 96개 추가이며 어느 단계도 apply하지 않았다.
- 주요 고정비는 상시 `t3.medium`, gp3 40 GiB, EC2·ALB public IPv4와 ALB 시간·LCU다. CloudWatch custom metric·alarm·로그와 RDS log export도 사용량 비용이 발생한다.
- 실제 부하 검증과 누적 300,000원 참고 상한 검토에서 instance class·EBS 크기를 조정할 수 있다.

## 제외 범위

- 애플리케이션 artifact·secret value 배포와 migration 실행
- CodeDeploy·CodePipeline 권한과 lifecycle
- SNS 사람 수신 구독과 ALB access log S3
- RunPod Template·Pod·Secret Terraform 소유 범위
