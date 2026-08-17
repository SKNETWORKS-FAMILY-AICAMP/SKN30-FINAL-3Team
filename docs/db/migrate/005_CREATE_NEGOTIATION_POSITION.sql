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


COMMENT ON TABLE negotiation_position_analysis IS '매물 대리·손님 대리 포지션 분석의 캐시 단위. 대상 ID, 마지막 로그 시각, 데이터 버전을 cache_key에 반영한다.';
COMMENT ON COLUMN negotiation_position_analysis.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN negotiation_position_analysis.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN negotiation_position_analysis.agent_run_id IS '포지션 분석을 생성한 에이전트 실행 식별자.';
COMMENT ON COLUMN negotiation_position_analysis.negotiation_side IS '매물 측 또는 손님 측 카드 구분.';
COMMENT ON COLUMN negotiation_position_analysis.unit_id IS '연결된 세대 식별자.';
COMMENT ON COLUMN negotiation_position_analysis.listing_id IS '연결된 매물 업무 건 식별자.';
COMMENT ON COLUMN negotiation_position_analysis.requirement_id IS '분석 대상 구입장 수요 식별자.';
COMMENT ON COLUMN negotiation_position_analysis.target_label IS '화면 표시용 대상 라벨.';
COMMENT ON COLUMN negotiation_position_analysis.cache_key IS '서버가 생성한 포지션 카드 캐시 키.';
COMMENT ON COLUMN negotiation_position_analysis.source_interaction_count IS '분석 입력으로 사용한 상담 로그 건수.';
COMMENT ON COLUMN negotiation_position_analysis.last_interaction_at IS '분석 입력에 포함된 마지막 상담 시각.';
COMMENT ON COLUMN negotiation_position_analysis.data_version IS '카드 입력 데이터 버전.';
COMMENT ON COLUMN negotiation_position_analysis.negotiation_intent IS '의향 판정 값.';
COMMENT ON COLUMN negotiation_position_analysis.stated_price_amount IS '장부에 표기된 가격.';
COMMENT ON COLUMN negotiation_position_analysis.estimated_price_amount IS '에이전트가 추정한 실질 가격.';
COMMENT ON COLUMN negotiation_position_analysis.price_estimation_basis IS '추정 가격 근거.';
COMMENT ON COLUMN negotiation_position_analysis.urgency IS '시급도 판정 값.';
COMMENT ON COLUMN negotiation_position_analysis.preferred_timing IS '시점·마감 조건 JSON.';
COMMENT ON COLUMN negotiation_position_analysis.flexible_conditions IS '양보 가능한 조건 목록 JSON.';
COMMENT ON COLUMN negotiation_position_analysis.inflexible_conditions IS '양보 불가 조건 목록 JSON.';
COMMENT ON COLUMN negotiation_position_analysis.contactability_status IS '분석 시점의 연락 가능성 판정 상태.';
COMMENT ON COLUMN negotiation_position_analysis.contactability_note IS '접촉 가능 상태 설명.';
COMMENT ON COLUMN negotiation_position_analysis.analysis_snapshot IS '포지션 카드 전체 스냅샷 JSON.';
COMMENT ON COLUMN negotiation_position_analysis.generated_at IS '카드 생성 시각.';
COMMENT ON COLUMN negotiation_position_analysis.invalidated_at IS '캐시 무효화 시각.';
COMMENT ON COLUMN negotiation_position_analysis.invalidation_reason IS '캐시 무효화 사유.';
COMMENT ON COLUMN negotiation_position_analysis.created_at IS '레코드 생성 시각.';

COMMENT ON TABLE negotiation_position_evidence IS '포지션 카드 항목별 상담 로그 원문 또는 추정 표시. 원문 클릭 시 interaction으로 이동한다.';
COMMENT ON COLUMN negotiation_position_evidence.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN negotiation_position_evidence.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN negotiation_position_evidence.position_analysis_id IS '소속 포지션 카드 식별자.';
COMMENT ON COLUMN negotiation_position_evidence.field_name IS '근거가 연결된 카드 필드명.';
COMMENT ON COLUMN negotiation_position_evidence.evidence_type IS '원문 인용 또는 추정 근거 유형.';
COMMENT ON COLUMN negotiation_position_evidence.interaction_id IS '연결된 상담 로그 식별자.';
COMMENT ON COLUMN negotiation_position_evidence.quote_text IS '상담 로그 인용문.';
COMMENT ON COLUMN negotiation_position_evidence.quote_start_offset IS '상담 원문에서 인용 근거가 시작하는 문자 오프셋.';
COMMENT ON COLUMN negotiation_position_evidence.quote_end_offset IS '상담 원문에서 인용 근거가 끝나는 문자 오프셋.';
COMMENT ON COLUMN negotiation_position_evidence.note IS '추정 근거 설명.';
COMMENT ON COLUMN negotiation_position_evidence.display_order IS '화면 표시 순서.';
COMMENT ON COLUMN negotiation_position_evidence.created_at IS '레코드 생성 시각.';
