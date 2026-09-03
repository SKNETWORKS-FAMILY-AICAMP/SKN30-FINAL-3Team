#!/usr/bin/env bash
set -euo pipefail

# shellcheck source=common.sh
source /opt/brokerage/revision/scripts/common.sh
require_backend_image

for service in api worker; do
  container="brokerage-dev-${service}-1"
  [[ "$(docker inspect --format '{{.State.Running}}' "${container}")" == "true" ]]
  [[ "$(docker inspect --format '{{.State.Health.Status}}' "${container}")" == "healthy" ]]
done
