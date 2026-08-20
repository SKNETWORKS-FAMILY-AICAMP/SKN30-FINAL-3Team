# 로컬 개발 DB

backend를 실제 PostgreSQL에 붙여 보기 위한 컨테이너 구성이다. 운영 인프라는
`infra/environments`의 Terraform이 관리하며, 이 디렉터리는 개발자 노트북 전용이다.

## 실행

```bash
docker compose -f infra/local/compose.yaml up -d
```

`brokerage-local-postgres` 컨테이너가 5432 포트로 뜨고, 데이터는 `local_postgres-data`
볼륨에 남는다. 컨테이너를 지워도 데이터는 유지된다. 완전히 비우려면
`docker compose -f infra/local/compose.yaml down -v`.

## migration 적용

```bash
cd backend
export PYTHONUTF8=1
export DB_URL="postgresql+psycopg://brokerage:localdev@127.0.0.1:5432/brokerage"
export DB_MIGRATION_URL="postgresql+psycopg://brokerage:localdev@127.0.0.1:5432/brokerage"
uv run yoyo apply --batch
```

두 가지를 주의한다.

- URL scheme은 `postgresql+psycopg`여야 한다. 그냥 `postgresql`을 쓰면 yoyo가
  psycopg2를 찾다가 `ModuleNotFoundError`로 죽는다. 이 프로젝트는 psycopg3를 쓴다.
- Windows에서는 `PYTHONUTF8=1`이 필요하다. 없으면 cp949로 SQL 파일을 읽다가
  한글 주석에서 `UnicodeDecodeError`가 난다.

## 개발 계정과 서버

```bash
uv run python src/manage.py create-development-user \
  --brokerage-name "개발 중개사무소" --login-id developer \
  --display-name "Developer" --role OWNER
uv run uvicorn main:app --app-dir src --port 8000
```

출력된 `brokerage_id`, `login_id`를 `backend/.env.local`의 `AUTH_DEVELOPMENT_*`에 넣고
`AUTH_DEVELOPMENT_ENABLED=true`로 두면 프론트의 "개발용 로그인" 버튼이 동작한다.

## 프론트 연결

`frontend/.env.local`(git 추적 안 함):

```dotenv
VITE_LEDGER_SOURCE=api
VITE_API_BASE_URL=/api/v1
VITE_BACKEND_ORIGIN=http://127.0.0.1:8000
```

`VITE_LEDGER_SOURCE=mock`으로 되돌리면 백엔드 없이 화면만 볼 수 있다.

## 알려진 공백

인물(`party`) 생성 API가 없다. 기존 인물이 연결되지 않은 신규 손님은 구입장에 저장할 수 없다.
