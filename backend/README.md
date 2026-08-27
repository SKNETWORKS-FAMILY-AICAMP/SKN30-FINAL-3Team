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

로컬 인증이 필요하면 개발 계정을 생성합니다.

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
- `APP_ENV=test` 또는 `APP_ENV=prod`: dotenv 파일을 읽지 않고 CI·배포가 주입한 프로세스 환경변수만 사용합니다.
- 환경 선택에는 `APP_ENV` 하나만 사용합니다.
- API entrypoint는 검증된 `APP_HOST`와 `APP_PORT`로 Uvicorn listener를 시작합니다.
- Worker 설정도 같은 병합 결과에서 검증되므로 개인 `.env`의 `WORKER_*` 값이 전역 환경변수 변경 없이 적용됩니다.
- 활성 Worker의 Provider 설정은 AI 모듈 로더가 `ai/.env.local`, `ai/.env`, 프로세스 환경변수 순서로 별도 병합합니다.
- F2 음성메모 runtime은 Backend 시작 시 항상 초기화됩니다. `ai/.env.local` 또는 개인 `ai/.env`에
  `AI_VLLM_LLM_BASE_URL`과 `AI_VLLM_STT_BASE_URL`을 모두 설정해야 합니다.
