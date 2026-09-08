#!/usr/bin/env bash
set -euo pipefail
source /opt/brokerage/revision/scripts/common.sh
require_backend_image
case "${1:-}" in
  stop)
    # SIGTERM blocks new API connections / worker claims. Do not force-kill in-flight work.
    for service in api worker; do
      id="$(compose ps --all --quiet "${service}")"
      if [[ -n "${id}" && "$(docker inspect -f '{{.State.Running}}' "${id}")" == true ]]; then
        docker update --restart=no "${id}" >/dev/null
        docker kill --signal TERM "${id}" >/dev/null
      fi
    done
    deadline=$((SECONDS + 300))
    while ((SECONDS < deadline)); do
      running="$(compose ps --status running --quiet api worker)"
      [[ -n "${running}" ]] || exit 0
      sleep 2
    done
    echo 'Workload drain timed out; GPU resources and routing must remain unchanged.' >&2
    exit 1
    ;;
  activate-general)
    [[ "${2:-}" =~ ^[1-9][0-9]*$ ]]
    [[ -z "$(compose ps --status running --quiet api worker)" ]]
    compose run --rm --no-deps -T worker python src/manage.py activate-general-qwen \
      --brokerage-id "$2" --model "${3:-unsloth/Qwen3.8-27B-unsloth-bnb-4bit}" --shared-dev --apply --workloads-stopped-confirmed
    ;;
  start)
    python3 "${REVISION_DIR}/scripts/render_env.py" --api-output "${API_ENV_FILE}" --worker-output "${WORKER_ENV_FILE}" --migration-output "${MIGRATION_ENV_FILE}"
    compose up --detach --no-deps --force-recreate --pull never api worker
    "${REVISION_DIR}/scripts/validate_service.sh"
    ;;
  *) echo 'Usage: serving_maintenance.sh stop|start' >&2; exit 2 ;;
esac
