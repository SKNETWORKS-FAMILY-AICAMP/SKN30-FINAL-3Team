-- PostgreSQL 15+
-- 사용자 피드백·정정과 상담 자동화·중개 판단 실험 결과
-- depends: 006_CREATE_MATCH_EVALUATION


CREATE TABLE ai_decision_feedback (
    id                              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id                    BIGINT NOT NULL,
    position_analysis_id            BIGINT,
    match_candidate_evaluation_id   BIGINT,
    feedback_type                   VARCHAR(30) NOT NULL,
    reason                          VARCHAR(50) NOT NULL,
    field_name                      VARCHAR(100),
    original_value                  JSONB,
    corrected_value                 JSONB,
    detail                          TEXT,
    correction_interaction_id       BIGINT,
    created_by                      BIGINT NOT NULL,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_feedback_position
        FOREIGN KEY (brokerage_id, position_analysis_id)
        REFERENCES negotiation_position_analysis (brokerage_id, id),
    CONSTRAINT fk_feedback_match_candidate
        FOREIGN KEY (brokerage_id, match_candidate_evaluation_id)
        REFERENCES match_candidate_evaluation (brokerage_id, id),
    CONSTRAINT fk_feedback_correction_interaction
        FOREIGN KEY (brokerage_id, correction_interaction_id)
        REFERENCES client_interaction (brokerage_id, id),
    CONSTRAINT fk_feedback_created_by
        FOREIGN KEY (brokerage_id, created_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_feedback_tenant_id
        UNIQUE (brokerage_id, id),
    CONSTRAINT ck_feedback_has_target
        CHECK (
            num_nonnulls(
                position_analysis_id,
                match_candidate_evaluation_id
            ) >= 1
        )
);

CREATE INDEX idx_feedback_reason
    ON ai_decision_feedback (
        brokerage_id,
        feedback_type,
        reason,
        created_at DESC
    );

CREATE TABLE ai_evaluation_result (
    id                          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id                BIGINT NOT NULL,
    evaluation_domain           VARCHAR(30) NOT NULL,
    evaluation_subject          VARCHAR(40) NOT NULL,
    experiment_key              VARCHAR(120) NOT NULL,
    case_key                    VARCHAR(120) NOT NULL,
    evaluation_variant          VARCHAR(40) NOT NULL,
    transcription_job_id        BIGINT,
    agent_run_id                BIGINT,
    match_evaluation_id         BIGINT,
    evaluator_type              VARCHAR(20) NOT NULL,
    evaluator_key               VARCHAR(120),
    rubric_version              VARCHAR(100) NOT NULL,
    evaluation_input_hash       VARCHAR(64),
    metric_scores               JSONB NOT NULL DEFAULT '{}'::jsonb,
    ground_truth_snapshot       JSONB NOT NULL DEFAULT '{}'::jsonb,
    passed                      BOOLEAN,
    evaluation_notes            TEXT,
    created_by                  BIGINT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_evaluation_result_brokerage
        FOREIGN KEY (brokerage_id)
        REFERENCES brokerage (id),
    CONSTRAINT fk_evaluation_result_transcription
        FOREIGN KEY (brokerage_id, transcription_job_id)
        REFERENCES consultation_transcription_job (brokerage_id, id),
    CONSTRAINT fk_evaluation_result_agent_run
        FOREIGN KEY (brokerage_id, agent_run_id)
        REFERENCES agent_run (brokerage_id, id),
    CONSTRAINT fk_evaluation_result_match
        FOREIGN KEY (brokerage_id, match_evaluation_id)
        REFERENCES match_evaluation (brokerage_id, id),
    CONSTRAINT fk_evaluation_result_created_by
        FOREIGN KEY (brokerage_id, created_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_evaluation_result_tenant_id
        UNIQUE (brokerage_id, id),
    CONSTRAINT ck_evaluation_result_has_subject
        CHECK (
            num_nonnulls(
                transcription_job_id,
                agent_run_id,
                match_evaluation_id
            ) >= 1
        )
);

CREATE INDEX idx_evaluation_result_experiment
    ON ai_evaluation_result (
        brokerage_id,
        experiment_key,
        case_key,
        evaluation_variant
    );

CREATE INDEX idx_evaluation_result_subject
    ON ai_evaluation_result (
        brokerage_id,
        evaluation_domain,
        evaluation_subject,
        created_at DESC
    );
