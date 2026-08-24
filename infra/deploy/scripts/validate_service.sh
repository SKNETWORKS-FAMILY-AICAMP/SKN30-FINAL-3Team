#!/usr/bin/env bash
set -euo pipefail

# shellcheck source=common.sh
source /opt/brokerage/revision/scripts/common.sh
require_backend_image

for attempt in $(seq 1 24); do
  api_status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' brokerage-dev-api-1 2>/dev/null || true)"
  worker_status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' brokerage-dev-worker-1 2>/dev/null || true)"
  if [[ "${api_status}" == "healthy" && "${worker_status}" == "healthy" ]] &&
    curl -fsS http://127.0.0.1:8000/health/ready >/dev/null; then
    exit 0
  fi
  sleep 5
done

compose ps
compose logs --tail 100 api worker
exit 1
