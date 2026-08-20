#!/usr/bin/env bash
set -euo pipefail

if [[ ! -f /opt/brokerage/revision/scripts/common.sh ]]; then
  exit 0
fi

# shellcheck source=common.sh
source /opt/brokerage/revision/scripts/common.sh
compose down --timeout 30 --remove-orphans || true
