#!/usr/bin/env bash
set -euo pipefail

# shellcheck source=common.sh
source /opt/brokerage/revision/scripts/common.sh
require_backend_image

services=(api)
case "${1:-}" in
  "") ;;
  --all) services+=(worker) ;;
  *) echo "Usage: refresh_ai_endpoints.sh [--all]" >&2; exit 2 ;;
esac

readonly RELEASE_MANIFEST="${REVISION_DIR}/release-manifest.json"
[[ -s "${RELEASE_MANIFEST}" ]]
readonly RELEASE_MANIFEST_SHA256="$(sha256sum "${RELEASE_MANIFEST}" | cut -d ' ' -f 1)"
readonly BACKEND_IMAGE_METADATA_SHA256="$(sha256sum "${BACKEND_IMAGE_FILE}" | cut -d ' ' -f 1)"
readonly BACKEND_IMAGE_ID="$(docker image inspect --format '{{.Id}}' "${BACKEND_IMAGE}")"

for service in "${services[@]}"; do
  container="brokerage-dev-${service}-1"
  [[ "$(docker inspect --format '{{.Config.Image}}' "${container}")" == "${BACKEND_IMAGE}" ]]
  [[ "$(docker inspect --format '{{.Image}}' "${container}")" == "${BACKEND_IMAGE_ID}" ]]
done

if [[ "${1:-}" == "--all" ]]; then
  python3 "${REVISION_DIR}/scripts/render_env.py" \
    --api-output "${API_ENV_FILE}" \
    --worker-output "${WORKER_ENV_FILE}" \
    --migration-output "${MIGRATION_ENV_FILE}"
else
  python3 "${REVISION_DIR}/scripts/render_env.py" --f2-only --api-output "${API_ENV_FILE}"
fi

compose config --quiet
compose up --detach --no-deps --force-recreate --pull never "${services[@]}"
"${REVISION_DIR}/scripts/validate_service.sh"

[[ "$(sha256sum "${RELEASE_MANIFEST}" | cut -d ' ' -f 1)" == "${RELEASE_MANIFEST_SHA256}" ]]
[[ "$(sha256sum "${BACKEND_IMAGE_FILE}" | cut -d ' ' -f 1)" == "${BACKEND_IMAGE_METADATA_SHA256}" ]]
for service in "${services[@]}"; do
  container="brokerage-dev-${service}-1"
  [[ "$(docker inspect --format '{{.Config.Image}}' "${container}")" == "${BACKEND_IMAGE}" ]]
  [[ "$(docker inspect --format '{{.Image}}' "${container}")" == "${BACKEND_IMAGE_ID}" ]]
done
