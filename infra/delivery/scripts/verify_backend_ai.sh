#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

: "${DB_URL:?DB_URL is required}"
: "${DB_MIGRATION_URL:?DB_MIGRATION_URL is required}"
: "${TEST_DB_URL:?TEST_DB_URL is required so integration tests cannot be skipped}"

cd "${repo_root}/ai"
uv sync --frozen
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest -q

cd "${repo_root}/backend"
uv sync --frozen
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run yoyo apply --batch
uv run yoyo apply --batch
uv run pytest -q
