-- PostgreSQL 15+
-- 중개사무소, 사용자, 불변 AI 모델 설정
-- depends:


CREATE TABLE brokerage (
    id                              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name                            VARCHAR(120) NOT NULL,
    business_registration_number    VARCHAR(20),
    settings                        JSONB NOT NULL DEFAULT '{}'::jsonb,
    status                          VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    row_version                     BIGINT NOT NULL DEFAULT 1,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX uq_brokerage_business_registration_number
    ON brokerage (business_registration_number)
    WHERE business_registration_number IS NOT NULL;

CREATE TABLE app_user (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id        BIGINT NOT NULL,
    login_id            VARCHAR(100) NOT NULL,
    password_hash       TEXT NOT NULL,
    display_name        VARCHAR(80) NOT NULL,
    role                VARCHAR(20) NOT NULL,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    last_login_at       TIMESTAMPTZ,
    row_version         BIGINT NOT NULL DEFAULT 1,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_app_user_brokerage
        FOREIGN KEY (brokerage_id)
        REFERENCES brokerage (id),
    CONSTRAINT uq_app_user_login
        UNIQUE (brokerage_id, login_id),
    CONSTRAINT uq_app_user_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE INDEX idx_app_user_brokerage_active
    ON app_user (brokerage_id, is_active);

CREATE TABLE ai_model_config (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id        BIGINT NOT NULL,
    capability          VARCHAR(50) NOT NULL,
    config_key          VARCHAR(100) NOT NULL,
    config_version      INTEGER NOT NULL,
    provider            VARCHAR(80) NOT NULL,
    model_name          VARCHAR(160) NOT NULL,
    model_version       VARCHAR(120),
    endpoint_alias      VARCHAR(160),
    parameters          JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_by          BIGINT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_ai_model_config_brokerage
        FOREIGN KEY (brokerage_id)
        REFERENCES brokerage (id),
    CONSTRAINT fk_ai_model_config_created_by
        FOREIGN KEY (brokerage_id, created_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_ai_model_config_version
        UNIQUE (brokerage_id, capability, config_key, config_version),
    CONSTRAINT uq_ai_model_config_tenant_id
        UNIQUE (brokerage_id, id),
    CONSTRAINT ck_ai_model_config_positive_version
        CHECK (config_version > 0)
);

CREATE INDEX idx_ai_model_config_capability
    ON ai_model_config (brokerage_id, capability, is_active);
