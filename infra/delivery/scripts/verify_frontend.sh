#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

cd "${repo_root}/frontend"
npm ci
npm run typecheck
npm run test:ledger
npm run build
npm run test:release
