#!/usr/bin/env bash
set -euo pipefail

# shellcheck source=common.sh
source /opt/brokerage/revision/scripts/common.sh
require_backend_image

docker_config_dir="$(mktemp -d /tmp/brokerage-docker-config.XXXXXX)"
ca_download="$(mktemp "${CONFIG_DIR}/global-bundle.pem.XXXXXX")"
cleanup() {
  rm -rf -- "${docker_config_dir}"
  if [[ -n "${ca_download}" ]]; then
    rm -f -- "${ca_download}"
  fi
}
trap cleanup EXIT
export DOCKER_CONFIG="${docker_config_dir}"

aws ecr get-login-password --region "${AWS_REGION}" |
  docker login --username AWS --password-stdin "${BACKEND_IMAGE%%/*}"

curl -fsSLo "${ca_download}" \
  https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
grep -q -- "-----BEGIN CERTIFICATE-----" "${ca_download}"
chmod 0644 "${ca_download}"
mv -f -- "${ca_download}" "${RDS_CA_FILE}"
ca_download=""
test -s "${RDS_CA_FILE}"

python3 "${REVISION_DIR}/scripts/render_env.py" \
  --runtime-output "${RUNTIME_ENV_FILE}" \
  --migration-output "${MIGRATION_ENV_FILE}"

compose --profile migration config --quiet
compose pull api worker migrate
compose --profile migration run --rm --no-deps --entrypoint sh migrate \
  -c "test -r '${RDS_CA_CONTAINER_FILE}'"
compose --profile migration run --rm --no-deps migrate
python3 "${REVISION_DIR}/scripts/record_deployment.py" \
  --manifest "${REVISION_DIR}/release-manifest.json" \
  --output "${APP_ROOT}/deploy-record.json"
