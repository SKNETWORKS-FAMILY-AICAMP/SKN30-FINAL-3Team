---
status: 결정
updated: 2026-08-18
---

# Infra reference 인덱스

현재 작업과 직접 관련된 문서만 읽는다.

| 문서 | 읽는 조건 |
|---|---|
| [resource-inventory.md](resource-inventory.md) | 아키텍처에 필요한 AWS·RunPod 자원과 도입 상태를 확인할 때 |
| [인프라 아키텍처](../../../../docs/architecture/infra/overview.md) | VPC 배치, 시스템 흐름, 저장·삭제와 조건부 확장을 확인할 때 |
| [배포·운영 구조](../../../../docs/architecture/infra/deployment-and-operations.md) | CodePipeline·CodeDeploy, RunPod, 관측·비용 운영을 확인할 때 |
| [RunPod Console 등록·일상 운영](../../../../infra/runpod/README.md) | Secret·registry·Template 최초 설정, SSM 등록, release 게시·Pod 생성·삭제·복구를 수행할 때 |
| [CloudWatch Alarm 장애 대응](../../../../docs/operations/cloudwatch-alarm-response.md) | Alarm Discord 메시지의 링크·안전 로그로 장애를 조사할 때 |
| [terraform-standards.md](terraform-standards.md) | Terraform root, state, 변수, 출력, 검증 방식을 변경할 때 |
| [aws-account-bootstrap.md](aws-account-bootstrap.md) | AWS 계정 인증, state bootstrap, 비용·IAM 기본 설정을 다룰 때 |
| [decisions/index.md](decisions/index.md) | Infra 내부 구조나 운영 방식을 변경하기 전에 승인 결정을 확인할 때 |
| [open-questions.md](open-questions.md) | 아직 승인되지 않은 배포·보안·운영 선택에 의존할 때 |
| [AWS·RunPod LLM 운영](../../../../infra/serving/README.md) | f2/general 등록, local 연결, 전환, GPU 캐시·전원과 실제 검증을 수행할 때 |

모델별 선택·동일 조건 평가·프로필 provenance는 [3모델 비교 기록](../../../../infra/serving/model-comparison-2026-09-08.md)을 확인한다.
