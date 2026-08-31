#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

cd "${repo_root}/frontend"
npm ci
npm run test:env
npm run test:auth
npm run test:root-error
npm run typecheck
npm run test:ledger
npm run test:f2
npm run test:f3
