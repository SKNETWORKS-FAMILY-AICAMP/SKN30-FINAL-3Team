---
status: 구현됨
updated: 2026-09-10
---

# 인프라 적용 인벤토리

이 문서는 **적용 여부의 정본**이다. 실시간 전원·endpoint·Secret 상태는 `just -f infra/justfile doctor`로 조회한다.
README·아키텍처 문서에는 적용 상태를 복제하지 않는다. 선택 근거는 [결정 인덱스](decisions/index.md),
일상 명령은 [개발자 운영](../../../../infra/operations/README.md)을 따른다.
2026-09-10 새 F2/general 이미지를 공유 dev에 적용하고 공식 `dev-start`·`dev-verify`의 앱 합성 요청·직접 추론·identity 및 VRAM 관측을 통과했다.
기동 plan의 기존 SNS 알림 구독 1건 복구 후 후속 drift가 없음을 확인했다. 이미지·기동 근거는
[새 이미지 적용 기록](../../../../infra/serving/image-rollout-validation-2026-09-10.md)에서 확인한다.
적용 사실과 실제 기동·추론·품질 승격은 별개다.

| 영역 | 적용·구현 범위 | 남은 조건 |
|---|---|---|
| 계정/state | IAM·MFA·TerraformOperatorRole·S3 원격 state 적용 | 2026-09-09 state version Deny 확대 적용·AWS 대조·drift 없음 확인 |
| 네트워크 | 서울 VPC·public/private subnet·IGW·S3 Gateway Endpoint·SG 적용 | NAT·IPv6·새 도메인 없음 |
| 앱·edge | EC2/ASG·ALB·CloudFront/OAC·deep lifecycle 적용 | deep 중지 시 ALB 제거·CF 비활성·ASG 0; 실제 상태는 doctor |
| RDS | PostgreSQL 15.18·db.t4g.small·20GiB/최대50GiB·비공개·암호화·IAM·백업7일 | 기존 migration 이력 있음. 최신 migration은 새 앱 배포에서 확인 |
| 저장소 | audio·data-model·frontend·pipeline S3, Backend/AI·CI pgvector ECR 적용 | immutable tag·scan·digest 배포, state와 업무 bucket 분리 유지 |
| 전달 | 3개 dev source Pipeline·QUEUED·Verify/Build 분리·CodeDeploy 적용 | 9/9 통합 Pipeline 성공; 9/10 검증된 정확한 revision 복원 및 앱 기동 성공 |
| 관측 | 전용 Alarm SNS/Lambda·Backend/AI 오류 alarm 적용 | RunPod 자체 감시 제거. 실제 알림 전달 시험과 설정 확인을 구분 |
| 비밀/설정 | Secret 컨테이너·SSM·TTY 회전·프로세스별 주입 구현·기반 적용 | 저장·구조·인증·배포 반영은 별도 확인 |
| RunPod | F2/general Console Template·registry·Secret 참조·SSM 등록됨 | 9/10 새 F2/general digest 게시·기존 Template 반영·SSM 등록 완료 |
| 공유 선택 | F2 consultation-v3 / RunPod RTX 4090, general Qwen3.8-27B-FP8 / RunPod L40S와 새 digest를 SSM에 저장 | 9/10 두 endpoint active; DB 대기 요청 0·모델 호환 확인, DB 설정 변경 없음 |
| GPU 실행 | RunPod create/delete와 AWS GPU EC2/EBS·SG·IAM·SSM 통합 코드·기반 적용 | 9/10 RunPod 두 GPU 준비 및 앱 합성 요청 성공; AWS 전환·왕복 검증은 별도 |
| Bedrock | alias·Instance Role 최소 권한 기반 적용 | 이번 점검에서 실제 추론·DB 활성 모델은 미확인 |
| 기존 F2 모델 | dev-f2-handwritten-v05-qwen3-4b-full-v1 S3 게시됨 | 미평가 dev 경로, 자동 활성화 없음 |
| 신규 F2 모델 | consultation-v3 LoRA 번들 검증·별도 catalog 등록 | 9/9 S3 게시·checksum 검증, 9/10 새 이미지·RTX 4090 기동과 앱 합성 요청 성공 |

## 이번 운영 개선

설정·클라우드 진단, 사용자 기동 후 검증, F2 선택과 이미지 게시 명령을 구현했다.
saved plan은 600 권한·입력 fingerprint·24시간 유효기간을 사용한다. 개인 `.env`는 모듈/워크트리 간 복사하지 않는다.
9/10 사용자 요청에 따라 정지·새 이미지 선택·Template 적용·서비스 기동을 수행했다.
실제 적용 범위와 검증 한계는 위 적용 기록에서 구분한다. [ADR-0023](decisions/ADR-0023-developer-operations-entrypoints.md)을 따른다.

## 조건부·제외

ECS/Cloud Map·SQS/DLQ·Route53/ACM은 별도 조건과 결정 전까지 미도입이다.
GitHub Actions OIDC·NAT·Multi-AZ RDS·Terraform 배포 Pipeline은 1차 범위에서 제외한다.
AWS Budget·Cost Anomaly Detection은 계정에서 사용 불가하므로 만들지 않는다.
2026-09-23까지 누적 300,000원은 참고 상한이며 자원 목록은 청구액 조회가 아니다.
이전 후보·측정 증거는 [서빙 검증](../../../../infra/serving/validation.md)에 보존한다.
