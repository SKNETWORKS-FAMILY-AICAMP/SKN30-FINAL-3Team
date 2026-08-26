---
status: 결정
updated: 2026-08-24
---

# 런타임 및 기술 후보

아래 항목은 명시적으로 `결정`으로 표시된 경우를 제외하면 후보 또는 계획이다.

| 영역 | 현재 방향 | 상태 |
|---|---|---|
| Frontend | React | 계획됨 |
| Backend | Python 3.13, uv, FastAPI | 결정 |
| Agent | Python 3.13, uv, LangGraph | 결정 |
| Data | Python | 계획됨 |
| Database | PostgreSQL 15, SQLModel, Yoyo 순수 SQL migration | 결정 |
| Queue | RDS 작업 polling | 결정; 1차 런타임 |
| Conditional queue | AWS SQS·DLQ | 조건부 |
| Backend runtime | EC2 ASG desired 1, API·Worker 논리 분리 | 결정; [ADR-0008](../decisions/ADR-0008-dev-demo-runtime-and-delivery.md) |
| AI package runtime | 같은 EC2에 설치한 `brokerage-ai` | 결정; AI ADR-0001 |
| Conditional AI runtime | ECS Fargate·Cloud Map | 조건부 |
| IaC | Terraform | 결정; [ADR-0007](../decisions/ADR-0007-terraform-iac.md) |
| Runtime AWS integration | AWS SDK for Python (`boto3`) | 제안 |
| Model API | OpenAI·OpenAI-compatible vLLM adapter | 구현됨; 운영 선택 미확정 |
| GPU runtime | RunPod Pod, 공용 Template | 운영 방향 결정; Terraform 소유 범위 보류 |
| Application CI/CD | 통합 자동·Backend 수동·Frontend 수동 CodePipeline V2 | 결정; 기존 main source 적용, dev/Verify·Build 분리 미적용 |

## 역할 분리 후보

- 1차에는 RDS 작업 상태를 API와 Worker가 공유한다. 독립 재시도, 지연 격리 또는 Worker 확장이 어려워진다는 측정 결과가 있을 때 SQS·DLQ를 도입한다.
- LangGraph는 F3 에이전트 실행 내부의 상태·재개 기반으로 사용하고 F2 선형 흐름에는 강제하지 않는다. 상세 범위는 [AI ADR-0002](../../../ai/references/decisions/ADR-0002-langgraph-adoption.md)를 따른다.
- SQLModel 테이블 모델은 API 및 이벤트 공개 계약으로 직접 사용하지 않는다.
- Backend는 Yoyo로 순수 SQL 전진 migration을 적용하며 애플리케이션 시작 시 자동 적용하지 않는다.
- AWS SDK는 실행 중 AWS 서비스를 호출하는 데 사용하고 IaC 대체 수단으로 사용하지 않는다.
- AI 실행부는 CPU·메모리 경합, API 지연, 독립 배포 또는 장애 격리 필요성이 측정될 때만 ECS로 분리한다. 분리 후에도 AI의 DB 직접 접근은 금지한다.
- 통합 Pipeline은 검증 gate 후 `dev` 변경을 자동 감지하고, Backend·Frontend 독립 Pipeline은 최신 `dev` 또는 지정 `COMMIT_ID`를 수동 배포한다. `main`은 릴리스 PR 기준으로 유지한다. 세 Pipeline은 `QUEUED`이며 Terraform 배포는 범위에서 제외한다.

## 비용 제약

AWS는 2026-09-23까지 누적 300,000원을 참고 상한으로 사용하고, RunPod와 OpenAI는 각각 2개월 합계 USD 300으로 분리한다. AWS Budget·Cost Anomaly Detection 자원은 만들지 않는다. 1차는 RDS `db.t4g.small`·gp3 20→50 GiB, EC2 `t3.small`·gp3 40 GiB와 ASG desired 1을 사용하고 NAT Gateway, Multi-AZ와 상시 다중 환경은 제외한다. RDS backup은 7일, CloudWatch log는 14일 보존하며 실제 부하와 누적 비용에 따라 적용 전 크기를 재검토한다.
