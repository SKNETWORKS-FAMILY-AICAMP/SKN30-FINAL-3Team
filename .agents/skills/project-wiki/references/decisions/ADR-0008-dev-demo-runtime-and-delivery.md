---
status: 결정
updated: 2026-09-02
---

# ADR-0008: 개발·시연 런타임과 수동 전달 경로

- 상태: 부분 대체됨
- 전달 결정 대체: [ADR-0011](ADR-0011-dev-cicd-pipeline-modes.md)
- RunPod 운영 구체화: [ADR-0020](ADR-0020-sllm-release-handoff.md). 이 결정의 EC2 Backend,
  설치형 `brokerage-ai`, RunPod 추론이라는 상위 런타임 구조는 유지한다.
- 결정일: 2026-08-18
- 보완 결정: [ADR-0009](ADR-0009-dev-demo-operating-constraints.md)

## 맥락

F2·F3 AI 흐름을 두 달 예산 안에서 공동 개발하고 시연하려면 Backend, 설치형 AI 라이브러리, GPU 모델과 배포 책임을 구체적인 실행 단위로 정해야 한다. 기존 ADR-0006의 프레임워크·영속성 경계는 유지하면서 첫 배포 복잡도와 상시 비용을 제한해야 한다.

## 결정

- 공유 개발·시연 환경은 `ap-northeast-2`에 둔다.
- 1차 런타임은 `EC2 Backend + 설치형 brokerage-ai + RunPod Pod 추론`으로 한다.
- Backend API와 Worker는 같은 EC2 배포 호스트에서 별도 프로세스로 실행하며 `brokerage-ai`를 Python dependency로 호출한다.
- AI의 공개 경계는 기존 프레임워크 중립 Python DTO·interface를 유지한다. 이번 결정은 애플리케이션 API·DTO를 변경하지 않는다.
- LLM·STT·Embedding은 논리적으로 분리하고 물리적 Pod 통합 여부는 모델별 VRAM·처리량 평가 후 정한다.
- 애플리케이션 CI/CD는 GitHub App 기반 CodeConnections, CodePipeline V2, CodeBuild, Manual approval과 CodeDeploy를 사용한다.
- CodeConnections의 자동 변경 감지는 끈다. 수동 실행은 최신 `main`을 기본으로 하고 필요한 경우 `COMMIT_ID` source revision override로 특정 commit SHA를 선택한다.
- Frontend와 Backend+AI Build는 병렬 실행한다. 두 Build 성공 뒤 사람 승인을 받고, Backend CodeDeploy와 health 검증 후 Frontend를 배포한다.
- DB migration은 CodeDeploy lifecycle에서 명시적으로 실행하고 실패 시 배포를 중단한다. 자동 down migration 없이 전진 호환 migration만 허용한다.
- Terraform은 애플리케이션 Pipeline에 넣지 않고 기존 수동 `preflight → fmt/validate → plan → 승인 → apply → 검증 → drift plan` 절차를 유지한다.
- AWS 비용 참고 상한은 2026-09-23까지 누적 300,000원이며 Billing 자원으로 자동 집행하지 않는다. RunPod와 OpenAI는 각각 2개월 합계 USD 300으로 별도 관리한다.

## AI 독립 배포 조건

CPU·메모리 경합, API 지연, 독립 배포 또는 장애 격리 필요성이 측정될 때만 AI 실행부를 ECS Fargate와 Cloud Map으로 분리한다. 이때 Backend는 EC2에 남고 내부 client adapter가 기존 DTO를 전송한다. AI는 DB, ORM, Repository와 업무용 S3에 직접 접근하지 않으며 필요한 부수 효과는 Backend capability를 통해 수행한다.

## 결과

첫 배포는 단일 EC2의 운영 단순성과 RunPod GPU 선택 유연성을 얻는다. 반면 EC2 한 대가 API와 Worker의 공통 장애 지점이고, NAT 없는 public subnet 배치는 개발·시연 환경에만 허용된다. 자동 push 배포를 끄므로 배포 담당자가 revision과 승인 이력을 명시적으로 관리해야 한다.

구체적인 AWS 자원, 네트워크, 저장소 분리와 운영 규칙은 [Infra ADR-0002](../../../infra/references/decisions/ADR-0002-dev-demo-aws-runpod-architecture.md) 및 [아키텍처 문서](../../../../../docs/architecture/infra/overview.md)를 따른다.

## 제외 범위

- GitHub Actions OIDC, Terraform 배포 Pipeline
- 1차 SQS·DLQ와 독립 AI ECS 서비스
- NAT Gateway, Multi-AZ RDS, WAF, ElastiCache, AWS Backup, EKS, Step Functions
- 실제 AWS·RunPod 자원 생성과 애플리케이션 API·DTO 변경
