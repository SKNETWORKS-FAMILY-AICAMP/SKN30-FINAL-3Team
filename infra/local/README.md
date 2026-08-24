# 로컬 개발 DB

backend를 실제 PostgreSQL에 붙여 보기 위한 컨테이너 구성이다. 운영 인프라는
`infra/environments`의 Terraform이 관리하며, 이 디렉터리는 개발자 노트북 전용이다.

## 실행

자격증명은 저장소에 두지 않는다. 예시 파일을 복사해 값을 채운 뒤 실행한다.

```bash
cp infra/local/.env.example infra/local/.env   # POSTGRES_USER/PASSWORD/DB 채우기
docker compose -f infra/local/compose.yaml up -d
```

`brokerage-local-postgres` 컨테이너가 `127.0.0.1:5432`에만 공개된다. 같은 네트워크의
다른 장치에서는 접속할 수 없다. 데이터는 `local_postgres-data` 볼륨에 남아 컨테이너를
지워도 유지된다. 완전히 비우려면 `docker compose -f infra/local/compose.yaml down -v`.

## migration 적용

접속 URL도 추적 파일에 적지 않는다. `.env`에 채운 값으로 셸에서 조립한다.

```bash
cd backend
set -a && . ../infra/local/.env && set +a
export PYTHONUTF8=1
export DB_URL="postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:5432/${POSTGRES_DB}"
export DB_MIGRATION_URL="$DB_URL"
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
uv run python src/server.py
```

출력된 `brokerage_id`, `login_id`와 `AUTH_DEVELOPMENT_ENABLED=true`를 Git에서 제외된
`backend/.env`의 `AUTH_DEVELOPMENT_*`에 넣으면 프론트의 "개발용 로그인" 버튼이 동작한다.
팀 공통 공개값이 있는 추적 파일 `backend/.env.local`은 개인 계정 때문에 수정하지 않는다.

## 프론트 연결

Git에서 제외된 `frontend/.env`에는 공통값 중 개인적으로 덮을 항목만 둔다. 실제 API를 사용할
때는 다음 한 줄이면 된다.

```dotenv
VITE_LEDGER_SOURCE=api
```

Backend port를 바꾼 경우에만 같은 파일에
`FRONTEND_BACKEND_ORIGIN=http://127.0.0.1:<port>`를 추가한다. `VITE_API_BASE_URL=/api/v1`과
mock 기본값은 추적된 `frontend/.env.local`에서 공유된다. 개인 `.env`의 override를 지우면
`VITE_LEDGER_SOURCE=mock`으로 돌아가 백엔드 없이 화면만 볼 수 있다.

## 알려진 공백

인물(`party`) 생성 API가 없다. 기존 인물이 연결되지 않은 신규 손님은 구입장에 저장할 수 없다.
