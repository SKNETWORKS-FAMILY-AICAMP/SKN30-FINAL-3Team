#!/usr/bin/env bash
set -euo pipefail
source /opt/brokerage/revision/scripts/common.sh
require_backend_image
# The disposable worker uses installed public AI workflows and writes no DB data.
model="${1:-unsloth/Qwen3.8-27B-unsloth-bnb-4bit}"
if compose run --rm --no-deps -T worker python src/manage.py smoke-general --model "$model" >/dev/null 2>&1; then
  echo 'general synthetic workflows: OK'
else
  echo 'general synthetic workflow validation failed' >&2
  exit 1
fi
