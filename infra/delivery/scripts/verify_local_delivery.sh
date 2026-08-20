#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
container_name="brokerage-delivery-local-${$}"
database_port="${LOCAL_TEST_DB_PORT:-55432}"
validation_dir="$(mktemp -d /tmp/brokerage-delivery-verify.XXXXXX)"
ci_database_image="brokerage-pgvector-ci:pg15.18-pgvector0.8.6"

cleanup() {
  docker stop "${container_name}" >/dev/null 2>&1 || true
  rm -rf "${validation_dir}"
}
trap cleanup EXIT

python3 --version | grep -Eq '^Python 3\.13\.'
uv --version | grep -Eq '^uv 0\.11\.2 '
node --version | grep -Eq '^v22\.'
docker version >/dev/null
docker compose version >/dev/null

cd "${repo_root}"
docker build \
  --file infra/delivery/docker/pgvector-ci.Dockerfile \
  --tag "${ci_database_image}" \
  .

docker run --detach --rm \
  --name "${container_name}" \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=brokerage \
  -p "${database_port}:5432" \
  "${ci_database_image}" >/dev/null

for attempt in $(seq 1 30); do
  if docker exec "${container_name}" pg_isready -U postgres >/dev/null; then
    break
  fi
  sleep 2
done
docker exec "${container_name}" pg_isready -U postgres >/dev/null

test_database_url="postgresql+psycopg://postgres:postgres@127.0.0.1:${database_port}/brokerage"
export DB_URL="${test_database_url}"
export DB_MIGRATION_URL="${test_database_url}"
export TEST_DB_URL="${test_database_url}"
export APP_PROFILE=test
export APP_ENV=test
export DB_TARGET=test
export HTTP_CORS_ALLOWED_ORIGINS='[]'
export HTTP_ALLOWED_HOSTS='["localhost","127.0.0.1"]'
export AUTH_DEVELOPMENT_ENABLED=false

"${repo_root}/infra/delivery/scripts/verify_backend_ai.sh"
"${repo_root}/infra/delivery/scripts/verify_frontend.sh"
"${repo_root}/infra/delivery/scripts/build_frontend_release.sh"

cd "${repo_root}"
docker build --file backend/Dockerfile --tag brokerage-backend:local .
docker run --rm --entrypoint sh brokerage-backend:local -c 'test "$(id -u)" = "10001"'

mkdir -p "${validation_dir}/config"
touch \
  "${validation_dir}/runtime.env" \
  "${validation_dir}/migration.env" \
  "${validation_dir}/config/global-bundle.pem"
export BACKEND_IMAGE=brokerage-backend:local
export RUNTIME_ENV_FILE="${validation_dir}/runtime.env"
export MIGRATION_ENV_FILE="${validation_dir}/migration.env"
export CONFIG_DIR="${validation_dir}/config"
export RDS_CA_FILE="${validation_dir}/config/global-bundle.pem"
export RDS_CA_CONTAINER_FILE=/etc/ssl/certs/aws-rds-global-bundle.pem
export AWS_REGION=ap-northeast-2
export API_LOG_GROUP=local-api
export WORKER_LOG_GROUP=local-worker
export INSTANCE_ID=local
docker compose --file infra/deploy/compose.dev.yml --profile migration config >/dev/null
