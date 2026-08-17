---
status: 계획됨
updated: 2026-08-17
---

# 인프라 자원 인벤토리

아래 상태는 아키텍처 문서를 인프라 관점에서 분류한 것이며 `제안`과 `미확정` 자원을 승인된 선택으로 바꾸지 않는다.

| 영역 | 후보 자원 | 상태 | 도입 조건 |
|---|---|---|---|
| 계정 기반 | IAM, Budget, S3 Terraform state | 구현됨(Budget 제외) | IAM·state는 적용됨; Budget은 조직 SCP 해제 또는 조직 관리자 제공 필요 |
| 데이터베이스 | RDS PostgreSQL 15, pgvector | 계획됨 | 공유 개발 DB 범위, 접근 경로, 백업·폐기 승인 |
| 네트워크 | VPC, subnet, security group, ingress | 미확정 | RDS 또는 컨테이너 첫 배포 설계 승인 |
| 파일 | F2 임시 음성용 암호화 저장소 | 제안 | 성공 즉시 삭제, 실패 최대 1시간 정책과 Backend 계약 확정 |
| 데이터·모델 | 데이터셋, 평가 보고서, 현재·직전 모델 artifact 저장소 | 제안 | Data·AI 저장 포맷, 접근 주체와 버전 정책 확정 |
| 컨테이너 | ECR, ECS Fargate API·Worker·인덱싱 Worker | 제안 | OQ-004와 인터넷 egress·ingress·용량 결정 |
| 큐 | SQS, DLQ | 제안 | OQ-009와 멱등성·재시도·보존 정책 결정 |
| 모델 실행 | RunPod/vLLM 또는 외부 모델 API | 계획됨 | 비용 범위, 개인정보 전송과 운영 모델 제공자 결정 |
| 관측성 | CloudWatch logs·metrics·alarms | 계획됨 | 배포 자원과 로그 보존·마스킹 정책 확정 |
| 공개 진입 | ALB, DNS, 인증서, Frontend hosting | 미확정 | 공개 배포 아키텍처와 도메인 확정 |

## 현재 구현 경계

- 이번 계정 bootstrap은 워크로드 자원을 만들지 않는다.
- `infra/environments/dev`는 계정·리전 조회만 수행한다.
- RDS, VPC, EC2, ECS, ECR, SQS, RunPod와 업무용 S3는 후속 결정 전까지 Terraform state에 추가하지 않는다.
- Terraform state bucket은 애플리케이션 파일 저장소가 아니며 다른 용도로 재사용하지 않는다.
