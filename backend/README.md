# Brokerage Backend

Python 3.13과 uv를 사용하는 Backend 애플리케이션입니다.

## 설치

[uv](https://docs.astral.sh/uv/)를 준비한 뒤 의존성을 설치합니다.

```bash
cd backend
uv sync --frozen
```

배포 환경에서는 editable dependency를 남기지 않도록 설치합니다.

```bash
uv sync --frozen --no-editable
```

## 로컬 실행

팀 공통 공개 설정은 Git에서 추적하는 [`.env.local`](.env.local)에 있습니다. 비밀값과 개인별 재정의는 Git에서 제외되는 `.env`에 둡니다.

```bash
cp .env.example .env
```

`.env`에 로컬 DB URL을 입력합니다. 실제 비밀값은 `.env.example`, `.env.local` 또는 다른 추적 파일에 기록하지 않습니다.

DB migration을 적용합니다.

```bash
uv run --env-file .env python src/migration_guard.py
```

로컬 인증이 필요하면 개발 계정을 생성합니다. 이 명령과 sample 장부 seed 명령은
`APP_ENV=local`에서만 실행됩니다.

```bash
uv run python src/manage.py create-development-user \
  --brokerage-name "개발 중개사무소" \
  --login-id developer \
  --display-name "Developer" \
  --role OWNER
```

출력된 `brokerage_id`와 `login_id`를 개인 `.env`에 설정합니다.

```dotenv
AUTH_DEVELOPMENT_ENABLED=true
AUTH_DEVELOPMENT_BROKERAGE_ID=1
AUTH_DEVELOPMENT_LOGIN_ID=developer
```

개발 서버를 실행합니다.

```bash
uv run python src/server.py
```

## 설정 환경

- `APP_ENV=local`: `.env.local`을 읽고 개인 `.env`, 실행 프로세스 환경변수 순서로 덮어씁니다.
- `APP_ENV=dev`: 공유 AWS 개발 애플리케이션 환경입니다. `DB_TARGET=development`만 허용하고
  dotenv 파일을 읽지 않으며 배포 프로세스 환경변수만 사용합니다.
- `APP_ENV=test`: `DB_TARGET=test`, `APP_ENV=prod`: `DB_TARGET=production`만 허용합니다. 두 환경도
  dotenv 파일을 읽지 않고 CI·배포가 주입한 프로세스 환경변수만 사용합니다.
- 환경 선택에는 `APP_ENV` 하나만 사용합니다.
- 개발 세션 API는 `local` 또는 `dev`에서 `AUTH_DEVELOPMENT_ENABLED=true`와 완전한 합성 계정
  식별자가 함께 설정된 경우에만 등록됩니다. `prod`에서는 설정할 수 없습니다.
- 공유 `dev`는 세션 유휴 만료를 30분, 절대 만료를 720분으로 주입하며 세션·CSRF Cookie에
  `Secure`, `HttpOnly`, `SameSite=Lax`를 적용합니다. 실제 개인정보·계정·비밀번호를 넣지 않습니다.
- API entrypoint는 검증된 `APP_HOST`와 `APP_PORT`로 Uvicorn listener를 시작합니다.
- Worker 설정도 같은 병합 결과에서 검증되므로 개인 `.env`의 `WORKER_*` 값이 전역 환경변수 변경 없이 적용됩니다.
- 활성 Worker의 Provider 설정은 `local`에서만 `ai/.env.local`, `ai/.env`, 프로세스 환경변수 순서로
  병합합니다. `dev`, `test`, `prod`에서는 AI 설정도 프로세스 환경변수만 사용합니다.
