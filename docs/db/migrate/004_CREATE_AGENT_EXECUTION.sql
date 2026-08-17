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


COMMENT ON TABLE agent_run IS '에이전트 실행 트리와 대상, 모델·프롬프트 버전, 비식별 입출력 및 실행 결과를 추적한다.';
COMMENT ON COLUMN agent_run.id IS '에이전트 실행 레코드 고유 식별자.';
COMMENT ON COLUMN agent_run.brokerage_id IS '실행을 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN agent_run.run_group_id IS '하나의 사용자 요청에서 파생된 실행 묶음 식별자.';
COMMENT ON COLUMN agent_run.parent_run_id IS '상위 에이전트 실행 식별자.';
COMMENT ON COLUMN agent_run.run_type IS '상담 분석, 포지션 분석, 매칭 등 실행 유형.';
COMMENT ON COLUMN agent_run.agent_type IS '실행을 담당한 에이전트 유형.';
COMMENT ON COLUMN agent_run.status IS '에이전트 실행 상태.';
COMMENT ON COLUMN agent_run.trigger_type IS '사용자 요청, 이벤트 등 실행 시작 원인.';
COMMENT ON COLUMN agent_run.model_config_id IS '실행에 사용한 불변 AI 모델 설정 식별자.';
COMMENT ON COLUMN agent_run.model_snapshot IS '실행 시점의 모델 설정 스냅샷.';
COMMENT ON COLUMN agent_run.prompt_version IS '실행에 사용한 프롬프트 버전.';
COMMENT ON COLUMN agent_run.workflow_version IS '실행에 사용한 워크플로 버전.';
COMMENT ON COLUMN agent_run.experiment_key IS '평가 실험 식별 키.';
COMMENT ON COLUMN agent_run.case_key IS '평가 실험 안의 케이스 식별 키.';
COMMENT ON COLUMN agent_run.evaluation_variant IS '실험에서 비교한 실행 변형.';
COMMENT ON COLUMN agent_run.requested_by IS '실행을 요청한 사용자 식별자.';
COMMENT ON COLUMN agent_run.target_unit_id IS '실행 대상 세대 식별자.';
COMMENT ON COLUMN agent_run.target_listing_id IS '실행 대상 매물 식별자.';
COMMENT ON COLUMN agent_run.target_requirement_id IS '실행 대상 구입장 수요 식별자.';
COMMENT ON COLUMN agent_run.input_data_version IS '분석 입력 데이터의 논리 버전.';
COMMENT ON COLUMN agent_run.last_interaction_at IS '분석 입력에 포함된 마지막 상담 시각.';
COMMENT ON COLUMN agent_run.redacted_input_snapshot IS '개인정보를 제거하거나 마스킹한 실행 입력 스냅샷.';
COMMENT ON COLUMN agent_run.redacted_output_snapshot IS '개인정보를 제거하거나 마스킹한 실행 출력 스냅샷.';
COMMENT ON COLUMN agent_run.input_tokens IS '모델 호출에 사용한 입력 토큰 수.';
COMMENT ON COLUMN agent_run.output_tokens IS '모델 호출에서 생성된 출력 토큰 수.';
COMMENT ON COLUMN agent_run.latency_ms IS '에이전트 실행 지연 시간(밀리초).';
COMMENT ON COLUMN agent_run.failure_code IS '실패 유형을 나타내는 안정적인 오류 코드.';
COMMENT ON COLUMN agent_run.failure_message IS '개인정보를 포함하지 않는 실패 설명.';
COMMENT ON COLUMN agent_run.started_at IS '실행을 시작한 시각.';
COMMENT ON COLUMN agent_run.completed_at IS '실행을 완료한 시각.';
COMMENT ON COLUMN agent_run.retention_until IS '실행 스냅샷 보존 기한.';
COMMENT ON COLUMN agent_run.purged_at IS '보존 대상 실행 스냅샷을 파기한 시각.';
COMMENT ON COLUMN agent_run.created_at IS '실행 레코드 생성 시각.';
COMMENT ON COLUMN agent_run.updated_at IS '실행 레코드 최종 수정 시각.';

COMMENT ON TABLE agent_capability_call IS '에이전트 실행 중 capability 호출 순서와 비식별 요청·응답 및 실행 결과를 기록한다.';
COMMENT ON COLUMN agent_capability_call.id IS 'capability 호출 레코드 고유 식별자.';
COMMENT ON COLUMN agent_capability_call.brokerage_id IS '호출을 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN agent_capability_call.agent_run_id IS '호출이 속한 에이전트 실행 식별자.';
COMMENT ON COLUMN agent_capability_call.sequence_no IS '동일 실행 안에서의 capability 호출 순번.';
COMMENT ON COLUMN agent_capability_call.capability_name IS '호출한 capability 이름.';
COMMENT ON COLUMN agent_capability_call.status IS 'capability 호출 실행 상태.';
COMMENT ON COLUMN agent_capability_call.redacted_request_payload IS '개인정보를 제거하거나 마스킹한 호출 요청.';
COMMENT ON COLUMN agent_capability_call.redacted_response_payload IS '개인정보를 제거하거나 마스킹한 호출 응답.';
COMMENT ON COLUMN agent_capability_call.started_at IS 'capability 호출 시작 시각.';
COMMENT ON COLUMN agent_capability_call.completed_at IS 'capability 호출 완료 시각.';
COMMENT ON COLUMN agent_capability_call.latency_ms IS 'capability 호출 지연 시간(밀리초).';
COMMENT ON COLUMN agent_capability_call.failure_code IS '호출 실패 유형을 나타내는 오류 코드.';
COMMENT ON COLUMN agent_capability_call.failure_message IS '개인정보를 포함하지 않는 호출 실패 설명.';
COMMENT ON COLUMN agent_capability_call.created_at IS 'capability 호출 레코드 생성 시각.';
