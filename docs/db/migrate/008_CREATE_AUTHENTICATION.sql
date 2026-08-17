-- PostgreSQL 15+
-- 사용자 서버 세션, CSRF 검증값, 만료와 폐기 상태
-- depends: 007_CREATE_AI_EVALUATION

CREATE TABLE user_session (
    id                          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id                BIGINT NOT NULL,
    user_id                     BIGINT NOT NULL,
    session_token_hash          CHAR(64) NOT NULL,
    csrf_token_hash             CHAR(64) NOT NULL,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    idle_expires_at             TIMESTAMPTZ NOT NULL,
    absolute_expires_at         TIMESTAMPTZ NOT NULL,
    revoked_at                  TIMESTAMPTZ,
    revoked_reason              VARCHAR(80),
    CONSTRAINT fk_user_session_user
        FOREIGN KEY (brokerage_id, user_id)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_user_session_tenant_id
        UNIQUE (brokerage_id, id),
    CONSTRAINT ck_user_session_token_hash
        CHECK (session_token_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_user_session_csrf_hash
        CHECK (csrf_token_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_user_session_expiry_order
        CHECK (
            created_at <= idle_expires_at
            AND idle_expires_at <= absolute_expires_at
        )
);

CREATE UNIQUE INDEX uq_user_session_token_hash
    ON user_session (session_token_hash);

CREATE INDEX idx_user_session_user_active
    ON user_session (brokerage_id, user_id, last_seen_at DESC)
    WHERE revoked_at IS NULL;

CREATE INDEX idx_user_session_expiry
    ON user_session (idle_expires_at, absolute_expires_at)
    WHERE revoked_at IS NULL;
