#!/usr/bin/env bash
set -euo pipefail

# shellcheck source=common.sh
source /opt/brokerage/revision/scripts/common.sh
require_backend_image

readonly RELEASE_MANIFEST="${REVISION_DIR}/release-manifest.json"
[[ -s "${RELEASE_MANIFEST}" ]]
readonly RELEASE_MANIFEST_SHA256="$(sha256sum "${RELEASE_MANIFEST}" | cut -d ' ' -f 1)"
readonly BACKEND_IMAGE_METADATA_SHA256="$(sha256sum "${BACKEND_IMAGE_FILE}" | cut -d ' ' -f 1)"
readonly BACKEND_IMAGE_ID="$(docker image inspect --format '{{.Id}}' "${BACKEND_IMAGE}")"

for service in api worker; do
  container="brokerage-dev-${service}-1"
  [[ "$(docker inspect --format '{{.Config.Image}}' "${container}")" == "${BACKEND_IMAGE}" ]]
  [[ "$(docker inspect --format '{{.Image}}' "${container}")" == "${BACKEND_IMAGE_ID}" ]]
done

python3 "${REVISION_DIR}/scripts/render_env.py" \
  --api-output "${API_ENV_FILE}" \
  --worker-output "${WORKER_ENV_FILE}" \
  --migration-output "${MIGRATION_ENV_FILE}"

compose --profile migration config --quiet
compose up --detach --no-deps --force-recreate --pull never api worker
"${REVISION_DIR}/scripts/validate_service.sh"

[[ "$(sha256sum "${RELEASE_MANIFEST}" | cut -d ' ' -f 1)" == "${RELEASE_MANIFEST_SHA256}" ]]
[[ "$(sha256sum "${BACKEND_IMAGE_FILE}" | cut -d ' ' -f 1)" == "${BACKEND_IMAGE_METADATA_SHA256}" ]]
for service in api worker; do
  container="brokerage-dev-${service}-1"
  [[ "$(docker inspect --format '{{.Config.Image}}' "${container}")" == "${BACKEND_IMAGE}" ]]
  [[ "$(docker inspect --format '{{.Image}}' "${container}")" == "${BACKEND_IMAGE_ID}" ]]
done
