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

먼저 [`.env.example`](.env.example)에 선언된 `DB_URL`과 `DB_MIGRATION_URL`을 실행 프로세스 환경변수로 주입합니다. 실제 비밀값은 저장소의 환경 파일에 기록하지 않습니다.

DB migration을 적용합니다.

```bash
uv run yoyo apply --batch
```

로컬 인증이 필요하면 개발 계정을 생성합니다.

```bash
uv run python src/manage.py create-development-user \
  --brokerage-name "개발 중개사무소" \
  --login-id developer \
  --display-name "Developer" \
  --role OWNER
```

출력된 `brokerage_id`와 `login_id`를 `.env.local`에 설정합니다.

```dotenv
AUTH_DEVELOPMENT_ENABLED=true
AUTH_DEVELOPMENT_BROKERAGE_ID=1
AUTH_DEVELOPMENT_LOGIN_ID=developer
```

개발 서버를 실행합니다.

```bash
uv run uvicorn main:app --app-dir src --reload
```
