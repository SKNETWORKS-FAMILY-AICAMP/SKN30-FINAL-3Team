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


COMMENT ON TABLE match_evaluation IS '앵커 포지션 1건과 후보 포지션 N건을 한 번의 중개 판정 호출로 평가한 결과 헤더.';
COMMENT ON COLUMN match_evaluation.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN match_evaluation.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN match_evaluation.agent_run_id IS '중개 판정을 수행한 에이전트 실행 식별자.';
COMMENT ON COLUMN match_evaluation.anchor_position_analysis_id IS '판정 기준 포지션 카드 식별자.';
COMMENT ON COLUMN match_evaluation.candidate_count IS '판정 후보 수.';
COMMENT ON COLUMN match_evaluation.data_version IS '판정 입력 데이터 버전.';
COMMENT ON COLUMN match_evaluation.candidate_selection_snapshot IS '후보 집합을 선택한 조건과 결과의 스냅샷.';
COMMENT ON COLUMN match_evaluation.generated_at IS '판정 생성 시각.';
COMMENT ON COLUMN match_evaluation.created_at IS '레코드 생성 시각.';

COMMENT ON TABLE match_candidate_evaluation IS '후보별 강함·약함·기각, 순위, 비교 근거, 결정적 걸림돌, 양보 지점, 행동·일정 제안.';
COMMENT ON COLUMN match_candidate_evaluation.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN match_candidate_evaluation.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN match_candidate_evaluation.match_evaluation_id IS '소속 교차 판정 식별자.';
COMMENT ON COLUMN match_candidate_evaluation.candidate_position_analysis_id IS '후보 포지션 카드 식별자.';
COMMENT ON COLUMN match_candidate_evaluation.match_grade IS '중개 판정 등급.';
COMMENT ON COLUMN match_candidate_evaluation.match_rank IS '후보 순위.';
COMMENT ON COLUMN match_candidate_evaluation.evaluation_basis IS '후보 간 비교 근거.';
COMMENT ON COLUMN match_candidate_evaluation.primary_obstacle IS '결정적 걸림돌.';
COMMENT ON COLUMN match_candidate_evaluation.possible_concession IS '양측이 조정할 수 있는 지점.';
COMMENT ON COLUMN match_candidate_evaluation.recommended_action IS '추천 행동 계획 JSON.';
COMMENT ON COLUMN match_candidate_evaluation.exclusion_reason IS '기각 판정 사유.';
COMMENT ON COLUMN match_candidate_evaluation.created_at IS '레코드 생성 시각.';

COMMENT ON TABLE match_candidate_evidence IS '중개 판정의 후보별 근거 원문 또는 추정 표시.';
COMMENT ON COLUMN match_candidate_evidence.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN match_candidate_evidence.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN match_candidate_evidence.match_candidate_evaluation_id IS '소속 중개 판정 후보 식별자.';
COMMENT ON COLUMN match_candidate_evidence.evidence_side IS '근거가 어느 측에서 나온 것인지 구분.';
COMMENT ON COLUMN match_candidate_evidence.field_name IS '근거가 설명하는 판정 필드명.';
COMMENT ON COLUMN match_candidate_evidence.evidence_type IS '원문 인용 또는 추정 근거 유형.';
COMMENT ON COLUMN match_candidate_evidence.interaction_id IS '연결된 상담 로그 식별자.';
COMMENT ON COLUMN match_candidate_evidence.quote_text IS '상담 로그 인용문.';
COMMENT ON COLUMN match_candidate_evidence.quote_start_offset IS '상담 원문에서 후보 판정 근거가 시작하는 문자 오프셋.';
COMMENT ON COLUMN match_candidate_evidence.quote_end_offset IS '상담 원문에서 후보 판정 근거가 끝나는 문자 오프셋.';
COMMENT ON COLUMN match_candidate_evidence.note IS '추정 근거 설명.';
COMMENT ON COLUMN match_candidate_evidence.created_at IS '레코드 생성 시각.';
