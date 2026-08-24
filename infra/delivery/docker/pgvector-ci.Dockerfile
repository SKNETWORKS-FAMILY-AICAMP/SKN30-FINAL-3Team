FROM public.ecr.aws/docker/library/postgres:15.18-bookworm AS builder

ARG PGVECTOR_VERSION=0.8.6
ARG PGVECTOR_COMMIT=8ee86c96f0fd72390f890aa8a336fda6d3ab4c6c

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        build-essential \
        ca-certificates \
        git \
        postgresql-server-dev-15 \
    && git clone --branch "v${PGVECTOR_VERSION}" --depth 1 https://github.com/pgvector/pgvector.git /tmp/pgvector \
    && test "$(git -C /tmp/pgvector rev-parse HEAD)" = "${PGVECTOR_COMMIT}" \
    && make -C /tmp/pgvector OPTFLAGS="" \
    && make -C /tmp/pgvector install

FROM public.ecr.aws/docker/library/postgres:15.18-bookworm

COPY --from=builder /usr/lib/postgresql/15/lib/vector.so /usr/lib/postgresql/15/lib/vector.so
COPY --from=builder /usr/share/postgresql/15/extension/vector* /usr/share/postgresql/15/extension/
