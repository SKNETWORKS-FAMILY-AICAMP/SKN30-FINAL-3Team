---
status: 결정
updated: 2026-08-27
---

# 개발환경 원칙

## 루트 환경

- 루트에 공통 Python `pyproject.toml`, 가상환경 또는 lock 파일을 초기 생성하지 않는다.
- `backend`, `ai`, `data`는 독립 실행·배포 가능성을 유지하고 각자 의존성과 lock을 관리한다. Backend는 AI를 `../ai` path dependency로 설치하되 루트 uv workspace는 만들지 않는다.
- 전체 저장소에 공통 도구가 실제로 필요해지면 별도 결정 후 루트 워크스페이스를 도입한다.
- `frontend`는 자신의 JavaScript/TypeScript 환경을 관리한다.

## 환경 구분

- 로컬: 각 모듈의 빠른 개발과 필요한 서비스 조합 실행
- CI: PR 검증을 위한 일회성 환경
- 공유 dev: `infra/environments/dev`가 소유하는 합성·비식별 개발·시연 배포
- prod: 실제 사용자와 데이터를 위한 운영 배포. 현재 Terraform root와 자격증명 로그인은 없음

공유 dev의 애플리케이션 환경·개발 세션 경계는
[ADR-0017](../decisions/ADR-0017-shared-dev-development-session.md)을 따른다. 별도 staging 환경은
필요성과 비용이 확인되기 전에는 추가하지 않는다.

## 설정과 비밀값

- 공통 정책의 정본은 [ADR-0015](../decisions/ADR-0015-environment-configuration-ownership.md)다.
- 각 모듈의 Git 추적 `.env.local`에는 팀 공통 비민감 로컬 기본값만 둔다.
- 개발자는 비밀 또는 개인 입력 이름만 있는 `.env.example`을 Git에서 제외한 `.env`로 복사하고,
  비밀값과 의도적인 개인 override만 채운다.
- 로컬 우선순위는 `process env > .env > .env.local > 코드 기본값`이다. Backend·AI의 dev·test·prod는
  저장소 dotenv 파일을 읽지 않는다. Frontend build는 공개 `.env.local`을 읽고 CI·release의
  process env가 배포별 값을 덮는다. `.env.prod`와 모드별 dotenv 파일은 사용하지 않는다.
- 비밀값은 승인된 비밀 저장소에서 관리하고 Infra가 CI·운영 프로세스 환경변수로 주입한다.
- Backend를 포함한 애플리케이션 모듈은 비밀 저장소에 직접 접근하지 않고 주입된 환경변수만 읽는다.
- API 키, DB 접속 URL·비밀번호, 클라우드 자격 증명과 개인정보를 Git 또는 공개 `.env` 파일에 기록하지 않는다.
- 배포별 비민감 Backend·AI 설정은 Terraform map과 Parameter Store, 수동 AI key·Discord webhook은
  ignored tfvars와 Secrets Manager가 소유한다. Terraform input은 ephemeral, secret version 값은
  write-only로 전달하고 회전 version 번호만 plan·state에 남긴다.
- Frontend 공개 build 값은 로컬 `.env.local`과 Terraform Frontend build map이 소유하며 CodeBuild
  process env가 release build에 주입한다. `VITE_*`에는 비밀값을 넣지 않는다.
- 로컬·dev·prod에서 같은 애플리케이션 인터페이스를 유지하되 개발 세션 route는 local·dev에만 둔다.

## 재현성

- 모듈별 런타임과 도구 버전을 명시한다.
- 의존성 잠금 파일은 해당 모듈이 생성될 때 모듈 내부에서 관리한다.
- 컨테이너 이미지는 모듈에 필요한 의존성만 포함한다.

## 커밋 전 자동 포맷

- 루트 `.pre-commit-config.yaml`이 AI·Backend Python 파일의 공통 커밋 전 hook 정본이다.
- 개발자는 저장소 루트에서 `uv run --locked --project backend pre-commit install`을 한 번 실행한다.
- hook은 staged 상태의 `ai/src`, `ai/tests`, `backend/src`, `backend/tests` Python 파일에 모듈별
  고정 Ruff 환경으로 `ruff check --fix`를 먼저 실행하고 `ruff format`을 적용한 뒤 해당 모듈의
  Pyright를 실행한다.
- 자동 수정이 발생하면 pre-commit이 커밋을 중단하며, 개발자는 변경분을 검토하고 다시 stage한 뒤
  커밋한다. hook 우회 가능성을 고려해 CodeBuild의 format·lint·type 검사를 유지한다.
- 루트 공통 Python 환경은 만들지 않으며 hook 실행 환경은 기존 Backend·AI 모듈 환경을 사용한다.
- hook은 `--locked`로 실행해 pyproject와 lock이 다르면 lock을 암묵적으로 바꾸지 않고 실패한다.
