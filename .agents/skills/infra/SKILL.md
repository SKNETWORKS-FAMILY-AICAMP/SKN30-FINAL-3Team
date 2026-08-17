---
name: infra
description: "`infra/`의 Terraform 후보 기반 AWS·RunPod 인프라, 네트워크, IAM, 배포, 관측성과 비용 구성을 개발하거나 운영 환경을 변경할 때 사용한다. 프로젝트 공통 지식은 project-wiki와 함께 확인한다."
---

# 인프라 스킬 초안

이 스킬의 구조와 개발 방식은 절대 규칙이 아니라 기본 권장안이다. 작업 규모와 위험에 맞는 가장 단순한 설계를 우선하고, 권장안에서 벗어난 이유와 검증 방법을 PR에 남긴다. 장기 유지할 모듈 내부 결정은 `.agents/skills/infra/references/decisions/`에, 프로젝트 공통 결정·계약·정책은 project-wiki에 기록한다. 저장소 지침과 승인된 프로젝트·모듈 결정은 이 권장안보다 우선한다.

- 작업 위치: `infra/`
- IaC 권장 후보: Terraform
- AWS SDK는 애플리케이션 런타임 연동 수단이며 IaC 대안이 아님
- 클라우드 방향: AWS, RunPod
- AWS 후보: ECS Fargate, SQS, PostgreSQL/RDS, S3, ECR, CloudWatch
- AWS 예산 제약: 2개월 합계 300,000원
- 비용 우선 검토: ARM64 최소 태스크, Single-AZ, 짧은 로그 보존, 필요 시에만 Worker 실행
- NAT Gateway, Multi-AZ, 상시 다중 환경은 비용 영향을 확인하고 승인 후 도입
- 비밀값을 코드, Terraform 변수 기본값, 상태 출력 또는 로그에 기록하지 않음
- 로컬·CI·운영 비밀값의 저장, 접근 제어와 프로세스 환경변수 주입은 Infra가 담당
- 애플리케이션 모듈에는 비밀 저장소 클라이언트를 요구하지 않고 동일한 환경변수 인터페이스를 제공
- 저장소에서 관리하는 공개 `.env` 파일에는 비밀 변수의 실제 값이나 참조 식별자를 기록하지 않음
- 최소 권한 IAM과 환경별 자원 경계를 적용
- 내부 폴더 구조, Terraform state backend, 모듈화, CI/CD, 배포 전략과 관측성 규칙은 보류
- 작업 전 project-wiki와 존재하는 경우 `.agents/skills/infra/references/index.md`에서 관련 결정만 확인
