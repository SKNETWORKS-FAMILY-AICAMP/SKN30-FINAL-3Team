-- PostgreSQL 15+
-- 매물 대리·손님 대리 포지션 분석과 상담 원문 근거
-- depends: 004_CREATE_AGENT_EXECUTION


CREATE TABLE negotiation_position_analysis (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id            BIGINT NOT NULL,
    agent_run_id            BIGINT NOT NULL,
    negotiation_side        VARCHAR(20) NOT NULL,
    unit_id                 BIGINT,
    listing_id              BIGINT,
    requirement_id          BIGINT,
    target_label            VARCHAR(200),
    cache_key               VARCHAR(500) NOT NULL,
    source_interaction_count INTEGER NOT NULL DEFAULT 0,
    last_interaction_at     TIMESTAMPTZ,
    data_version            BIGINT NOT NULL,
    negotiation_intent      VARCHAR(20) NOT NULL DEFAULT 'UNKNOWN',
    stated_price_amount     BIGINT,
    estimated_price_amount  BIGINT,
    price_estimation_basis  TEXT,
    urgency                 VARCHAR(20) NOT NULL DEFAULT 'UNKNOWN',
    preferred_timing        JSONB NOT NULL DEFAULT '{}'::jsonb,
    flexible_conditions     JSONB NOT NULL DEFAULT '[]'::jsonb,
    inflexible_conditions   JSONB NOT NULL DEFAULT '[]'::jsonb,
    contactability_status   VARCHAR(20) NOT NULL DEFAULT 'CAUTION',
    contactability_note     TEXT,
    analysis_snapshot       JSONB NOT NULL DEFAULT '{}'::jsonb,
    generated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    invalidated_at          TIMESTAMPTZ,
    invalidation_reason     TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_position_analysis_run
        FOREIGN KEY (brokerage_id, agent_run_id)
        REFERENCES agent_run (brokerage_id, id),
    CONSTRAINT fk_position_analysis_unit
        FOREIGN KEY (brokerage_id, unit_id)
        REFERENCES property_unit (brokerage_id, id),
    CONSTRAINT fk_position_analysis_listing
        FOREIGN KEY (brokerage_id, listing_id)
        REFERENCES property_listing (brokerage_id, id),
    CONSTRAINT fk_position_analysis_requirement
        FOREIGN KEY (brokerage_id, requirement_id)
        REFERENCES property_requirement (brokerage_id, id),
    CONSTRAINT uq_position_analysis_tenant_id
        UNIQUE (brokerage_id, id),
    CONSTRAINT ck_position_analysis_has_target
        CHECK (num_nonnulls(unit_id, listing_id, requirement_id) >= 1)
);

CREATE UNIQUE INDEX uq_position_analysis_active_cache_key
    ON negotiation_position_analysis (brokerage_id, cache_key)
    WHERE invalidated_at IS NULL;

CREATE INDEX idx_position_analysis_listing
    ON negotiation_position_analysis (
        brokerage_id,
        listing_id,
        generated_at DESC
    )
    WHERE listing_id IS NOT NULL;

CREATE INDEX idx_position_analysis_requirement
    ON negotiation_position_analysis (
        brokerage_id,
        requirement_id,
        generated_at DESC
    )
    WHERE requirement_id IS NOT NULL;

CREATE TABLE negotiation_position_evidence (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id            BIGINT NOT NULL,
    position_analysis_id    BIGINT NOT NULL,
    field_name              VARCHAR(100) NOT NULL,
    evidence_type           VARCHAR(20) NOT NULL,
    interaction_id          BIGINT,
    quote_text              TEXT,
    quote_start_offset      INTEGER,
    quote_end_offset        INTEGER,
    note                    TEXT,
    display_order           INTEGER NOT NULL DEFAULT 0,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_position_evidence_analysis
        FOREIGN KEY (brokerage_id, position_analysis_id)
        REFERENCES negotiation_position_analysis (brokerage_id, id),
    CONSTRAINT fk_position_evidence_interaction
        FOREIGN KEY (brokerage_id, interaction_id)
        REFERENCES client_interaction (brokerage_id, id),
    CONSTRAINT uq_position_evidence_tenant_id
        UNIQUE (brokerage_id, id),
    CONSTRAINT ck_position_evidence_source
        CHECK (
            interaction_id IS NOT NULL
            OR evidence_type = 'INFERENCE'
        )
);

CREATE INDEX idx_position_evidence_analysis
    ON negotiation_position_evidence (
        brokerage_id,
        position_analysis_id,
        display_order
    );
