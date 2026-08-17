---
status: 결정
updated: 2026-08-18
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
| GPU runtime | RunPod Pod, 공용 Template | 결정; 구현 계획됨 |
| Application CI/CD | CodeConnections → CodePipeline V2 → CodeBuild → CodeDeploy | 결정; 구현 계획됨 |

## 역할 분리 후보

- 1차에는 RDS 작업 상태를 API와 Worker가 공유한다. 독립 재시도, 지연 격리 또는 Worker 확장이 어려워진다는 측정 결과가 있을 때 SQS·DLQ를 도입한다.
- LangGraph는 F3 에이전트 실행 내부의 상태·재개 기반으로 사용하고 F2 선형 흐름에는 강제하지 않는다. 상세 범위는 [AI ADR-0002](../../../ai/references/decisions/ADR-0002-langgraph-adoption.md)를 따른다.
- SQLModel 테이블 모델은 API 및 이벤트 공개 계약으로 직접 사용하지 않는다.
- Backend는 Yoyo로 순수 SQL 전진 migration을 적용하며 애플리케이션 시작 시 자동 적용하지 않는다.
- AWS SDK는 실행 중 AWS 서비스를 호출하는 데 사용하고 IaC 대체 수단으로 사용하지 않는다.
- AI 실행부는 CPU·메모리 경합, API 지연, 독립 배포 또는 장애 격리 필요성이 측정될 때만 ECS로 분리한다. 분리 후에도 AI의 DB 직접 접근은 금지한다.
- Pipeline은 `DetectChanges=false`로 자동 push 실행을 끄고 최신 `main` 또는 지정 `COMMIT_ID`를 수동 배포한다. Terraform 배포는 Pipeline 범위에서 제외한다.

## 비용 제약

AWS는 2개월 합계 300,000원, RunPod와 OpenAI는 각각 2개월 합계 USD 300으로 분리한다. 1차는 Single-AZ 소형 PostgreSQL과 ASG desired 1을 사용하고 NAT Gateway, Multi-AZ와 상시 다중 환경은 제외한다. 정확한 instance class와 로그·백업 보존기간은 구현 전 확정한다.
