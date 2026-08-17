-- PostgreSQL 15+
-- 음성 전사, 필드 제안, 사용자 승인 전 임시 상태
-- depends: 002_CREATE_PROPERTY_LEDGER


CREATE TABLE ledger_draft (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id        BIGINT NOT NULL,
    ledger_type         VARCHAR(20) NOT NULL,
    status              VARCHAR(20) NOT NULL DEFAULT 'DRAFT',
    source_type         VARCHAR(20) NOT NULL DEFAULT 'HUMAN',
    target_unit_id      BIGINT,
    target_listing_id   BIGINT,
    target_requirement_id BIGINT,
    final_unit_id       BIGINT,
    final_listing_id    BIGINT,
    final_requirement_id BIGINT,
    draft_payload       JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by          BIGINT NOT NULL,
    last_saved_by       BIGINT,
    expires_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    row_version         BIGINT NOT NULL DEFAULT 1,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_ledger_draft_brokerage
        FOREIGN KEY (brokerage_id)
        REFERENCES brokerage (id),
    CONSTRAINT fk_ledger_draft_target_unit
        FOREIGN KEY (brokerage_id, target_unit_id)
        REFERENCES property_unit (brokerage_id, id),
    CONSTRAINT fk_ledger_draft_target_listing
        FOREIGN KEY (brokerage_id, target_listing_id)
        REFERENCES property_listing (brokerage_id, id),
    CONSTRAINT fk_ledger_draft_target_requirement
        FOREIGN KEY (brokerage_id, target_requirement_id)
        REFERENCES property_requirement (brokerage_id, id),
    CONSTRAINT fk_ledger_draft_final_unit
        FOREIGN KEY (brokerage_id, final_unit_id)
        REFERENCES property_unit (brokerage_id, id),
    CONSTRAINT fk_ledger_draft_final_listing
        FOREIGN KEY (brokerage_id, final_listing_id)
        REFERENCES property_listing (brokerage_id, id),
    CONSTRAINT fk_ledger_draft_final_requirement
        FOREIGN KEY (brokerage_id, final_requirement_id)
        REFERENCES property_requirement (brokerage_id, id),
    CONSTRAINT fk_ledger_draft_created_by
        FOREIGN KEY (brokerage_id, created_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT fk_ledger_draft_last_saved_by
        FOREIGN KEY (brokerage_id, last_saved_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_ledger_draft_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE INDEX idx_ledger_draft_user_status
    ON ledger_draft (brokerage_id, created_by, status, updated_at DESC);

CREATE TABLE consultation_transcription_job (
    id                          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id                BIGINT NOT NULL,
    request_id                  UUID NOT NULL,
    ledger_draft_id             BIGINT NOT NULL,
    input_mode                  VARCHAR(20) NOT NULL DEFAULT 'FILE_UPLOAD',
    audio_object_key            TEXT,
    audio_content_type          VARCHAR(120),
    audio_size_bytes            BIGINT,
    audio_sha256                VARCHAR(64),
    status                      VARCHAR(30) NOT NULL DEFAULT 'DRAFT',
    transcription_model_config_id BIGINT,
    analysis_model_config_id    BIGINT,
    transcription_model_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    analysis_model_snapshot     JSONB NOT NULL DEFAULT '{}'::jsonb,
    prompt_version              VARCHAR(100),
    parser_version              VARCHAR(100),
    transcribed_text            TEXT,
    consultation_type           VARCHAR(30),
    ledger_match_result         VARCHAR(20) NOT NULL DEFAULT 'UNKNOWN',
    analysis_summary            JSONB NOT NULL DEFAULT '{}'::jsonb,
    retry_count                 INTEGER NOT NULL DEFAULT 0,
    failed_stage                VARCHAR(40),
    failure_code                VARCHAR(80),
    failure_message             TEXT,
    started_at                  TIMESTAMPTZ,
    transcribed_at              TIMESTAMPTZ,
    analyzed_at                 TIMESTAMPTZ,
    approved_by                 BIGINT,
    approved_at                 TIMESTAMPTZ,
    ledger_saved_at             TIMESTAMPTZ,
    retention_until             TIMESTAMPTZ,
    audio_purged_at             TIMESTAMPTZ,
    transcribed_text_purged_at  TIMESTAMPTZ,
    created_by                  BIGINT NOT NULL,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_transcription_job_draft
        FOREIGN KEY (brokerage_id, ledger_draft_id)
        REFERENCES ledger_draft (brokerage_id, id),
    CONSTRAINT fk_transcription_job_stt_model
        FOREIGN KEY (brokerage_id, transcription_model_config_id)
        REFERENCES ai_model_config (brokerage_id, id),
    CONSTRAINT fk_transcription_job_analysis_model
        FOREIGN KEY (brokerage_id, analysis_model_config_id)
        REFERENCES ai_model_config (brokerage_id, id),
    CONSTRAINT fk_transcription_job_approved_by
        FOREIGN KEY (brokerage_id, approved_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT fk_transcription_job_created_by
        FOREIGN KEY (brokerage_id, created_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_transcription_job_request
        UNIQUE (brokerage_id, request_id),
    CONSTRAINT uq_transcription_job_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE INDEX idx_transcription_job_status
    ON consultation_transcription_job (
        brokerage_id,
        status,
        created_at DESC
    );

CREATE INDEX idx_transcription_job_draft
    ON consultation_transcription_job (
        brokerage_id,
        ledger_draft_id,
        created_at DESC
    );

CREATE TABLE transcription_field_proposal (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id            BIGINT NOT NULL,
    transcription_job_id    BIGINT NOT NULL,
    target_entity           VARCHAR(30) NOT NULL,
    field_name              VARCHAR(120) NOT NULL,
    current_value           JSONB,
    proposed_value          JSONB,
    final_value             JSONB,
    proposal_status         VARCHAR(20) NOT NULL,
    confidence              NUMERIC(6,5),
    evidence_text           TEXT,
    evidence_start_offset   INTEGER,
    evidence_end_offset     INTEGER,
    is_selected             BOOLEAN NOT NULL DEFAULT FALSE,
    applied_by              BIGINT,
    applied_at              TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_field_proposal_job
        FOREIGN KEY (brokerage_id, transcription_job_id)
        REFERENCES consultation_transcription_job (brokerage_id, id),
    CONSTRAINT fk_field_proposal_applied_by
        FOREIGN KEY (brokerage_id, applied_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_field_proposal
        UNIQUE (
            brokerage_id,
            transcription_job_id,
            target_entity,
            field_name
        ),
    CONSTRAINT uq_field_proposal_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE INDEX idx_field_proposal_job
    ON transcription_field_proposal (
        brokerage_id,
        transcription_job_id,
        proposal_status
    );

CREATE TABLE interaction_log_proposal (
    id                          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id                BIGINT NOT NULL,
    transcription_job_id        BIGINT NOT NULL,
    draft_interaction_content   TEXT NOT NULL,
    final_interaction_content   TEXT,
    proposal_status             VARCHAR(20) NOT NULL DEFAULT 'NEEDS_REVIEW',
    is_selected                 BOOLEAN NOT NULL DEFAULT TRUE,
    final_client_interaction_id BIGINT,
    approved_by                 BIGINT,
    approved_at                 TIMESTAMPTZ,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_interaction_log_proposal_job
        FOREIGN KEY (brokerage_id, transcription_job_id)
        REFERENCES consultation_transcription_job (brokerage_id, id),
    CONSTRAINT fk_interaction_log_proposal_interaction
        FOREIGN KEY (brokerage_id, final_client_interaction_id)
        REFERENCES client_interaction (brokerage_id, id),
    CONSTRAINT fk_interaction_log_proposal_approved_by
        FOREIGN KEY (brokerage_id, approved_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_interaction_log_proposal_job
        UNIQUE (brokerage_id, transcription_job_id),
    CONSTRAINT uq_interaction_log_proposal_tenant_id
        UNIQUE (brokerage_id, id)
);
