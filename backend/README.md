# Brokerage Backend

Python 3.13, FastAPI, SQLModel과 PostgreSQL 15 기반 백엔드다. 실제 로그인 화면은 아직 구현하지 않으며, 로컬에서는 개발자가 생성한 계정으로 서버 세션 인증을 사용한다.

## 구성

~~~text
backend/
├── src/
│   ├── main.py
│   ├── manage.py
│   ├── api/
│   ├── core/
│   │   └── config.py
│   └── domain/
│       ├── engine.py
│       ├── session.py
│       └── authentication/
├── tests/
├── .env.example
├── .env.local
├── .env.prod
├── .python-version
├── .pre-commit-config.yaml
├── pyproject.toml
├── uv.lock
└── yoyo.ini
~~~

src/는 애플리케이션 소스 루트다. 공개 HTTP DTO는 api/schemas/, DB와 인증 구현은 domain/에 둔다. 기능 패키지는 ledger, consultations, negotiations, matching, evaluations처럼 업무 용어를 사용한다.

## 설치

~~~bash
cd backend
uv sync --frozen
~~~

Python은 3.13으로 고정된다. 가상환경과 lock 파일은 backend/ 안에서만 관리한다.

## 환경 설정

src/core/config.py가 python-dotenv로 환경 파일을 읽고 환경변수를 그룹 DTO에 명시적으로 바인딩한다.

- 기본 profile은 local이며 .env.local을 읽는다.
- 운영은 실행 환경에 APP_PROFILE=prod를 먼저 주입하고 .env.prod를 읽는다.
- 테스트는 DTO를 직접 구성하며 dotenv를 읽지 않는다.
- 프로세스 환경변수가 dotenv 값보다 우선한다.
- .env.local과 .env.prod는 공개 설정만 담아 Git에서 관리한다.
- DB_URL, DB_MIGRATION_URL, 비밀번호와 토큰은 공개 환경 파일에 키 자체를 두지 않는다. 필요한 비밀 변수 이름은 .env.example이 정본이다.
- Backend는 비밀 저장소에 직접 접근하지 않는다. Infra가 로컬·CI·운영 프로세스 환경변수로 비밀값을 주입한다.
- 구체적인 비밀 저장소와 주입 도구가 확정되기 전에는 실행 셸 또는 승인된 실행 환경에서 필수 비밀 변수를 먼저 제공한다.

## 실행

~~~bash
uv run uvicorn main:app --app-dir src --reload
~~~

운영 profile 확인용 실행:

~~~bash
APP_PROFILE=prod uv run uvicorn main:app --app-dir src
~~~

DB_URL 또는 DB_MIGRATION_URL 같은 필수 비밀 환경변수가 누락되면 값 자체를 출력하지 않고 설정 검증 단계에서 실패한다.

## DB migration

실행 SQL은 ../docs/db/migrate/에 있다. 애플리케이션 시작 시 migration을 자동 실행하지 않는다.

~~~bash
uv run yoyo list
uv run yoyo apply --batch
~~~

프로세스 환경변수로 주입된 DB_URL은 애플리케이션 DML 계정, DB_MIGRATION_URL은 DDL 전용 계정을 사용한다. 공용 AWS 개발 DB에는 병합된 SQL만 지정 담당자가 직렬 적용한다.

새 SQL 파일 규칙은 [DB SQL 관리](../docs/db/README.md)를 따른다.

## 개발 계정과 인증

먼저 migration을 적용한 후 개발 계정을 만든다.

~~~bash
uv run python src/manage.py create-development-user \
  --brokerage-name "개발 중개사무소" \
  --login-id developer \
  --display-name "Developer" \
  --role OWNER
~~~

출력된 brokerage_id와 login_id를 .env.local에 반영한다.

~~~dotenv
AUTH_DEVELOPMENT_ENABLED=true
AUTH_DEVELOPMENT_BROKERAGE_ID=1
AUTH_DEVELOPMENT_LOGIN_ID=developer
~~~

서버를 재시작한 뒤 다음 API로 세션을 발급한다.

~~~text
POST /api/v1/auth/development-session
GET /api/v1/auth/me
DELETE /api/v1/auth/session
~~~

세션 발급 응답의 CSRF 토큰은 상태 변경 요청의 X-CSRF-Token 헤더로 전달한다. 세션 원문은 HttpOnly 쿠키에만 두고 DB에는 SHA-256 해시만 저장한다.

만료되거나 폐기된 세션 정리:

~~~bash
uv run python src/manage.py purge-expired-sessions
~~~

개발 인증과 개발 계정 명령은 운영 환경에서 거부된다.

## 상태 확인

- GET /health/live: 프로세스 상태
- GET /health/ready: PostgreSQL SELECT 1

모든 응답에는 X-Request-ID가 포함된다.

## 품질 검사

~~~bash
uv run ruff format --check src tests
uv run ruff check src tests
uv run pyright
uv run pytest
uv run pre-commit run --config .pre-commit-config.yaml --all-files
~~~

실제 PostgreSQL 통합 테스트는 별도 테스트 DB를 명시할 때만 실행한다.

~~~bash
TEST_DB_URL=postgresql+psycopg://... uv run pytest tests/integration
~~~

실사용자 이름, 연락처, 상담 원문, 세션, CSRF 토큰과 DB 자격 증명을 테스트 데이터나 로그에 넣지 않는다.
