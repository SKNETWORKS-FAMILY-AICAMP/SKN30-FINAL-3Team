#!/usr/bin/env bash
set -euo pipefail

readonly APP_ROOT=/opt/brokerage
readonly REVISION_DIR="${APP_ROOT}/revision"
readonly CONFIG_DIR="${APP_ROOT}/config"
readonly RUNTIME_ENV_FILE="${CONFIG_DIR}/runtime.env"
readonly MIGRATION_ENV_FILE="${CONFIG_DIR}/migration.env"
readonly COMPOSE_FILE="${REVISION_DIR}/compose.dev.yml"
readonly BACKEND_IMAGE_FILE="${REVISION_DIR}/backend-image.env"

export AWS_REGION="${AWS_REGION:-ap-northeast-2}"
export CONFIG_DIR RUNTIME_ENV_FILE MIGRATION_ENV_FILE
export API_LOG_GROUP="${API_LOG_GROUP:-/skn30-final-3team-dev/application/api}"
export WORKER_LOG_GROUP="${WORKER_LOG_GROUP:-/skn30-final-3team-dev/application/worker}"
export INSTANCE_ID="${INSTANCE_ID:-$(curl -fsS --connect-timeout 2 -X PUT http://169.254.169.254/latest/api/token -H 'X-aws-ec2-metadata-token-ttl-seconds: 300' | xargs -I{} curl -fsS --connect-timeout 2 -H 'X-aws-ec2-metadata-token: {}' http://169.254.169.254/latest/meta-data/instance-id)}"

if [[ -s "${BACKEND_IMAGE_FILE}" ]]; then
  # shellcheck disable=SC1091
  source "${BACKEND_IMAGE_FILE}"
  export BACKEND_IMAGE
fi

require_backend_image() {
  if [[ ! -s "${BACKEND_IMAGE_FILE}" ]]; then
    echo "Missing Backend image release metadata: ${BACKEND_IMAGE_FILE}" >&2
    return 1
  fi
  if [[ "${BACKEND_IMAGE:-}" != *@sha256:* ]]; then
    echo "BACKEND_IMAGE must be pinned to an ECR digest" >&2
    return 1
  fi
}

compose() {
  docker compose --project-name brokerage-dev --file "${COMPOSE_FILE}" "$@"
}
