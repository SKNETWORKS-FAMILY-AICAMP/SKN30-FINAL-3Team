-- PostgreSQL 15+
-- 결정적 후보 집합과 양측 포지션 기반 교차 판정
-- depends: 005_CREATE_NEGOTIATION_POSITION


CREATE TABLE match_evaluation (
    id                          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id                BIGINT NOT NULL,
    agent_run_id                BIGINT NOT NULL,
    anchor_position_analysis_id BIGINT NOT NULL,
    candidate_count             INTEGER NOT NULL DEFAULT 0,
    data_version                BIGINT NOT NULL,
    candidate_selection_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    generated_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_match_evaluation_run
        FOREIGN KEY (brokerage_id, agent_run_id)
        REFERENCES agent_run (brokerage_id, id),
    CONSTRAINT fk_match_evaluation_anchor
        FOREIGN KEY (brokerage_id, anchor_position_analysis_id)
        REFERENCES negotiation_position_analysis (brokerage_id, id),
    CONSTRAINT uq_match_evaluation_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE INDEX idx_match_evaluation_anchor
    ON match_evaluation (
        brokerage_id,
        anchor_position_analysis_id,
        generated_at DESC
    );

CREATE TABLE match_candidate_evaluation (
    id                              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id                    BIGINT NOT NULL,
    match_evaluation_id             BIGINT NOT NULL,
    candidate_position_analysis_id  BIGINT NOT NULL,
    match_grade                     VARCHAR(20) NOT NULL,
    match_rank                      INTEGER NOT NULL,
    evaluation_basis                TEXT NOT NULL,
    primary_obstacle                TEXT,
    possible_concession             TEXT,
    recommended_action              JSONB NOT NULL DEFAULT '{}'::jsonb,
    exclusion_reason                TEXT,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_match_candidate_evaluation
        FOREIGN KEY (brokerage_id, match_evaluation_id)
        REFERENCES match_evaluation (brokerage_id, id),
    CONSTRAINT fk_match_candidate_position
        FOREIGN KEY (brokerage_id, candidate_position_analysis_id)
        REFERENCES negotiation_position_analysis (brokerage_id, id),
    CONSTRAINT uq_match_candidate_position
        UNIQUE (
            brokerage_id,
            match_evaluation_id,
            candidate_position_analysis_id
        ),
    CONSTRAINT uq_match_candidate_rank
        UNIQUE (brokerage_id, match_evaluation_id, match_rank),
    CONSTRAINT uq_match_candidate_tenant_id
        UNIQUE (brokerage_id, id),
    CONSTRAINT ck_match_candidate_positive_rank
        CHECK (match_rank > 0)
);

CREATE INDEX idx_match_candidate_grade
    ON match_candidate_evaluation (
        brokerage_id,
        match_evaluation_id,
        match_grade,
        match_rank
    );

CREATE TABLE match_candidate_evidence (
    id                              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id                    BIGINT NOT NULL,
    match_candidate_evaluation_id   BIGINT NOT NULL,
    evidence_side                   VARCHAR(20) NOT NULL,
    field_name                      VARCHAR(100),
    evidence_type                   VARCHAR(20) NOT NULL,
    interaction_id                  BIGINT,
    quote_text                      TEXT,
    quote_start_offset              INTEGER,
    quote_end_offset                INTEGER,
    note                            TEXT,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_match_candidate_evidence_candidate
        FOREIGN KEY (brokerage_id, match_candidate_evaluation_id)
        REFERENCES match_candidate_evaluation (brokerage_id, id),
    CONSTRAINT fk_match_candidate_evidence_interaction
        FOREIGN KEY (brokerage_id, interaction_id)
        REFERENCES client_interaction (brokerage_id, id),
    CONSTRAINT uq_match_candidate_evidence_tenant_id
        UNIQUE (brokerage_id, id),
    CONSTRAINT ck_match_candidate_evidence_source
        CHECK (
            interaction_id IS NOT NULL
            OR evidence_type = 'INFERENCE'
        )
);

CREATE INDEX idx_match_candidate_evidence_candidate
    ON match_candidate_evidence (
        brokerage_id,
        match_candidate_evaluation_id
    );
