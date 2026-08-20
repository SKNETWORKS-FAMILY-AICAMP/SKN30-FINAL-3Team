---
status: 결정
updated: 2026-08-18
---

# ADR-0009: 개발·시연 환경의 기간·접근·데이터 보완 결정

- 상태: 승인됨
- 결정일: 2026-08-18
- 보완 대상: [ADR-0008](ADR-0008-dev-demo-runtime-and-delivery.md), [Infra ADR-0002](../../../infra/references/decisions/ADR-0002-dev-demo-aws-runpod-architecture.md)

## 맥락

개발·시연 런타임과 전달 구조를 승인한 뒤 실제 계정에서 AWS Budget과 Cost Anomaly Detection을 사용할 수 없다는 제약, 프로젝트 종료일, 도메인 부재와 브라우저 동일 origin 요구가 확인됐다. Identity Center 사용 가능 여부, release artifact 종료 기준과 pgvector 활성화 책임도 구현 전에 명확히 해야 한다.

이 ADR은 기존 런타임·전달 선택을 대체하지 않는다. 다만 비용 기간, AWS Billing 자원, 브라우저 진입 경로, 도메인·TLS, Identity Center, release artifact와 pgvector에 관해서는 이 보완 결정이 우선한다.

## 결정

### 기간과 비용

- AWS 비용 상한은 월별 한도가 아니라 **2026-09-23까지 누적 300,000원**이다.
- 이 계정에서는 AWS Budget과 Cost Anomaly Detection 등 Billing 관련 서비스를 사용할 수 없으므로 해당 서비스 자원을 만들지 않는다.
- 300,000원은 운영 판단을 위한 참고 상한이며 사용 허가나 자동 차단 장치가 아니다. 비용 발생 변경은 예상 비용, 소유자와 `ExpiresAt=2026-09-23`을 검토한다.
- RunPod와 OpenAI의 기존 별도 한도는 ADR-0008을 유지한다.

### 계정 접근

- Identity Center는 사용할 수 있다.
- 첫 유료 workload apply 전에 permission set, 사용자·그룹 할당, `TerraformOperatorRole` trust 전환과 기존 IAM 사용자 권한 폐기 절차를 확정한다.
- 이 세부 전환이 검토되기 전에는 기존 임시 IAM+MFA 접근을 운영 workload의 확정 접근 모델로 간주하지 않는다.

### 브라우저 진입과 개인정보

- 현재 프로젝트에는 사용자 소유 도메인이 없으며 개발·시연 Frontend는 CloudFront 기본 도메인을 사용한다.
- CloudFront는 private S3 Frontend origin과 ALB custom origin을 함께 사용한다. `/api/*` behavior는 ALB로 전달해 브라우저에 동일 origin API를 제공한다.
- Viewer는 HTTPS로 CloudFront에 접속한다. CloudFront와 ALB 사이는 HTTP를 사용하며, ALB HTTP ingress는 CloudFront origin-facing managed prefix list에서만 허용한다. 브라우저가 ALB를 직접 호출하는 경로는 제공하지 않는다.
- Route 53, 사용자 소유 도메인, ACM 인증서와 ALB HTTPS listener는 현재 개발·시연 환경에 만들지 않는다.
- CloudFront viewer 구간만 TLS이고 origin 구간은 HTTP이므로 실제 개인정보 트래픽은 계속 금지한다. 합성·비식별 데이터만 사용한다.

### release artifact와 데이터베이스

- Data/model S3의 승인된 release artifact는 2026-09-23까지 유효하다. 환경 종료 시 반출 필요성을 확인한 뒤 만료·삭제한다.
- PostgreSQL 15의 `vector` extension은 공유 환경에 적용하는 최초 DB migration에서 활성화한다.
- Terraform은 SQL migration을 실행하거나 pgvector schema를 소유하지 않는다. migration 파일, 적용 명령과 이력은 Backend DB migration 경계가 소유한다.
- Backend·AI·Frontend의 Dockerfile, 실행 명령, Worker 준비 상태, build 오류 수정과 배포 계약 준비는 별도 작업 범위다. Infra 전달 자원은 그 계약을 임의로 가정하지 않는다.

## 결과

- AWS 비용 자동 알림이나 차단을 전제로 할 수 없으므로 모든 유료 자원 변경에서 종료일과 예상 비용을 사람이 검토해야 한다.
- 브라우저 세션 cookie와 CSRF 요청은 CloudFront 기본 도메인의 동일 origin에서 처리할 수 있다.
- 현재 진입 경로는 실제 개인정보를 다루는 운영 보안 기준이 아니며 운영 승격 시 도메인, 종단 간 TLS와 접근 통제를 새로 결정해야 한다.
- pgvector 사용 가능성은 최초 DB migration으로 재현되며 Terraform state에 SQL 부수 효과가 섞이지 않는다.

## 제외 범위

- Identity Center permission set과 trust policy의 구체 구현
- AWS 비용을 대신 추적할 외부 도구 또는 수동 장부 선택
- Pipeline artifact와 CloudWatch log의 정확한 보존기간
- 애플리케이션 배포 선행 작업 구현
