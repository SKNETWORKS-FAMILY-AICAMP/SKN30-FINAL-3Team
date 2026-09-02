---
status: 결정
updated: 2026-09-01
---

# ADR-0015: 환경설정과 비밀값의 소유권을 환경별로 분리

- 상태: 부분 대체됨
- 결정일: 2026-08-24
- 관련 문서: [개발환경 원칙](../development/environments.md), [공유 dev 환경](ADR-0017-shared-dev-development-session.md)
- 대체 범위: 운영 AI·Discord 비밀값의 Terraform tfvars/version 소유 방식은 [ADR-0021](ADR-0021-runpod-operations-and-secret-ownership.md)에서 대체한다.

## 맥락

로컬 공개 설정, 개인 비밀값, 배포 설정과 정적 Frontend build 값이 모듈 파일과 Infra에
중복되면서 새 환경변수를 추가할 때 여러 loader·allowlist·CodeBuild block과 manifest를 함께
수정해야 했다. 반대로 설정 정본을 별도 JSON 계약으로 만들면 애플리케이션과 Terraform 외에 또
하나의 변경 지점이 생긴다.

## 결정

- 각 모듈의 Git 추적 `.env.local`은 팀 공통 비민감 로컬 기본값만 소유한다.
- Git에서 제외한 `.env`는 개발자가 `.env.example`을 복사해 만드는 개인 비밀값·override 파일이다.
  `.env.example`에는 비밀 또는 개인 입력이 필요한 변수 이름만 빈 값으로 둔다.
- 로컬 설정 우선순위는 `process env > .env > .env.local > 코드 기본값`이다. Backend·AI의
  dev·test·prod는 저장소 dotenv 파일을 읽지 않고 process env만 사용한다. Frontend build는 공개
  공통값인 `.env.local`을 읽되 CI·release의 process env가 배포별 값을 덮는다.
- `.env.prod`와 모드별 dotenv 파일은 사용하지 않는다. 배포별 비민감 Backend·AI 설정은 Terraform
  map이 Parameter Store에 기록하고, 배포가 프로세스별 env 파일로 주입한다.
- 수동으로 제공하는 AI Provider key와 Discord webhook은 Git에서 제외한 tfvars에서 받는다.
  Terraform의 ephemeral input과 Secrets Manager write-only version 인자를 사용해 plan과 state에
  값을 남기지 않으며, 회전할 때 비민감 version 번호를 함께 증가시킨다.
- RDS 비밀번호와 migration IAM token처럼 서비스가 자동 생성하는 비밀값은 기존 자동 생성 경계를
  유지한다.
- Frontend `VITE_*`는 공개 build-time 설정이다. 로컬 기본값은 `frontend/.env.local`, 배포별 값은
  Terraform의 단일 Frontend build map이 CodeBuild process env로 전달한다. 동일 origin `/api`
  경로를 사용하며 도메인이나 비밀값을 bundle에 넣지 않는다.
- 환경설정용 JSON 정본이나 release manifest schema를 추가하지 않는다. 기존 release manifest는
  artifact 식별과 무결성 정보만 계속 소유한다.

## 결과

새 공개 설정은 애플리케이션이 사용하는 변수와 로컬 `.env.local`, 필요한 환경의 Terraform map만
수정한다. 배포 loader와 CodeBuild는 map을 동적으로 전달하므로 변수별 중복 block을 만들지 않는다.
개인 `.env`에 공통 공개값을 복사하면 팀 기본값을 계속 가리므로 개발자는 비밀값과 의도적인
override만 남겨야 한다.

write-only 비밀값은 내용 변경을 Terraform이 비교할 수 없으므로 tfvars의 version 번호 증가가
회전 trigger다. plan과 apply 사이에는 같은 비밀값 파일을 유지해야 한다.
