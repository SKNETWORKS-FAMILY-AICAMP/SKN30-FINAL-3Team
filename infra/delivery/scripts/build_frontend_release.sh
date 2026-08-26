#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

: "${VITE_API_BASE_URL:?VITE_API_BASE_URL must be injected for a Frontend release}"
if [[ "${VITE_LEDGER_SOURCE:-}" != "api" ]]; then
  echo "VITE_LEDGER_SOURCE=api must be injected for a Frontend release" >&2
  exit 1
fi

cd "${repo_root}/frontend"
npm ci
npm run build
npm run test:release
