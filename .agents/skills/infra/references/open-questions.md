---
status: 미확정
updated: 2026-08-18
---

# Infra 미해결 질문

| ID | 질문 | 영향 | 결정 시점 |
|---|---|---|---|
| INFRA-OQ-001 | IAM+MFA 임시 인증을 Identity Center로 언제 전환할 것인가? | 사용자 수명주기, 감사, 운영 접근 | 운영 자원 배포 전 |
| INFRA-OQ-002 | RDS 자동 백업 보존기간과 환경 종료 시 final snapshot·폐기 기준은 무엇인가? | 비용, 복구, 개인정보 삭제 | RDS 구현 전 |
| INFRA-OQ-003 | 조건부 ECS AI 내부 호출의 인증·암호화·service discovery와 외부 모델 egress를 어떻게 구성할 것인가? | 보안, 재시도, 비용, 장애 격리 | ECS 도입 ADR 전 |
| INFRA-OQ-004 | 데이터·모델 artifact, Pipeline artifact와 CloudWatch log의 정확한 수명주기는 무엇인가? | 비용, 재현성, 개인정보 삭제 | 첫 저장소 구현 전 |
| INFRA-OQ-005 | 조직 SCP로 차단된 AWS Budget을 조직 관리자가 제공할 것인가? | 비용 알림과 월 한도 추적 | 첫 유료 워크로드 생성 전 |
| INFRA-OQ-006 | 공개 API 도메인, Route 53 hosted zone과 ACM 인증서 소유권은 어떻게 정할 것인가? | HTTPS, 개인정보 전송, DNS 운영 | 실제 개인정보 시연 전 |
| INFRA-OQ-007 | EC2·RDS class와 LLM·STT·Embedding GPU·Pod 통합 구성을 어떤 부하·VRAM 결과로 정할 것인가? | 비용, 지연, 가용성 | workload Terraform·RunPod 생성 전 |

프로젝트 공통 미해결 질문인 보존기간, 큐 전환 계약과 Identity Center는 project-wiki `open-questions.md`를 정본으로 사용한다. 첫 런타임, 분리된 예산과 비밀 저장 제품은 [ADR-0008](../../project-wiki/references/decisions/ADR-0008-dev-demo-runtime-and-delivery.md) 및 [Infra ADR-0002](decisions/ADR-0002-dev-demo-aws-runpod-architecture.md)에서 해결됐다.
