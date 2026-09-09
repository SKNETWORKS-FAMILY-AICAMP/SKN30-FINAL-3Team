# Brokerage Backend

Python 3.13, uv, FastAPI를 사용하는 Backend 애플리케이션입니다.

## 로컬 프로세스 구성

API와 Worker는 같은 Backend 패키지와 DB를 사용하지만 서로 다른 프로세스로 실행합니다.

| 프로세스 | 진입점 | 역할 |
|---|---|---|
| API | `src/server.py` | HTTP API와 F2 runtime 제공, F3 실행 요청을 DB에 적재 |
| Worker | `src/worker.py` | 별도 소비 스레드로 변경 이벤트 처리, DB 실행 선점과 F3 파이프라인 수행 |

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
| `seed-f3-synthetic` | 저장 결과 화면·API 확인 (`--ledger-only`는 모델 검증 준비) | 전용 합성 사무소, 사용자, AI 설정, 장부·상담 로그·예시 매칭 결과 |

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

F3 장부와 예시 매칭 결과를 준비하려면 migration 적용 후 `backend/`에서 관리 명령을 실행합니다.
`--confirm-reset`은 기존 `F3_SYNTHETIC 합성중개사무소`의 장부와 실행 결과를 지우고 다시
적재한다는 명시적 확인입니다. API와 Worker를 먼저 중지한 뒤 실행합니다.

```bash
uv run python src/manage.py seed-f3-synthetic --confirm-reset \
  --model-profile local-openai
```

명령은 `backend/.env`의 `DB_URL`을 사용하며 `APP_ENV=local`과 loopback DB 호스트에서만
동작합니다. 저장소의 고정된 reset → data → allowlisted model profile → verify 순서로 실행하고,
장부 30개 검사 후 예시 결과를 생성하고 결과 12개 검사도 `PASS`여야 성공합니다. 성공 JSON의 `brokerage_id`를
`backend/.env`에 설정합니다. 자동 증가 ID는
환경마다 다르므로 문서의 예시 숫자를 고정해서 사용하지 않습니다.

```dotenv
AUTH_DEVELOPMENT_ENABLED=true
AUTH_DEVELOPMENT_BROKERAGE_ID=<brokerage_id 출력값>
AUTH_DEVELOPMENT_LOGIN_ID=f3_synthetic_dev
```

F3 seed의 reset 범위, 케이스와 공유 dev 적용법은
[F3 합성 seed 안내](../docs/db/seed/README.md)를 따릅니다. 기본 실행은 84개 대상 중 적격 81개에
실제 모델 호출 없는 예시 결과를 저장하고 화면에 출처를 표시합니다. 실제 모델·Worker를
검증하려면 같은 명령에 `--ledger-only`를 추가해 결과 없는 장부를 준비합니다.

범용 Provider·모델·키는 `ai/.env`에서 선택합니다. 기본은 OpenAI `gpt-5.6-luna`이며
`AI_GENERAL_API_KEY`에 개인 키를 입력합니다. Backend 개인 파일에는 AI 변수를 쓰지 않습니다.
지원 enum, capability별 명시 모델 반영, F2 연결은
[환경변수 관리](../docs/development/environment-variables.md)를 따릅니다.

## 6. API와 Worker 실행

### 터미널 1: API

```bash
just -f infra/justfile local-api
```

- API: `http://127.0.0.1:8000`
- OpenAPI UI: `http://127.0.0.1:8000/docs`
- liveness: `http://127.0.0.1:8000/health/live`
- DB readiness: `http://127.0.0.1:8000/health/ready`

### 터미널 2: F3 Worker

`backend/.env`에 `F3_ALLOW_SYNTHETIC_PROTOTYPE=true`를 지정한 뒤 저장소 루트에서 실행합니다.
이는 검토된 합성 데이터 전용 허용이며 실사용 데이터 허용이 아닙니다.

```bash
just -f infra/justfile local-worker
```

Worker 실행 자체가 작업 처리를 시작합니다. 필요 없으면 실행하지 않고 종료는 Ctrl+C로 합니다.
로컬 launcher가 모듈별 환경을 검증하고 주입하며 Worker는 합성 opt-in·DB·Provider를 검증합니다.
Worker가 없으면 F3 요청은 QUEUED에 머뭅니다. 별도 비활성 Worker는 없습니다.

조건부 자동 판정은 migration021 적용 후 같은 개인 `backend/.env`에서 별도로 켭니다.

```dotenv
F3_AUTO_JUDGMENT_ENABLED=true
F3_AUTO_DEBOUNCE_SECONDS=3
F3_AUTO_BATCH_SIZE=20
```

자동 판정 기본값은 false입니다. 꺼져 있어도 명시적 실행 요청과 저장 결과 조회는 제공하며,
원장 변경 이벤트는 DB에 보존됩니다. 켜면 기존 대상도 제한된 배치로 검증합니다. 저장은
AI 완료를 기다리지 않고 원장과 outbox를 한 transaction에 기록합니다. outbox 기록 실패는
원장 저장 실패로 반환합니다. 결과 목록 GET은 모델이나 작업을 생성하지 않습니다.

Worker 내부의 이벤트 소비는 모델 대기와 독립적입니다. 30초 heartbeat로 300초 lease를
갱신하고 DB 전역 F3 슬롯 1개를 사용합니다. 후보 카드는 최대 5개 병렬이며, 현재 단일 API의
챗봇 1건과 합한 general 요청 상한은 6건입니다. API 다중 프로세스 확장에는 챗봇의 공유
admission 제어가 필요합니다. 자세한 구현·서버 분리 경계는
[F3 실행 참조](../.agents/skills/backend/references/f3-execution.md)를 따릅니다.

### 테스트 모델로 브라우저 통합 검증

일회용 로컬 DB 이름을 `*_validation`으로 지정하고 합성 seed·migration021·API를 준비한 뒤
저장소 루트에서 실행합니다. `backend/.env`의 DB와 API의 DB는 같아야 하며 개발 세션도 같은
합성 사무소를 가리켜야 합니다.

```bash
uv run --locked --project backend python backend/scripts/f3_browser_validation.py \
  --confirm-synthetic-validation --api-base-url http://127.0.0.1:8103
```

이 도구는 테스트 generator임이 표시된 모델 profile을 검증 DB에 기록하고 합성 매물 가격을
1원 바꿔 저장→이벤트→Worker→결과 조회를 두 방향으로 확인합니다. 실제 모델에 자동으로
대체 적용되는 기능이 아니며 모델 품질·GPU 부하를 검증하지 않습니다. 일반 개발 DB나 공유
환경에서는 실행할 수 없습니다.


## 설정 환경

파일 역할·변수 추가 및 정리 기준은 [환경변수 관리](../docs/development/environment-variables.md)를 따릅니다.
F2 로컬 기본값은 offline입니다. 연결 준비 후 `ai/.env.example`의 SLLM/STT URL 쌍을 함께 설정합니다.

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
- 로컬 API/Worker는 Infra launcher가 `backend/.env*`와 `ai/.env*`를 각각 주입합니다.
  dev/test/prod는 주입된 process env만 사용합니다.
