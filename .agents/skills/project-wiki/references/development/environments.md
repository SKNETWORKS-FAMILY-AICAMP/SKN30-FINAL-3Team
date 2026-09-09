---
status: 결정
updated: 2026-09-09
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

범용 모델의 local·dev 정책은 [ADR-0030](../decisions/ADR-0030-local-dev-dual-cloud-serving.md)을
따른다. local은 개인 OpenAI key와 기존 모델을 기본으로 유지한다. 공유 dev는 검증 후
Qwen을 활성화하고 f2/general별 AWS·RunPod를 명시 선택한다. Backend는 자신의 dotenv만
읽으며 AI에는 값을 주입한다. 개인 설정과 로컬 DB 모델 선택은 공유 dev 설정을 변경하지 않는다.
연결·검증 명령은 [LLM 운영 절차](../../../../../infra/serving/README.md)를 따른다.

AI 설정은 `ai/.env.local`/`ai/.env`만 소유한다. 로컬 API/Worker는 Infra launcher가
Backend·AI 입력을 각각 검증해 주입한다. 기존 Backend 개인 파일의 AI 입력은 명시적으로 이전한다.
[ADR-0034](../decisions/ADR-0034-module-owned-environment.md)와
[설정/실행 안내](../../../../../docs/development/environment-variables.md)를 따른다.

## 설정과 비밀값

- 공통 정책은 [ADR-0015](../decisions/ADR-0015-environment-configuration-ownership.md)와
  [입력 관리 보완 ADR-0033](../decisions/ADR-0033-environment-input-maintenance.md)을 따른다.
  변수별 설명은 각 모듈 `.env.local`/`.env.example`, 사람용 작성 절차는
  [환경변수 관리](../../../../../docs/development/environment-variables.md)가 소유한다.
- Backend F3 합성 opt-in도 같은 config 로더를 사용한다. 로컬 F2는 offline으로 시작하며
  연결 준비 후 SLLM/STT URL 쌍과 키를 지정한다. 미사용 embedding URL 기본값은 두지 않는다.
- 각 모듈의 Git 추적 `.env.local`에는 팀 공통 비민감 로컬 기본값만 둔다.
- 개발자는 비밀 또는 개인 입력 이름만 있는 `.env.example`을 Git에서 제외한 `.env`로 복사하고,
  비밀값과 의도적인 개인 override만 채운다. 선택 공개 override는 예시에서 주석 처리해 빈 값 덮어쓰기를 막는다.
- 로컬 우선순위는 `process env > .env > .env.local > 코드 기본값`이다. Backend·AI의 dev·test·prod는
  저장소 dotenv 파일을 읽지 않는다. Frontend build는 공개 `.env.local`을 읽고 CI·release의
  process env가 배포별 값을 덮는다. `.env.prod`와 모드별 dotenv 파일은 사용하지 않는다.
- 비밀값은 승인된 비밀 저장소에서 관리하고 Infra가 CI·운영 프로세스 환경변수로 주입한다.
- Backend를 포함한 애플리케이션 모듈은 비밀 저장소에 직접 접근하지 않고 주입된 환경변수만 읽는다.
- API 키, DB 접속 URL·비밀번호, 클라우드 자격 증명과 개인정보를 Git 또는 공개 `.env` 파일에 기록하지 않는다.
- dev 공개 설정은 Terraform map과 Parameter Store가 소유한다. AI·Discord·RunPod·GHCR 비밀값은
  Secrets Manager와 TTY 운영 명령이 소유하며 tfvars에 넣지 않는다. Terraform은 컨테이너만 관리한다.
  후속 소유권은 Infra ADR-0020·0022를 따른다.
- `just -f infra/justfile env-doctor` / `env-fix`로 로컬 이름·권한을 점검·정리한다.
  개인 파일을 다른 모듈·워크트리로 복사하지 않는다. [설정 관리 위치](../../../../../infra/operations/configuration.md)를 따른다.
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
- hook은 staged 상태의 `ai/`와 `backend/` 아래 Python 파일 전체에 모듈별 고정 Ruff 환경으로
  `ruff check --fix`를 먼저 실행하고 `ruff format`을 적용한다. `src/`와 `tests/` 변경에는 해당
  모듈의 Pyright도 실행한다.
- 에이전트는 Python 파일 변경을 마치기 전에 루트 `AGENTS.md`의 모듈별 Ruff 명령을 실행한다.
  이 완료 조건은 `eval/`, `training/`처럼 `src/`와 `tests/` 밖의 Python 파일에도 적용한다.
- 자동 수정이 발생하면 pre-commit이 커밋을 중단하며, 개발자는 변경분을 검토하고 다시 stage한 뒤
  커밋한다. hook 우회 가능성을 고려해 CodeBuild의 format·lint·type 검사를 유지한다.
- 루트 공통 Python 환경은 만들지 않으며 hook 실행 환경은 기존 Backend·AI 모듈 환경을 사용한다.
- hook은 `--locked`로 실행해 pyproject와 lock이 다르면 lock을 암묵적으로 바꾸지 않고 실패한다.
