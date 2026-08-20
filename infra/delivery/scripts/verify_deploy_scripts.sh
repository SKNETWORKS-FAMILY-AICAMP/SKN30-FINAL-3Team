#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

cd "${repo_root}"
bash -n \
  infra/deploy/scripts/common.sh \
  infra/deploy/scripts/application_stop.sh \
  infra/deploy/scripts/before_install.sh \
  infra/deploy/scripts/after_install.sh \
  infra/deploy/scripts/application_start.sh \
  infra/deploy/scripts/validate_service.sh
python3 -m unittest infra.tests.test_delivery_common -v
