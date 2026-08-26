#!/usr/bin/env bash
set -euo pipefail

readonly APP_ROOT=/opt/brokerage
readonly REVISION_DIR="${APP_ROOT}/revision"
readonly CONFIG_DIR="${APP_ROOT}/config"
readonly API_ENV_FILE="${CONFIG_DIR}/api.env"
readonly WORKER_ENV_FILE="${CONFIG_DIR}/worker.env"
readonly MIGRATION_ENV_FILE="${CONFIG_DIR}/migration.env"
readonly RDS_CA_FILE="${CONFIG_DIR}/global-bundle.pem"
readonly RDS_CA_CONTAINER_FILE="/etc/ssl/certs/aws-rds-global-bundle.pem"
readonly COMPOSE_FILE="${REVISION_DIR}/compose.dev.yml"
readonly BACKEND_IMAGE_FILE="${REVISION_DIR}/backend-image.env"

export AWS_REGION="${AWS_REGION:-ap-northeast-2}"
export CONFIG_DIR API_ENV_FILE WORKER_ENV_FILE MIGRATION_ENV_FILE
export RDS_CA_FILE RDS_CA_CONTAINER_FILE
export INSTANCE_ID="${INSTANCE_ID:-$(curl -fsS --connect-timeout 2 -X PUT http://169.254.169.254/latest/api/token -H 'X-aws-ec2-metadata-token-ttl-seconds: 300' | xargs -I{} curl -fsS --connect-timeout 2 -H 'X-aws-ec2-metadata-token: {}' http://169.254.169.254/latest/meta-data/instance-id)}"

if [[ -s "${BACKEND_IMAGE_FILE}" ]]; then
  # shellcheck disable=SC1091
  source "${BACKEND_IMAGE_FILE}"
  export AI_PROVIDER_SECRET_ID API_LOG_GROUP APP_PARAMETER_PREFIX APP_PORT
  export APP_READINESS_PATH AWS_REGION BACKEND_IMAGE
  export BACKEND_RUNTIME_DATABASE_SECRET_ID WORKER_LOG_GROUP
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

  local metadata_name
  for metadata_name in \
    AI_PROVIDER_SECRET_ID \
    API_LOG_GROUP \
    APP_PARAMETER_PREFIX \
    APP_PORT \
    APP_READINESS_PATH \
    AWS_REGION \
    BACKEND_RUNTIME_DATABASE_SECRET_ID \
    WORKER_LOG_GROUP; do
    if [[ -z "${!metadata_name:-}" ]]; then
      echo "Missing Backend deployment metadata: ${metadata_name}" >&2
      return 1
    fi
  done

  if [[ ! "${APP_PORT}" =~ ^[0-9]+$ ]] ||
    ((APP_PORT < 1 || APP_PORT > 65535)); then
    echo "APP_PORT must be an integer between 1 and 65535" >&2
    return 1
  fi
  if [[ "${APP_PARAMETER_PREFIX}" != /* ]]; then
    echo "APP_PARAMETER_PREFIX must be an absolute SSM path" >&2
    return 1
  fi
  if [[ "${APP_READINESS_PATH}" != /* ]]; then
    echo "APP_READINESS_PATH must be an absolute HTTP path" >&2
    return 1
  fi
}

compose() {
  docker compose --project-name brokerage-dev --file "${COMPOSE_FILE}" "$@"
}
