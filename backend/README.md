# Brokerage Backend

Python 3.13, uv, FastAPI를 사용하는 Backend 애플리케이션입니다.

## 로컬 프로세스 구성

API와 Worker는 같은 Backend 패키지와 DB를 사용하지만 서로 다른 프로세스로 실행합니다.

| 프로세스 | 진입점 | 역할 |
|---|---|---|
| API | `src/server.py` | HTTP API와 F2 runtime 제공, F3 실행 요청을 DB에 적재 |
| Worker | `src/worker.py` | DB를 polling해 F3 실행을 선점하고 AI 파이프라인 처리 |

API를 실행해도 Worker는 자동으로 시작되지 않습니다. F3 실행을 끝까지 확인하려면 API와 활성
Worker를 각각 실행해야 합니다. DB migration도 애플리케이션 시작과 분리되어 있으므로 먼저
명시적으로 적용합니다.

## 1. 의존성 설치

[uv](https://docs.astral.sh/uv/)와 Python 3.13을 준비한 뒤 Backend 의존성을 설치합니다.

```bash
cd backend
uv sync --frozen
```

배포 환경에서는 editable dependency를 남기지 않도록 설치합니다.

```bash
uv sync --frozen --no-editable
```

## 2. 로컬 PostgreSQL 실행

저장소 루트에서 로컬 DB 설정 파일을 만들고 PostgreSQL 15 컨테이너를 실행합니다.

```bash
cp infra/local/.env.example infra/local/.env
```

`infra/local/.env`에 `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`를 채운 다음 실행합니다.

```bash
docker compose --env-file infra/local/.env -f infra/local/compose.yaml up -d
```

세부 내용은 [로컬 개발 DB 안내](../infra/local/README.md)에 있습니다.

## 3. Backend 로컬 설정

팀 공통 비민감 설정은 Git에서 추적하는 [`.env.local`](.env.local)에 있습니다. DB 접속 정보,
API Key와 개인별 재정의는 Git에서 제외되는 `.env`에 둡니다.

```bash
cd backend
cp .env.example .env
```

`backend/.env`에 애플리케이션과 migration이 사용할 로컬 DB URL을 설정합니다. 비밀번호에 URL
예약 문자가 있으면 percent-encoding해야 합니다.

```dotenv
DB_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:5432/<database>
DB_MIGRATION_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:5432/<database>
```

실제 비밀값은 `.env.example`, `.env.local` 또는 다른 추적 파일에 기록하지 않습니다.

## 4. DB migration 적용

`backend/`에서 migration guard를 실행합니다. 애플리케이션이나 Worker가 migration을 자동으로
적용하지 않습니다.

```bash
uv run --env-file .env python src/migration_guard.py
```

## 5. Seed 선택

로컬에서 사용할 수 있는 seed는 목적이 다른 두 종류입니다.

| 종류 | 용도 | 생성 범위 |
|---|---|---|
| `seed-sample-ledger` | F1 장부 화면과 일반 API 확인 | 지정한 개발 사무소의 예시 장부 |
| `seed-f3-synthetic` | API → Worker → AI의 F3 전체 흐름 확인 | 전용 합성 사무소, 사용자, AI 설정, 장부와 상담 로그 |

F3 합성 seed는 개발 계정 생성, sample 장부 seed와 AI 모델 설정 등록을 대신합니다. 실행 목적에
맞는 한 경로를 선택하면 됩니다.

### 5-A. 일반 sample 장부

먼저 로컬 전용 개발 계정을 만듭니다.

```bash
uv run python src/manage.py create-development-user \
  --brokerage-name "개발 중개사무소" \
  --login-id developer \
  --display-name "Developer" \
  --role OWNER
```

출력 JSON의 `id`가 `user_id`, `brokerage_id`가 사무소 ID입니다. 두 값을 사용해 예시 장부를
생성합니다.

```bash
uv run python src/manage.py seed-sample-ledger \
  --brokerage-id <brokerage_id> \
  --user-id <id>
```

같은 사무소에 장부 데이터가 이미 있으면 명령이 중단됩니다. 해당 사무소의 기존 장부를 모두
지우고 다시 만들 의도가 확실할 때만 `--reset`을 추가합니다. API와 Worker를 먼저 중지하고,
개인 로컬의 전용 개발 사무소에서만 사용합니다.

```bash
uv run python src/manage.py seed-sample-ledger \
  --brokerage-id <brokerage_id> \
  --user-id <id> \
  --reset
```

개발 세션을 발급할 수 있도록 `backend/.env`에 계정 정보를 넣습니다.

```dotenv
AUTH_DEVELOPMENT_ENABLED=true
AUTH_DEVELOPMENT_BROKERAGE_ID=<brokerage_id>
AUTH_DEVELOPMENT_LOGIN_ID=developer
```

`create-development-user`와 `seed-sample-ledger`는 `APP_ENV=local`에서만 실행됩니다.

### 5-B. F3 합성 seed

F3 파이프라인 전체를 확인하려면 migration 적용 후 `backend/`에서 관리 명령을 실행합니다.
`--confirm-reset`은 기존 `F3_SYNTHETIC 합성중개사무소`의 장부와 실행 결과를 지우고 다시
적재한다는 명시적 확인입니다. API와 Worker를 먼저 중지한 뒤 실행합니다.

```bash
uv run python src/manage.py seed-f3-synthetic --confirm-reset \
  --model-profile local-openai
```

명령은 `backend/.env`의 `DB_URL`을 사용하며 `APP_ENV=local`과 loopback DB 호스트에서만
동작합니다. 저장소의 고정된 reset → data → allowlisted model profile → verify 순서로 실행하고,
모두 30개 검사가 `PASS`여야 성공합니다. 성공 JSON의 `brokerage_id`를
`backend/.env`에 설정합니다. 자동 증가 ID는
환경마다 다르므로 문서의 예시 숫자를 고정해서 사용하지 않습니다.

```dotenv
AUTH_DEVELOPMENT_ENABLED=true
AUTH_DEVELOPMENT_BROKERAGE_ID=<brokerage_id 출력값>
AUTH_DEVELOPMENT_LOGIN_ID=f3_synthetic_dev
```

F3 seed의 reset 범위, 케이스와 공유 dev 적용법은
[F3 합성 seed 안내](../docs/db/seed/README.md)를 따릅니다. 이 seed는 실행 결과를 미리 만들지
않으며, `agent_run`과 판정 결과는 활성 Worker가 직접 생성해야 합니다.

`local-openai` F3 모델 설정은 OpenAI `gpt-5.6-luna`이므로 AI 개인 설정도 준비합니다.
`dev-bedrock-gpt56-luna`는 공유 dev POC용이며 Infra Bedrock doctor 통과 뒤 명시적으로
활성하고 합성 smoke로 검증합니다. 실패 시 OpenAI key·runtime이 배포된 환경에서만
`local-openai`를 명시 재적용합니다.
두 Qwen dev 프로필은 GPU runtime 배포 전까지 비활성 비교 경로로 보존합니다.

```bash
cp ../ai/.env.example ../ai/.env
```

```dotenv
AI_OPENAI_API_KEY=<private-api-key>
```

다른 Provider나 모델은 [F3 합성 seed 안내](../docs/db/seed/README.md)의 allowlist
프로필과 [`ai/.env.example`](../ai/.env.example)을 함께 확인합니다.

## 6. API와 Worker 실행

### 터미널 1: API

```bash
cd backend
uv run python src/server.py
```

- API: `http://127.0.0.1:8000`
- OpenAPI UI: `http://127.0.0.1:8000/docs`
- liveness: `http://127.0.0.1:8000/health/live`
- DB readiness: `http://127.0.0.1:8000/health/ready`

### 터미널 2: F3 Worker

검토된 F3 합성 seed만 처리하는 로컬 Worker는 두 설정을 명시해 실행합니다.

```bash
cd backend
WORKER_ENABLED=true \
F3_ALLOW_SYNTHETIC_PROTOTYPE=true \
uv run python src/worker.py
```

활성 Worker는 DB, 합성 데이터 opt-in과 AI Provider 설정을 검증한 뒤 DB polling을 시작합니다.
API에서 접수한 F3 실행이 없으면 대기합니다. 종료할 때는 `Ctrl+C`를 사용합니다.

`WORKER_ENABLED=false`인 기본 설정으로 `src/worker.py`를 실행하면 DB readiness만 확인하고 작업을
선점하지 않습니다. 따라서 API만 실행했거나 비활성 Worker만 실행한 상태에서는 F3 실행이
`QUEUED`에 머뭅니다.

`F3_ALLOW_SYNTHETIC_PROTOTYPE=true`는 검토된 합성 데이터 전용 opt-in입니다. 실사용 데이터를
처리해도 된다는 설정이 아닙니다.

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
- Worker 설정도 같은 병합 결과에서 검증되므로 개인 `.env`의 `WORKER_*` 값이 전역 환경변수 변경
  없이 적용됩니다. 활성 Worker의 합성 opt-in은 위 실행 명령처럼 프로세스 환경변수로 명시합니다.
- 활성 Worker의 Provider 설정은 `local`에서만 `ai/.env.local`, `ai/.env`, 프로세스 환경변수 순서로
  병합합니다. `dev`, `test`, `prod`에서는 AI 설정도 프로세스 환경변수만 사용합니다.
