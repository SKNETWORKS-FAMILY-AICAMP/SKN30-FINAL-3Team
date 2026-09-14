# Brokerage Backend

Python 3.13, uv, FastAPI 기반의 고성능 중개 지원 백엔드 애플리케이션입니다.
REST API 서버, 실시간 Server-Sent Events (SSE) 챗봇 스트리밍, 그리고 F3 멀티 에이전트 처리를 위한 비동기 Worker 프로세스로 구성됩니다.

---

## 프로세스 구조

API 서버와 비동기 Worker는 동일한 Backend 패키지와 DB를 공유하지만, 격리된 프로세스로 분리되어 동작합니다.

| 프로세스 | 진입점 | 역할 및 책임 |
|---|---|---|
| **API Server** | `src/server.py` | • REST API 엔드포인트 (원장, 상담로그, 마스터)<br/>• F2 음성 업로드 및 동기 STT/추출 런타임<br/>• 챗봇 SSE 실시간 스트리밍 및 대화 히스토리 관리<br/>• F3 실행 요청을 DB 큐(`agent_run`)에 적재 |
| **F3 Worker** | `src/worker.py` | • DB를 지속적으로 폴링하여 대기 중인 F3 작업 선점(Lease 획득)<br/>• LangGraph 기반 멀티 에이전트 파이프라인 구동<br/>• 포지션 카드 생성, 대리인 협상, 최종 중개 판정 결과 저장 |

> [!IMPORTANT]
> API 서버를 실행해도 Worker는 자동으로 시작되지 않습니다. F3 멀티 에이전트 판정 기능을 종단 간 실행하려면 API와 Worker 프로세스를 각각 실행해야 합니다.

---

## 주요 API 라우터 구조

- `src/api/property_ledger.py`: 매물 및 구입 원장 CRUD, 필터링, 정렬, 삭제 처리
- `src/api/f2.py`: 음성메모 업로드, Whisper STT 전사 및 LLM 구조화 추출, 사용자 승인/원장 반영
- `src/api/f3_runs.py`: F3 멀티 에이전트 실행 요청 생성, 상태 조회(QUEUED, RUNNING, COMPLETED, FAILED), 판정 결과 반환
- `src/api/chatbot.py`: 챗봇 대화방 생성 및 조회, Server-Sent Events (SSE) 스트리밍 질의응답
- `src/api/time_keeper.py`: 상담 로그 기록 및 고객별 타임라인 조회
- `src/api/authentication.py`: 세션 발급, 개발 세션 원클릭 로그인 및 권한 검증
- `src/api/health.py`: Liveness (`/health/live`) 및 Readiness (`/health/ready`) 헬스체크

---

## 1. 의존성 설치

[uv](https://docs.astral.sh/uv/)와 Python 3.13을 준비한 뒤 의존성을 설치합니다.

```bash
cd backend
uv sync --frozen
```

배포 환경에서는 editable dependency 없이 설치합니다.

```bash
uv sync --frozen --no-editable
```

---

## 2. 로컬 PostgreSQL 실행

Docker Compose를 이용해 PostgreSQL 15 컨테이너를 실행합니다.

```bash
cp infra/local/.env.example infra/local/.env
docker compose --env-file infra/local/.env -f infra/local/compose.yaml up -d
```

자세한 내용은 [로컬 개발 DB 안내](../infra/local/README.md)를 참고하세요.

---

## 3. 환경변수 설정

팀 공통 비민감 설정은 [`.env.local`](.env.local)에 정의되어 있습니다. 로컬 DB 접속 정보와 개발 환경 설정은 `.env`에 정의합니다.

```bash
cd backend
cp .env.example .env
```

`backend/.env`의 핵심 설정:

```dotenv
APP_ENV=local
DB_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/brokerage_dev
DB_MIGRATION_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/brokerage_dev

# 개발 세션 간편 로그인 설정
AUTH_DEVELOPMENT_ENABLED=true
AUTH_DEVELOPMENT_BROKERAGE_ID=1
AUTH_DEVELOPMENT_LOGIN_ID=f3_synthetic_dev

# F3 합성 데이터 허용 플래그
F3_ALLOW_SYNTHETIC_PROTOTYPE=true
```

---

## 4. DB 마이그레이션 적용

Yoyo 마이그레이션을 실행하여 스키마를 최신 상태로 갱신합니다.

```bash
uv run --env-file .env python src/migration_guard.py
```

---

## 5. 시드 데이터 적재

로컬 테스트 및 시연을 위해 **F3 합성 시드 데이터** 적재를 권장합니다.

```bash
uv run python src/manage.py seed-f3-synthetic --confirm-reset --model-profile local-openai
```

명령 실행 완료 시 출력되는 JSON의 `brokerage_id`를 `backend/.env`의 `AUTH_DEVELOPMENT_BROKERAGE_ID`에 입력합니다.

---

## 6. 서버 및 워커 실행

### 터미널 1: Backend API 서버

```bash
# Justfile 레시피 사용 시
just -f infra/justfile local-api

# 또는 직접 실행 시
uv run python src/server.py
```
- API 서버: `http://127.0.0.1:8000`
- OpenAPI 문서: `http://127.0.0.1:8000/docs`
- Liveness 체크: `http://127.0.0.1:8000/health/live`
- DB Readiness 체크: `http://127.0.0.1:8000/health/ready`

### 터미널 2: F3 비동기 Worker

```bash
# Justfile 레시피 사용 시
just -f infra/justfile local-worker

# 또는 직접 실행 시
uv run python src/worker.py
```

Worker는 DB 큐를 지속적으로 감시하며, F3 실행 요청이 들어오면 작업을 선점하여 AI 추론을 완료하고 결과를 저장합니다.

---

## 코드 품질 및 테스트

```bash
# 코드 포맷 및 린트 검사
uv run --locked --project backend ruff check --fix backend
uv run --locked --project backend ruff format backend

# 타입 검사
uv run --locked --project backend pyright

# 단위/통합 테스트 실행
uv run --locked --project backend pytest
```
