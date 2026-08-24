FROM public.ecr.aws/docker/library/python:3.13-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.2 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /workspace

COPY ai/pyproject.toml ai/uv.lock ai/README.md /workspace/ai/
COPY ai/src /workspace/ai/src
COPY backend/pyproject.toml backend/uv.lock backend/README.md /workspace/backend/
COPY backend/src /workspace/backend/src
RUN cd /workspace/backend && uv sync --frozen --no-dev --no-editable

FROM public.ecr.aws/docker/library/python:3.13-slim-bookworm AS runtime

ENV PATH="/workspace/backend/.venv/bin:${PATH}" \
    PYTHONPATH="/workspace/backend/src" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /workspace/backend

RUN groupadd --system --gid 10001 brokerage \
    && useradd --system --uid 10001 --gid brokerage --home-dir /nonexistent brokerage \
    && apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder --chown=brokerage:brokerage /workspace/backend/.venv /workspace/backend/.venv
COPY --chown=brokerage:brokerage backend/src /workspace/backend/src
COPY --chown=brokerage:brokerage backend/yoyo.ini /workspace/backend/yoyo.ini
COPY --chown=brokerage:brokerage docs/db/migrate /workspace/docs/db/migrate

USER brokerage

CMD ["python", "src/server.py"]
