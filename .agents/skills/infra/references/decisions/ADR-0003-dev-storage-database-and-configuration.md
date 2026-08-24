---
status: 결정
updated: 2026-08-24
---

# ADR-0003: 개발 환경의 저장소·데이터베이스·설정 기준

- 상태: 승인됨
- 결정일: 2026-08-18
- 부분 대체: 수동 비밀값과 공개 설정 주입 방식은 [ADR-0013](ADR-0013-dev-environment-materialization.md)에서 대체

## 맥락

개발·시연용 네트워크와 보안 경계 다음 단계로 업무용 S3, RDS PostgreSQL과 애플리케이션 설정 저장소를 구현하려면 비용·복구·삭제·비밀값 소유 기준을 먼저 고정해야 한다. RunPod의 Terraform 소유 범위와 GPU 구성은 아직 확정되지 않았으므로 이 결정에 포함하지 않는다.

## 결정

### RDS

- PostgreSQL 15.18, `db.t4g.small`, Single-AZ를 사용한다.
- 저장소는 암호화된 gp3 20 GiB로 시작하고 storage autoscaling 상한을 50 GiB로 둔다.
- 자동 백업은 7일 보존하고 deletion protection을 활성화한다.
- 환경 종료 시 final snapshot을 생성한 뒤 인스턴스를 삭제한다. snapshot의 최종 폐기 시점은 개인정보·복구 필요성을 검토한 종료 승인에서 정한다.
- `vector` extension은 최초 Backend DB migration에서 활성화한다. Terraform은 SQL을 실행하거나 extension schema를 소유하지 않는다.

### S3 수명주기

- 임시 음성은 애플리케이션의 성공·취소 즉시 삭제와 실패 1시간 이내 sweeper 삭제가 1차 통제다. S3 Lifecycle은 누락 방지 안전망으로 객체를 1일 후 만료한다.
- Data/model bucket의 `releases/` prefix는 2026-09-23까지 유효하다. S3 Lifecycle의 절대 만료 시각은 `2026-09-24T00:00:00Z`로 설정한다.
- Pipeline artifact는 생성 14일 후 만료한다.
- 각 bucket은 Terraform state, Frontend origin과 다른 업무 저장소로 재사용하지 않고 public access block, 기본 암호화와 최소 권한을 적용한다.

### 설정과 비밀값

- Secrets Manager는 Backend runtime DB URL, migration DB URL, AI provider API key용 container 3개와 접근 정책만 Terraform이 소유한다. 실제 secret value와 전체 접속 URL은 Terraform 코드, 변수 기본값, plan과 state에 넣지 않는다.
- ECR은 immutable tag를 사용하고 자동 lifecycle은 untagged image만 push 7일 후 만료한다. 배포 대상과 롤백용 tagged digest는 delivery 계약이 확정될 때까지 자동 삭제하지 않는다.
- Parameter Store에는 비민감 설정만 저장한다. SecureString을 Secrets Manager의 대체 경로로 사용하지 않는다.
- 애플리케이션은 저장소 클라이언트에 직접 의존하지 않으며 Infra가 런타임 프로세스 환경변수로 주입한다.

### 관측 보존

- 애플리케이션, ALB, RDS와 배포용 CloudWatch log group의 기본 보존기간은 14일이다.
- log group 구현은 후속 observability 단계에서 수행하며 원문 개인정보, 전체 프롬프트, 인증 헤더와 비밀값 로깅 금지를 유지한다.

## 결과

- RDS와 S3의 비용 상한 및 종료 동작을 Terraform plan에서 검토할 수 있다.
- final snapshot은 자동 삭제되지 않으므로 환경 종료 승인에서 소유자, 보존 근거와 폐기 일정을 별도로 기록해야 한다.
- 비밀값이 Terraform state에 들어가지 않으며 애플리케이션과 Infra의 주입 책임이 분리된다.

## 제외 범위

- RDS final snapshot의 정확한 폐기일과 법정·업무 보존기간
- 애플리케이션 migration 및 secret value 주입의 실행 구현
- RunPod Template·Pod·Secret의 IaC 소유 범위, GPU와 Pod 통합 구성
