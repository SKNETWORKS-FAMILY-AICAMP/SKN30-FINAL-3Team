#!/usr/bin/env bash
set -euo pipefail

# shellcheck source=common.sh
source /opt/brokerage/revision/scripts/common.sh
compose up --detach --remove-orphans api worker
