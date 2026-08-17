---
status: 계획됨
updated: 2026-08-17
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
| Queue | AWS SQS | 제안 |
| Container runtime | AWS ECS Fargate | 제안 |
| IaC | Terraform | 제안 |
| Runtime AWS integration | AWS SDK for Python (`boto3`) | 제안 |
| Model API | OpenAI·OpenAI-compatible vLLM adapter | 구현됨; 운영 선택 미확정 |
| GPU runtime | RunPod | 계획됨 |

## 역할 분리 후보

- SQS는 서비스 간 작업 전달, 재시도와 결합도 완화를 담당한다.
- LangGraph는 F3 에이전트 실행 내부의 상태·재개 기반으로 사용하고 F2 선형 흐름에는 강제하지 않는다. 상세 범위는 [AI ADR-0002](../../../ai/references/decisions/ADR-0002-langgraph-adoption.md)를 따른다.
- SQLModel 테이블 모델은 API 및 이벤트 공개 계약으로 직접 사용하지 않는다.
- Backend는 Yoyo로 순수 SQL 전진 migration을 적용하며 애플리케이션 시작 시 자동 적용하지 않는다.
- AWS SDK는 실행 중 AWS 서비스를 호출하는 데 사용하고 IaC 대체 수단으로 사용하지 않는다.

## 비용 제약

ECS Fargate를 사용한다면 ARM64 최소 태스크, Single-AZ 소형 PostgreSQL, 짧은 로그 보존을 우선 검토한다. NAT Gateway, Multi-AZ와 상시 다중 환경은 예산 영향이 크므로 별도 승인을 받는다.
