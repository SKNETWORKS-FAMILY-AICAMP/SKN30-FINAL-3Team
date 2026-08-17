-- PostgreSQL 15+
-- 에이전트 실행 트리, 모델·프롬프트 버전, capability 호출 추적
-- depends: 003_CREATE_CONSULTATION_AUTOMATION


CREATE TABLE agent_run (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id            BIGINT NOT NULL,
    run_group_id            UUID NOT NULL,
    parent_run_id           BIGINT,
    run_type                VARCHAR(30) NOT NULL,
    agent_type              VARCHAR(30) NOT NULL,
    status                  VARCHAR(20) NOT NULL DEFAULT 'QUEUED',
    trigger_type            VARCHAR(50) NOT NULL,
    model_config_id         BIGINT,
    model_snapshot          JSONB NOT NULL DEFAULT '{}'::jsonb,
    prompt_version          VARCHAR(100),
    workflow_version        VARCHAR(100),
    experiment_key          VARCHAR(120),
    case_key                VARCHAR(120),
    evaluation_variant      VARCHAR(40),
    requested_by            BIGINT NOT NULL,
    target_unit_id          BIGINT,
    target_listing_id       BIGINT,
    target_requirement_id   BIGINT,
    input_data_version      BIGINT NOT NULL DEFAULT 1,
    last_interaction_at     TIMESTAMPTZ,
    redacted_input_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    redacted_output_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    input_tokens            INTEGER NOT NULL DEFAULT 0,
    output_tokens           INTEGER NOT NULL DEFAULT 0,
    latency_ms              INTEGER,
    failure_code            VARCHAR(80),
    failure_message         TEXT,
    started_at              TIMESTAMPTZ,
    completed_at            TIMESTAMPTZ,
    retention_until         TIMESTAMPTZ,
    purged_at               TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_agent_run_brokerage
        FOREIGN KEY (brokerage_id)
        REFERENCES brokerage (id),
    CONSTRAINT fk_agent_run_parent
        FOREIGN KEY (brokerage_id, parent_run_id)
        REFERENCES agent_run (brokerage_id, id),
    CONSTRAINT fk_agent_run_model
        FOREIGN KEY (brokerage_id, model_config_id)
        REFERENCES ai_model_config (brokerage_id, id),
    CONSTRAINT fk_agent_run_requested_by
        FOREIGN KEY (brokerage_id, requested_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT fk_agent_run_unit
        FOREIGN KEY (brokerage_id, target_unit_id)
        REFERENCES property_unit (brokerage_id, id),
    CONSTRAINT fk_agent_run_listing
        FOREIGN KEY (brokerage_id, target_listing_id)
        REFERENCES property_listing (brokerage_id, id),
    CONSTRAINT fk_agent_run_requirement
        FOREIGN KEY (brokerage_id, target_requirement_id)
        REFERENCES property_requirement (brokerage_id, id),
    CONSTRAINT uq_agent_run_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE INDEX idx_agent_run_group
    ON agent_run (brokerage_id, run_group_id, created_at);

CREATE INDEX idx_agent_run_experiment
    ON agent_run (
        brokerage_id,
        experiment_key,
        case_key,
        evaluation_variant
    )
    WHERE experiment_key IS NOT NULL;

CREATE INDEX idx_agent_run_target_unit
    ON agent_run (brokerage_id, target_unit_id, created_at DESC)
    WHERE target_unit_id IS NOT NULL;

CREATE INDEX idx_agent_run_target_requirement
    ON agent_run (
        brokerage_id,
        target_requirement_id,
        created_at DESC
    )
    WHERE target_requirement_id IS NOT NULL;

CREATE TABLE agent_capability_call (
    id                          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id                BIGINT NOT NULL,
    agent_run_id                BIGINT NOT NULL,
    sequence_no                 INTEGER NOT NULL,
    capability_name             VARCHAR(100) NOT NULL,
    status                      VARCHAR(20) NOT NULL DEFAULT 'RUNNING',
    redacted_request_payload    JSONB NOT NULL DEFAULT '{}'::jsonb,
    redacted_response_payload   JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at                TIMESTAMPTZ,
    latency_ms                  INTEGER,
    failure_code                VARCHAR(80),
    failure_message             TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_tool_call_run
        FOREIGN KEY (brokerage_id, agent_run_id)
        REFERENCES agent_run (brokerage_id, id),
    CONSTRAINT uq_tool_call_run_sequence
        UNIQUE (brokerage_id, agent_run_id, sequence_no),
    CONSTRAINT uq_tool_call_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE INDEX idx_tool_call_run
    ON agent_capability_call (brokerage_id, agent_run_id, sequence_no);
