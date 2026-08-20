#!/usr/bin/env bash
set -euo pipefail

# shellcheck source=common.sh
source /opt/brokerage/revision/scripts/common.sh
require_backend_image

docker_config_dir="$(mktemp -d /tmp/brokerage-docker-config.XXXXXX)"
cleanup() {
  rm -rf -- "${docker_config_dir}"
}
trap cleanup EXIT
export DOCKER_CONFIG="${docker_config_dir}"

aws ecr get-login-password --region "${AWS_REGION}" |
  docker login --username AWS --password-stdin "${BACKEND_IMAGE%%/*}"

curl -fsSLo "${CONFIG_DIR}/global-bundle.pem"   https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
chmod 0644 "${CONFIG_DIR}/global-bundle.pem"

python3 "${REVISION_DIR}/scripts/render_env.py"   --runtime-output "${RUNTIME_ENV_FILE}"   --migration-output "${MIGRATION_ENV_FILE}"

compose config --quiet
compose pull api worker migrate
compose --profile migration run --rm --no-deps migrate
python3 "${REVISION_DIR}/scripts/record_deployment.py" \
  --manifest "${REVISION_DIR}/release-manifest.json" \
  --output "${APP_ROOT}/deploy-record.json"
