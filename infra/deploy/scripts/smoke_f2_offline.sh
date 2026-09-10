#!/usr/bin/env bash
set -euo pipefail

# shellcheck source=common.sh
source /opt/brokerage/revision/scripts/common.sh
require_backend_image

python3 "${REVISION_DIR}/scripts/smoke_f2.py" \
  --base-url "http://127.0.0.1:${APP_PORT}" \
  --audio "${REVISION_DIR}/scripts/smoke_f2_audio.mp3.b64" \
  --expected-provider-status offline
