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


COMMENT ON TABLE ai_decision_feedback IS '포지션 분석 또는 매칭 판정에 대한 사용자 평가와 구조화된 정정을 기록한다.';
COMMENT ON COLUMN ai_decision_feedback.id IS 'AI 판단 피드백 레코드 고유 식별자.';
COMMENT ON COLUMN ai_decision_feedback.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN ai_decision_feedback.position_analysis_id IS '피드백 대상 포지션 분석 식별자.';
COMMENT ON COLUMN ai_decision_feedback.match_candidate_evaluation_id IS '피드백 대상 후보별 매칭 판정 식별자.';
COMMENT ON COLUMN ai_decision_feedback.feedback_type IS '평가, 정정 등 피드백 유형.';
COMMENT ON COLUMN ai_decision_feedback.reason IS '구조화된 피드백 사유 코드.';
COMMENT ON COLUMN ai_decision_feedback.field_name IS '필드 단위 정정 대상 필드명.';
COMMENT ON COLUMN ai_decision_feedback.original_value IS '정정 전 AI 판단 값.';
COMMENT ON COLUMN ai_decision_feedback.corrected_value IS '사용자가 확정한 정정 값.';
COMMENT ON COLUMN ai_decision_feedback.detail IS '피드백 상세 설명.';
COMMENT ON COLUMN ai_decision_feedback.correction_interaction_id IS '정정 내용을 추가 전용 상담 로그로 남긴 경우의 상담 식별자.';
COMMENT ON COLUMN ai_decision_feedback.created_by IS '피드백을 등록한 사용자 식별자.';
COMMENT ON COLUMN ai_decision_feedback.created_at IS '피드백 생성 시각.';

COMMENT ON TABLE ai_evaluation_result IS '상담 자동화와 중개 판단의 실험 케이스별 평가 점수와 통과 여부를 기록한다.';
COMMENT ON COLUMN ai_evaluation_result.id IS 'AI 평가 결과 레코드 고유 식별자.';
COMMENT ON COLUMN ai_evaluation_result.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN ai_evaluation_result.evaluation_domain IS '상담 자동화, 중개 판단 등 평가 도메인.';
COMMENT ON COLUMN ai_evaluation_result.evaluation_subject IS '평가 대상 기능 또는 단계.';
COMMENT ON COLUMN ai_evaluation_result.experiment_key IS '평가 실험을 식별하는 키.';
COMMENT ON COLUMN ai_evaluation_result.case_key IS '실험 안의 평가 케이스 식별 키.';
COMMENT ON COLUMN ai_evaluation_result.evaluation_variant IS '동일 케이스에서 비교한 모델·프롬프트·워크플로 변형.';
COMMENT ON COLUMN ai_evaluation_result.transcription_job_id IS '평가 대상 상담 전사 작업 식별자.';
COMMENT ON COLUMN ai_evaluation_result.agent_run_id IS '평가 대상 에이전트 실행 식별자.';
COMMENT ON COLUMN ai_evaluation_result.match_evaluation_id IS '평가 대상 매칭 판정 식별자.';
COMMENT ON COLUMN ai_evaluation_result.evaluator_type IS '사람, 규칙, 모델 등 평가자 유형.';
COMMENT ON COLUMN ai_evaluation_result.evaluator_key IS '구체 평가자 또는 평가 설정 식별 키.';
COMMENT ON COLUMN ai_evaluation_result.rubric_version IS '평가에 사용한 루브릭 버전.';
COMMENT ON COLUMN ai_evaluation_result.evaluation_input_hash IS '동일 평가 입력을 식별하는 SHA-256 해시.';
COMMENT ON COLUMN ai_evaluation_result.metric_scores IS '평가 지표별 점수.';
COMMENT ON COLUMN ai_evaluation_result.ground_truth_snapshot IS '평가 시점의 정답 또는 기준값 스냅샷.';
COMMENT ON COLUMN ai_evaluation_result.passed IS '평가 통과 여부.';
COMMENT ON COLUMN ai_evaluation_result.evaluation_notes IS '평가 결과에 대한 설명과 메모.';
COMMENT ON COLUMN ai_evaluation_result.created_by IS '평가 결과를 생성한 사용자 식별자.';
COMMENT ON COLUMN ai_evaluation_result.created_at IS '평가 결과 생성 시각.';
