#!/usr/bin/env bash
set -euo pipefail

# shellcheck source=common.sh
source /opt/brokerage/revision/scripts/common.sh
require_backend_image
if [[ -f "${APP_ROOT}/serving-maintenance" ]]; then
  echo 'Reviewed maintenance deployment installed; dev-start releases API/Worker after model validation.'
  exit 0
fi
compose up --detach --remove-orphans api worker
