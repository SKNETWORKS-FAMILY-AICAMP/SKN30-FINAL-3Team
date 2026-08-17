---
status: 미확정
updated: 2026-08-17
---

# Infra 미해결 질문

| ID | 질문 | 영향 | 결정 시점 |
|---|---|---|---|
| INFRA-OQ-001 | IAM+MFA 임시 인증을 Identity Center로 언제 전환할 것인가? | 사용자 수명주기, 감사, 운영 접근 | 운영 자원 배포 전 |
| INFRA-OQ-002 | 공유 개발 RDS의 private 접속·백업·폐기 기준은 무엇인가? | 네트워크, 비용, 개발자 온보딩 | RDS 구현 전 |
| INFRA-OQ-003 | ECS의 공개 ingress와 외부 모델 egress를 어떻게 구성할 것인가? | NAT·endpoint 비용, 보안, 배포 | ECS 구현 전 |
| INFRA-OQ-004 | 업무용 S3의 버킷 분리와 수명주기는 무엇인가? | 음성·데이터셋·모델 보존과 접근 | 첫 파일 저장 전 |
| INFRA-OQ-005 | 조직 SCP로 차단된 AWS Budget을 조직 관리자가 제공할 것인가? | 비용 알림과 월 한도 추적 | 첫 유료 워크로드 생성 전 |

프로젝트 공통 미해결 질문인 ECS, 예산 범위, 보존기간, 큐와 비밀값 주입은 project-wiki `open-questions.md`를 정본으로 사용한다.
