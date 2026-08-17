-- REVIEWED ARCHIVE
-- ============================================================================
-- 이 파일은 2026-08-14 통합 58테이블 설계의 검토용 보존본이다.
-- 현재 MVP 생성 기준선은 docs/db/migrate/의 순번 SQL이며 이 파일을 실행하지 않는다.
--
-- 원문 대비 정정:
-- - 명칭 개선 후 남아 있던 5개 인덱스의 구 컬럼 참조를 현재 컬럼명으로 수정했다.
-- - 업무 범위와 테이블 수는 원문 그대로 보존했다.
-- ============================================================================

-- ============================================================================
-- 부동산 중개업무 멀티 에이전트 플랫폼 통합 DDL - 관계 중심 버전
-- PostgreSQL 15+
-- 기준 요구사항: 통합 요구사항 정의서 F1 · F2 · F3 (2026-08-13)
-- 개정 기준일: 2026-08-14
--
-- 설계 원칙
-- ---------------------------------------------------------------------------
-- 1. PostgreSQL은 데이터 저장 구조와 엔터티 관계 무결성에 집중한다.
-- 2. PK, FK, 복합 tenant FK, UNIQUE, NOT NULL, INDEX를 DB 책임으로 둔다.
--    FK는 대상 존재와 tenant 경계를 보장하며, 여러 FK 간 업무상 일치 여부는 서버에서 검증한다.
-- 3. 상태 전이, 승인, 권한 판단, 최신 동의 여부, AI 역할 검증은 서버에서 처리한다.
-- 4. TRIGGER, 사용자 정의 FUNCTION/PROCEDURE, CHECK 제약, CASCADE 동작을 사용하지 않는다.
-- 5. 삭제·복구·갱신·append-only·row_version 증가·updated_at 갱신은 서버 트랜잭션에서 처리한다.
-- 6. F1 업무 원장을 단일 원천으로 유지하고 F2/F3는 F1을 통해 연동한다.
-- 7. 음성·PDF·사진 등 원본 파일은 Object Storage에 두고 DB에는 메타데이터와 관계만 저장한다.
-- 8. 업무 상태값은 VARCHAR로 저장하고 허용값 및 상태 머신은 서버 코드에서 관리한다.
-- 9. pgvector는 필요 시 별도 선택 적용한다. 기본 DDL은 vector 확장에 의존하지 않는다.
-- 10. 본 파일은 신규 환경용 baseline이며 기존 DB에는 별도 migration을 작성한다.
-- ============================================================================

BEGIN;

-- ============================================================================
-- 0. EXTENSIONS
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS pgcrypto;


-- ============================================================================
-- 3. TENANT / USERS
-- ============================================================================

CREATE TABLE brokerage (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name                VARCHAR(120) NOT NULL,
    business_registration_number     VARCHAR(20),
    phone               VARCHAR(30),
    address             TEXT,
    settings            JSONB NOT NULL DEFAULT '{}'::jsonb,
    status              VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    row_version         BIGINT NOT NULL DEFAULT 1,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX uq_brokerage_business_number
    ON brokerage (business_registration_number)
    WHERE business_registration_number IS NOT NULL;

CREATE TABLE app_user (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id        BIGINT NOT NULL,
    login_id            VARCHAR(100) NOT NULL,
    password_hash       TEXT NOT NULL,
    display_name        VARCHAR(80) NOT NULL,
    role                VARCHAR(20) NOT NULL,
    phone               VARCHAR(30),
    ui_preferences      JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    last_login_at       TIMESTAMPTZ,
    row_version         BIGINT NOT NULL DEFAULT 1,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_app_user_brokerage
        FOREIGN KEY (brokerage_id)
        REFERENCES brokerage(id),
    CONSTRAINT uq_app_user_login
        UNIQUE (brokerage_id, login_id),
    CONSTRAINT uq_app_user_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE INDEX idx_app_user_brokerage_active
    ON app_user (brokerage_id, is_active);

-- ============================================================================
-- 4. CONFIGURABLE CODE MASTER / AI MODEL CONFIG
-- ============================================================================

CREATE TABLE code_group (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id        BIGINT NOT NULL,
    code                VARCHAR(50) NOT NULL,
    name                VARCHAR(100) NOT NULL,
    description         TEXT,
    is_system_group     BOOLEAN NOT NULL DEFAULT FALSE,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_by          BIGINT,
    row_version         BIGINT NOT NULL DEFAULT 1,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_code_group_brokerage
        FOREIGN KEY (brokerage_id)
        REFERENCES brokerage(id),
    CONSTRAINT fk_code_group_created_by
        FOREIGN KEY (brokerage_id, created_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_code_group_code
        UNIQUE (brokerage_id, code),
    CONSTRAINT uq_code_group_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE TABLE code_value (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id        BIGINT NOT NULL,
    group_code          VARCHAR(50) NOT NULL,
    code                VARCHAR(50) NOT NULL,
    label               VARCHAR(100) NOT NULL,
    description         TEXT,
    display_order       INTEGER NOT NULL DEFAULT 0,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_by          BIGINT,
    row_version         BIGINT NOT NULL DEFAULT 1,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_code_value_group
        FOREIGN KEY (brokerage_id, group_code)
        REFERENCES code_group (brokerage_id, code),
    CONSTRAINT fk_code_value_created_by
        FOREIGN KEY (brokerage_id, created_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_code_value_code
        UNIQUE (brokerage_id, group_code, code),
    CONSTRAINT uq_code_value_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE INDEX idx_code_value_lookup
    ON code_value (brokerage_id, group_code, is_active, display_order);

CREATE TABLE ai_model_config (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id        BIGINT NOT NULL,
    capability          VARCHAR(40) NOT NULL,
    provider            VARCHAR(80) NOT NULL,
    model_name          VARCHAR(160) NOT NULL,
    endpoint_alias      VARCHAR(160),
    parameters          JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding_dimension INTEGER,
    max_context_tokens  INTEGER,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_by          BIGINT,
    updated_by          BIGINT,
    row_version         BIGINT NOT NULL DEFAULT 1,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_ai_model_config_brokerage
        FOREIGN KEY (brokerage_id)
        REFERENCES brokerage(id),
    CONSTRAINT fk_ai_model_config_created_by
        FOREIGN KEY (brokerage_id, created_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT fk_ai_model_config_updated_by
        FOREIGN KEY (brokerage_id, updated_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_ai_model_config_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE UNIQUE INDEX uq_ai_model_config_active_capability
    ON ai_model_config (brokerage_id, capability)
    WHERE is_active = TRUE;

-- ============================================================================
-- 5. COMPLEX / UNIT TYPE MASTER
-- ============================================================================

CREATE TABLE property_complex (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id        BIGINT NOT NULL,
    property_type       VARCHAR(30) NOT NULL DEFAULT 'APARTMENT',
    name                VARCHAR(150) NOT NULL,
    road_address        TEXT,
    jibun_address       TEXT,
    legal_dong_code     VARCHAR(20),
    household_count     INTEGER,
    completion_year     SMALLINT,
    contacts            JSONB NOT NULL DEFAULT '[]'::jsonb,
    extra_info          JSONB NOT NULL DEFAULT '{}'::jsonb,
    memo                TEXT,
    is_deleted          BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at          TIMESTAMPTZ,
    row_version         BIGINT NOT NULL DEFAULT 1,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_complex_brokerage
        FOREIGN KEY (brokerage_id)
        REFERENCES brokerage(id),
    CONSTRAINT uq_complex_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE INDEX idx_complex_brokerage_type
    ON property_complex (brokerage_id, property_type)
    WHERE is_deleted = FALSE;

CREATE INDEX idx_complex_name_trgm
    ON property_complex USING gin (name gin_trgm_ops);


CREATE TABLE property_complex_unit_type (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id        BIGINT NOT NULL,
    complex_id          BIGINT NOT NULL,
    type_code           VARCHAR(30) NOT NULL,
    pyeong              NUMERIC(6,2),
    exclusive_area_sqm  NUMERIC(10,2),
    supply_area_sqm     NUMERIC(10,2),
    description         TEXT,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    row_version         BIGINT NOT NULL DEFAULT 1,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_complex_unit_type_complex
        FOREIGN KEY (brokerage_id, complex_id)
        REFERENCES property_complex (brokerage_id, id),
    CONSTRAINT uq_complex_unit_type_code
        UNIQUE (brokerage_id, complex_id, type_code),
    CONSTRAINT uq_complex_unit_type_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE INDEX idx_complex_unit_type_complex
    ON property_complex_unit_type (brokerage_id, complex_id, is_active);

-- ============================================================================
-- 6. UNIT / PARTY / LISTING / DEMAND CORE LEDGER
-- ============================================================================

CREATE TABLE property_unit (
    id                          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id                BIGINT NOT NULL,
    complex_id                  BIGINT NOT NULL,
    unit_type_id                BIGINT,
    building_number                 VARCHAR(50),
    unit_number                          VARCHAR(50) NOT NULL,
    unit_usage_type             VARCHAR(30) NOT NULL DEFAULT 'RESIDENTIAL',
    floor_number                    VARCHAR(20),
    orientation                   VARCHAR(30),
    -- 사무소별 선택 코드: TENANCY_STATUS 그룹만 참조한다.
        tenancy_status_group_code   VARCHAR(50) NOT NULL,
    tenancy_status_code         VARCHAR(50),
    current_deposit_amount             BIGINT,
    current_monthly_rent_amount        BIGINT,
    loan_amount                 BIGINT,
    tenancy_expiry_date         DATE,
    tenancy_raw_text                 TEXT,
    is_expanded                 BOOLEAN,
    built_in_features            TEXT,
    facility_condition             TEXT,
    assigned_user_id            BIGINT,
    memo                        TEXT,
    custom_fields               JSONB NOT NULL DEFAULT '{}'::jsonb,
    display_color            VARCHAR(20),
    last_contact_at             TIMESTAMPTZ,
    lifecycle_status            VARCHAR(30) NOT NULL DEFAULT 'NORMAL',
    row_version                 BIGINT NOT NULL DEFAULT 1,
    is_deleted                  BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at                  TIMESTAMPTZ,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_unit_complex
        FOREIGN KEY (brokerage_id, complex_id)
        REFERENCES property_complex (brokerage_id, id),
    CONSTRAINT fk_unit_complex_unit_type
        FOREIGN KEY (brokerage_id, unit_type_id)
        REFERENCES property_complex_unit_type (brokerage_id, id),
    CONSTRAINT fk_unit_tenancy_status_code
        FOREIGN KEY (
        brokerage_id,
        tenancy_status_group_code,
        tenancy_status_code
        )
        REFERENCES code_value (brokerage_id, group_code, code),
    CONSTRAINT fk_unit_assigned_user
        FOREIGN KEY (brokerage_id, assigned_user_id)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_unit_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE UNIQUE INDEX uq_unit_location
    ON property_unit (
        brokerage_id,
        complex_id,
        COALESCE(building_number, ''),
        unit_number
    )
    WHERE is_deleted = FALSE;

CREATE INDEX idx_unit_complex
    ON property_unit (brokerage_id, complex_id)
    WHERE is_deleted = FALSE;

CREATE INDEX idx_unit_lifecycle
    ON property_unit (brokerage_id, lifecycle_status)
    WHERE is_deleted = FALSE;

CREATE INDEX idx_unit_expiry
    ON property_unit (brokerage_id, tenancy_expiry_date)
    WHERE tenancy_expiry_date IS NOT NULL
      AND is_deleted = FALSE;

CREATE INDEX idx_unit_last_contact
    ON property_unit (brokerage_id, last_contact_at DESC)
    WHERE is_deleted = FALSE;


CREATE TABLE party (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id            BIGINT NOT NULL,
    party_type              VARCHAR(20) NOT NULL,
    name                    VARCHAR(150) NOT NULL,
    alternate_name                   VARCHAR(150),
    birth_date              DATE,
    business_registration_number         VARCHAR(20),
    memo                    TEXT,
    merged_target_party_id    BIGINT,
    is_deleted              BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at              TIMESTAMPTZ,
    row_version             BIGINT NOT NULL DEFAULT 1,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_party_brokerage
        FOREIGN KEY (brokerage_id)
        REFERENCES brokerage(id),
    CONSTRAINT uq_party_tenant_id
        UNIQUE (brokerage_id, id),
    CONSTRAINT fk_party_merged_into
        FOREIGN KEY (brokerage_id, merged_target_party_id)
        REFERENCES party (brokerage_id, id)
);

CREATE INDEX idx_party_name_trgm
    ON party USING gin (name gin_trgm_ops);

CREATE INDEX idx_party_alias_trgm
    ON party USING gin (alternate_name gin_trgm_ops);

CREATE INDEX idx_party_business_number
    ON party (brokerage_id, business_registration_number)
    WHERE business_registration_number IS NOT NULL
      AND is_deleted = FALSE;


CREATE TABLE party_contact (
    id                          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id                BIGINT NOT NULL,
    party_id                    BIGINT NOT NULL,
    contact_method                VARCHAR(20) NOT NULL DEFAULT 'PHONE',
    contact_value                       VARCHAR(320) NOT NULL,
    normalized_contact_value            VARCHAR(320) NOT NULL,
    contact_label                       VARCHAR(50),
    marker_group_code           VARCHAR(50) NOT NULL,
    marker_code                 VARCHAR(50),
    display_order               INTEGER NOT NULL DEFAULT 0,
    is_primary                  BOOLEAN NOT NULL DEFAULT FALSE,
    is_sms_opted_out                 BOOLEAN NOT NULL DEFAULT FALSE,
    sms_opted_out_at              TIMESTAMPTZ,
    sms_opt_out_reason          TEXT,
    is_deleted                  BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at                  TIMESTAMPTZ,
    row_version                 BIGINT NOT NULL DEFAULT 1,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_party_contact_party
        FOREIGN KEY (brokerage_id, party_id)
        REFERENCES party (brokerage_id, id),
    CONSTRAINT fk_party_contact_marker
        FOREIGN KEY (brokerage_id, marker_group_code, marker_code)
        REFERENCES code_value (brokerage_id, group_code, code),
    CONSTRAINT uq_party_contact_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE UNIQUE INDEX uq_party_contact_value
    ON party_contact (
        brokerage_id,
        party_id,
        contact_method,
        normalized_contact_value
    )
    WHERE is_deleted = FALSE;

CREATE UNIQUE INDEX uq_party_contact_primary
    ON party_contact (brokerage_id, party_id, contact_method)
    WHERE is_primary = TRUE
      AND is_deleted = FALSE;

CREATE INDEX idx_party_contact_phone_search
    ON party_contact (brokerage_id, normalized_contact_value)
    WHERE contact_method = 'PHONE'
      AND is_deleted = FALSE;


CREATE TABLE property_unit_party_relation (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id        BIGINT NOT NULL,
    unit_id             BIGINT NOT NULL,
    party_id            BIGINT NOT NULL,
    role                VARCHAR(20) NOT NULL,
    role_index          SMALLINT NOT NULL DEFAULT 1,
    is_primary          BOOLEAN NOT NULL DEFAULT FALSE,
    is_co_owner         BOOLEAN NOT NULL DEFAULT FALSE,
    valid_from          DATE,
    valid_to            DATE,
    memo                TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_unit_party_relation_unit
        FOREIGN KEY (brokerage_id, unit_id)
        REFERENCES property_unit (brokerage_id, id),
    CONSTRAINT fk_unit_party_relation_party
        FOREIGN KEY (brokerage_id, party_id)
        REFERENCES party (brokerage_id, id),
    CONSTRAINT uq_unit_party_relation_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE UNIQUE INDEX uq_unit_party_relation_current_index
    ON property_unit_party_relation (brokerage_id, unit_id, role, role_index)
    WHERE valid_to IS NULL;

CREATE UNIQUE INDEX uq_unit_party_relation_current_primary
    ON property_unit_party_relation (brokerage_id, unit_id, role)
    WHERE valid_to IS NULL
      AND is_primary = TRUE;

CREATE INDEX idx_unit_party_relation_party
    ON property_unit_party_relation (brokerage_id, party_id, role);


CREATE TABLE party_merge_history (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id        BIGINT NOT NULL,
    source_party_id     BIGINT NOT NULL,
    target_party_id     BIGINT NOT NULL,
    source_snapshot     JSONB NOT NULL,
    target_snapshot     JSONB NOT NULL,
    merged_by           BIGINT NOT NULL,
    merged_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    memo                TEXT,
    CONSTRAINT fk_party_merge_source
        FOREIGN KEY (brokerage_id, source_party_id)
        REFERENCES party (brokerage_id, id),
    CONSTRAINT fk_party_merge_target
        FOREIGN KEY (brokerage_id, target_party_id)
        REFERENCES party (brokerage_id, id),
    CONSTRAINT fk_party_merge_user
        FOREIGN KEY (brokerage_id, merged_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_party_merge_history_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE TABLE consent_event (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id        BIGINT NOT NULL,
    party_id            BIGINT NOT NULL,
    event_type          VARCHAR(10) NOT NULL,
    document_version    VARCHAR(50) NOT NULL,
    purpose             TEXT,
    items               TEXT,
    retention_period    TEXT,
    source_type         VARCHAR(10) NOT NULL DEFAULT 'HUMAN',
    occurred_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    recorded_by         BIGINT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_consent_event_party
        FOREIGN KEY (brokerage_id, party_id)
        REFERENCES party (brokerage_id, id),
    CONSTRAINT fk_consent_event_recorded_by
        FOREIGN KEY (brokerage_id, recorded_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_consent_event_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE INDEX idx_consent_event_party
    ON consent_event (brokerage_id, party_id, occurred_at DESC);


CREATE TABLE property_listing (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id        BIGINT NOT NULL,
    unit_id             BIGINT NOT NULL,
    received_at         DATE NOT NULL DEFAULT CURRENT_DATE,
    status              VARCHAR(30) NOT NULL DEFAULT 'RECEIVED',
    handover_condition  VARCHAR(100),
    is_sale_available        BOOLEAN NOT NULL DEFAULT FALSE,
    sale_price          BIGINT,
    is_jeonse_available      BOOLEAN NOT NULL DEFAULT FALSE,
    jeonse_deposit_amount      BIGINT,
    is_monthly_rent_available     BOOLEAN NOT NULL DEFAULT FALSE,
    monthly_rent_deposit_amount     BIGINT,
    monthly_rent_amount        BIGINT,
    price_raw_text           TEXT,
    client_party_id     BIGINT,
    co_broker_party_id  BIGINT,
    assigned_user_id    BIGINT,
    memo                TEXT,
    custom_fields       JSONB NOT NULL DEFAULT '{}'::jsonb,
    closed_at           DATE,
    closed_price_amount        BIGINT,
    row_version         BIGINT NOT NULL DEFAULT 1,
    is_deleted          BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at          TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_listing_unit
        FOREIGN KEY (brokerage_id, unit_id)
        REFERENCES property_unit (brokerage_id, id),
    CONSTRAINT fk_listing_client_party
        FOREIGN KEY (brokerage_id, client_party_id)
        REFERENCES party (brokerage_id, id),
    CONSTRAINT fk_listing_co_broker_party
        FOREIGN KEY (brokerage_id, co_broker_party_id)
        REFERENCES party (brokerage_id, id),
    CONSTRAINT fk_listing_assigned_user
        FOREIGN KEY (brokerage_id, assigned_user_id)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_listing_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE INDEX idx_listing_unit
    ON property_listing (brokerage_id, unit_id, received_at DESC)
    WHERE is_deleted = FALSE;

CREATE INDEX idx_listing_status
    ON property_listing (brokerage_id, status)
    WHERE is_deleted = FALSE;


CREATE TABLE property_requirement (
    id                          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id                BIGINT NOT NULL,
    party_id                    BIGINT NOT NULL,
    consent_grant_event_id      BIGINT NOT NULL,
    received_at                 DATE NOT NULL DEFAULT CURRENT_DATE,
    demand_type                 VARCHAR(20) NOT NULL,
    desired_pyeongs             NUMERIC(6,2)[],
    min_area_sqm                NUMERIC(10,2),
    max_area_sqm                NUMERIC(10,2),
    area_requirement_raw_text                    TEXT,
    min_budget_amount                  BIGINT,
    max_budget_amount                  BIGINT,
    budget_raw_text                  TEXT,
    desired_move_in_date                   DATE,
    move_in_date_raw_text               TEXT,
    request_expiry_date                 DATE,
    workflow_stage              VARCHAR(100),
    status                      VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    completed_at                TIMESTAMPTZ,
    matched_unit_id           BIGINT,
    closure_reason           TEXT,
    co_broker_party_id          BIGINT,
    assigned_user_id            BIGINT,
    classification_group_code   VARCHAR(50) NOT NULL,
    classification_code         VARCHAR(50),
    display_color            VARCHAR(20),
    memo                        TEXT,
    custom_fields               JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_contact_at             TIMESTAMPTZ,
    row_version                 BIGINT NOT NULL DEFAULT 1,
    is_deleted                  BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at                  TIMESTAMPTZ,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_demand_party
        FOREIGN KEY (brokerage_id, party_id)
        REFERENCES party (brokerage_id, id),
    CONSTRAINT fk_demand_consent
        FOREIGN KEY (brokerage_id, consent_grant_event_id)
        REFERENCES consent_event (brokerage_id, id),
    CONSTRAINT fk_demand_completed_unit
        FOREIGN KEY (brokerage_id, matched_unit_id)
        REFERENCES property_unit (brokerage_id, id),
    CONSTRAINT fk_demand_co_broker_party
        FOREIGN KEY (brokerage_id, co_broker_party_id)
        REFERENCES party (brokerage_id, id),
    CONSTRAINT fk_demand_assigned_user
        FOREIGN KEY (brokerage_id, assigned_user_id)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT fk_demand_classification_code
        FOREIGN KEY (
        brokerage_id,
        classification_group_code,
        classification_code
        )
        REFERENCES code_value (brokerage_id, group_code, code),
    CONSTRAINT uq_demand_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE INDEX idx_demand_party
    ON property_requirement (brokerage_id, party_id, received_at DESC)
    WHERE is_deleted = FALSE;

CREATE INDEX idx_demand_status
    ON property_requirement (brokerage_id, status, received_at DESC)
    WHERE is_deleted = FALSE;

CREATE INDEX idx_demand_expiry
    ON property_requirement (brokerage_id, request_expiry_date)
    WHERE request_expiry_date IS NOT NULL
      AND is_deleted = FALSE;

CREATE INDEX idx_demand_last_contact
    ON property_requirement (brokerage_id, last_contact_at DESC)
    WHERE is_deleted = FALSE;



CREATE TABLE property_requirement_complex (
    brokerage_id        BIGINT NOT NULL,
    demand_id           BIGINT NOT NULL,
    complex_id          BIGINT NOT NULL,
    preference_order    SMALLINT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_demand_complex
        PRIMARY KEY (brokerage_id, demand_id, complex_id),
    CONSTRAINT fk_demand_complex_demand
        FOREIGN KEY (brokerage_id, demand_id)
        REFERENCES property_requirement (brokerage_id, id),
    CONSTRAINT fk_demand_complex_complex
        FOREIGN KEY (brokerage_id, complex_id)
        REFERENCES property_complex (brokerage_id, id)
);

CREATE INDEX idx_demand_complex_complex
    ON property_requirement_complex (brokerage_id, complex_id, demand_id);


-- ============================================================================
-- 7. DRAFT / INTERACTION LOG
-- ============================================================================

CREATE TABLE ledger_draft (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id        BIGINT NOT NULL,
    ledger_type         VARCHAR(20) NOT NULL,
    status              VARCHAR(20) NOT NULL DEFAULT 'DRAFT',
    source_type         VARCHAR(10) NOT NULL DEFAULT 'HUMAN',
    target_unit_id      BIGINT,
    target_listing_id   BIGINT,
    target_demand_id    BIGINT,
    final_unit_id       BIGINT,
    final_listing_id    BIGINT,
    final_demand_id     BIGINT,
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
        REFERENCES brokerage(id),
    CONSTRAINT fk_ledger_draft_target_unit
        FOREIGN KEY (brokerage_id, target_unit_id)
        REFERENCES property_unit (brokerage_id, id),
    CONSTRAINT fk_ledger_draft_target_listing
        FOREIGN KEY (brokerage_id, target_listing_id)
        REFERENCES property_listing (brokerage_id, id),
    CONSTRAINT fk_ledger_draft_target_demand
        FOREIGN KEY (brokerage_id, target_demand_id)
        REFERENCES property_requirement (brokerage_id, id),
    CONSTRAINT fk_ledger_draft_final_unit
        FOREIGN KEY (brokerage_id, final_unit_id)
        REFERENCES property_unit (brokerage_id, id),
    CONSTRAINT fk_ledger_draft_final_listing
        FOREIGN KEY (brokerage_id, final_listing_id)
        REFERENCES property_listing (brokerage_id, id),
    CONSTRAINT fk_ledger_draft_final_demand
        FOREIGN KEY (brokerage_id, final_demand_id)
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

CREATE TABLE client_interaction (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id            BIGINT NOT NULL,
    interaction_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    interaction_channel                 VARCHAR(20) NOT NULL DEFAULT 'CALL',
    communication_direction               VARCHAR(20),
    interaction_result                  VARCHAR(20),
    counterparty_role        VARCHAR(20),
    counterparty_index       SMALLINT,
    marker_text             VARCHAR(10),
    interaction_content                    TEXT NOT NULL,
    legacy_format_type           TEXT,
    party_id                BIGINT,
    unit_id                 BIGINT,
    listing_id              BIGINT,
    demand_id               BIGINT,
    related_context         JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_type             VARCHAR(10) NOT NULL DEFAULT 'HUMAN',
    approval_status         VARCHAR(20) NOT NULL DEFAULT 'NOT_REQUIRED',
    approved_by             BIGINT,
    approved_at             TIMESTAMPTZ,
    source_metadata         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by              BIGINT,
    is_voided                 BOOLEAN NOT NULL DEFAULT FALSE,
    void_reason             TEXT,
    voided_by               BIGINT,
    voided_at               TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_interaction_brokerage
        FOREIGN KEY (brokerage_id)
        REFERENCES brokerage(id),
    CONSTRAINT fk_interaction_party
        FOREIGN KEY (brokerage_id, party_id)
        REFERENCES party (brokerage_id, id),
    CONSTRAINT fk_interaction_unit
        FOREIGN KEY (brokerage_id, unit_id)
        REFERENCES property_unit (brokerage_id, id),
    CONSTRAINT fk_interaction_listing
        FOREIGN KEY (brokerage_id, listing_id)
        REFERENCES property_listing (brokerage_id, id),
    CONSTRAINT fk_interaction_demand
        FOREIGN KEY (brokerage_id, demand_id)
        REFERENCES property_requirement (brokerage_id, id),
    CONSTRAINT fk_interaction_created_by
        FOREIGN KEY (brokerage_id, created_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT fk_interaction_approved_by
        FOREIGN KEY (brokerage_id, approved_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT fk_interaction_voided_by
        FOREIGN KEY (brokerage_id, voided_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_interaction_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE INDEX idx_interaction_unit
    ON client_interaction (brokerage_id, unit_id, occurred_at DESC)
    WHERE is_void = FALSE;

CREATE INDEX idx_interaction_demand
    ON client_interaction (brokerage_id, demand_id, interaction_at DESC)
    WHERE is_voided = FALSE;

CREATE INDEX idx_interaction_party
    ON client_interaction (brokerage_id, party_id, interaction_at DESC)
    WHERE is_voided = FALSE;

CREATE INDEX idx_interaction_listing
    ON client_interaction (brokerage_id, listing_id, interaction_at DESC)
    WHERE is_voided = FALSE;

CREATE INDEX idx_interaction_source
    ON client_interaction (brokerage_id, source_type, interaction_at DESC)
    WHERE is_voided = FALSE;

CREATE INDEX idx_interaction_body_trgm
    ON client_interaction USING gin (interaction_content gin_trgm_ops);


-- ============================================================================
-- 8. TENANCY / CONTRACT / TRANSACTION / SCHEDULE
-- ============================================================================

CREATE TABLE tenancy_history (
    id                          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id                BIGINT NOT NULL,
    unit_id                     BIGINT NOT NULL,
    valid_from                  DATE,
    valid_to                    DATE,
    tenancy_status_group_code   VARCHAR(50) NOT NULL,
    tenancy_status_code         VARCHAR(50),
    deposit_amount                     BIGINT,
    monthly_rent_amount                BIGINT,
    loan_amount                 BIGINT,
    expiry_date                 DATE,
    tenancy_raw_text                    TEXT,
    tenant_parties_snapshot            JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_interaction_id       BIGINT,
    created_by                  BIGINT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_tenancy_history_unit
        FOREIGN KEY (brokerage_id, unit_id)
        REFERENCES property_unit (brokerage_id, id),
    CONSTRAINT fk_tenancy_history_status_code
        FOREIGN KEY (
        brokerage_id,
        tenancy_status_group_code,
        tenancy_status_code
        )
        REFERENCES code_value (brokerage_id, group_code, code),
    CONSTRAINT fk_tenancy_history_interaction
        FOREIGN KEY (brokerage_id, source_interaction_id)
        REFERENCES client_interaction (brokerage_id, id),
    CONSTRAINT fk_tenancy_history_created_by
        FOREIGN KEY (brokerage_id, created_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_tenancy_history_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE INDEX idx_tenancy_history_unit
    ON tenancy_history (brokerage_id, unit_id, valid_from DESC NULLS LAST, created_at DESC);


CREATE TABLE property_contract (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id        BIGINT NOT NULL,
    unit_id             BIGINT NOT NULL,
    listing_id          BIGINT,
    demand_id           BIGINT,
    contract_type       VARCHAR(20) NOT NULL,
    status              VARCHAR(20) NOT NULL DEFAULT 'SIGNED',
    executed_at         DATE,
    contract_price_amount               BIGINT,
    contract_deposit_amount             BIGINT,
    monthly_rent_amount        BIGINT,
    intermediate_date   DATE,
    balance_date        DATE,
    contract_parties             JSONB NOT NULL DEFAULT '{}'::jsonb,
    contract_checklist           JSONB NOT NULL DEFAULT '{}'::jsonb,
    memo                TEXT,
    assigned_user_id    BIGINT,
    row_version         BIGINT NOT NULL DEFAULT 1,
    is_deleted          BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at          TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_contract_unit
        FOREIGN KEY (brokerage_id, unit_id)
        REFERENCES property_unit (brokerage_id, id),
    CONSTRAINT fk_contract_listing
        FOREIGN KEY (brokerage_id, listing_id)
        REFERENCES property_listing (brokerage_id, id),
    CONSTRAINT fk_contract_demand
        FOREIGN KEY (brokerage_id, demand_id)
        REFERENCES property_requirement (brokerage_id, id),
    CONSTRAINT fk_contract_assigned_user
        FOREIGN KEY (brokerage_id, assigned_user_id)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_contract_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE INDEX idx_contract_unit
    ON property_contract (brokerage_id, unit_id, executed_at DESC NULLS LAST)
    WHERE is_deleted = FALSE;

CREATE INDEX idx_contract_status
    ON property_contract (brokerage_id, status, balance_date)
    WHERE is_deleted = FALSE;


CREATE TABLE property_transaction_history (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id        BIGINT NOT NULL,
    unit_id             BIGINT NOT NULL,
    listing_id          BIGINT,
    demand_id           BIGINT,
    contract_id         BIGINT,
    transaction_type    VARCHAR(20) NOT NULL,
    completed_at        TIMESTAMPTZ NOT NULL,
    transaction_price_amount               BIGINT,
    deposit_amount             BIGINT,
    monthly_rent_amount        BIGINT,
    co_broker_party_id  BIGINT,
    assigned_user_id    BIGINT,
    parties_snapshot    JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_type         VARCHAR(10) NOT NULL DEFAULT 'HUMAN',
    memo                TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_transaction_history_unit
        FOREIGN KEY (brokerage_id, unit_id)
        REFERENCES property_unit (brokerage_id, id),
    CONSTRAINT fk_transaction_history_listing
        FOREIGN KEY (brokerage_id, listing_id)
        REFERENCES property_listing (brokerage_id, id),
    CONSTRAINT fk_transaction_history_demand
        FOREIGN KEY (brokerage_id, demand_id)
        REFERENCES property_requirement (brokerage_id, id),
    CONSTRAINT fk_transaction_history_contract
        FOREIGN KEY (brokerage_id, contract_id)
        REFERENCES property_contract (brokerage_id, id),
    CONSTRAINT fk_transaction_history_co_broker
        FOREIGN KEY (brokerage_id, co_broker_party_id)
        REFERENCES party (brokerage_id, id),
    CONSTRAINT fk_transaction_history_assigned_user
        FOREIGN KEY (brokerage_id, assigned_user_id)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_transaction_history_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE INDEX idx_transaction_history_unit
    ON property_transaction_history (brokerage_id, unit_id, completed_at DESC);

CREATE INDEX idx_transaction_history_demand
    ON property_transaction_history (brokerage_id, demand_id, completed_at DESC)
    WHERE demand_id IS NOT NULL;


CREATE TABLE business_schedule_event (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id        BIGINT NOT NULL,
    title               VARCHAR(200) NOT NULL,
    event_type          VARCHAR(30),
    starts_at           TIMESTAMPTZ NOT NULL,
    ends_at             TIMESTAMPTZ,
    location            TEXT,
    memo                TEXT,
    assigned_user_id    BIGINT,
    unit_id             BIGINT,
    listing_id          BIGINT,
    demand_id           BIGINT,
    contract_id         BIGINT,
    status              VARCHAR(20) NOT NULL DEFAULT 'SCHEDULED',
    source_type         VARCHAR(10) NOT NULL DEFAULT 'HUMAN',
    approval_status     VARCHAR(20) NOT NULL DEFAULT 'NOT_REQUIRED',
    approved_by         BIGINT,
    approved_at         TIMESTAMPTZ,
    source_metadata     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by          BIGINT,
    row_version         BIGINT NOT NULL DEFAULT 1,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_schedule_event_brokerage
        FOREIGN KEY (brokerage_id)
        REFERENCES brokerage(id),
    CONSTRAINT fk_schedule_event_assigned_user
        FOREIGN KEY (brokerage_id, assigned_user_id)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT fk_schedule_event_unit
        FOREIGN KEY (brokerage_id, unit_id)
        REFERENCES property_unit (brokerage_id, id),
    CONSTRAINT fk_schedule_event_listing
        FOREIGN KEY (brokerage_id, listing_id)
        REFERENCES property_listing (brokerage_id, id),
    CONSTRAINT fk_schedule_event_demand
        FOREIGN KEY (brokerage_id, demand_id)
        REFERENCES property_requirement (brokerage_id, id),
    CONSTRAINT fk_schedule_event_contract
        FOREIGN KEY (brokerage_id, contract_id)
        REFERENCES property_contract (brokerage_id, id),
    CONSTRAINT fk_schedule_event_created_by
        FOREIGN KEY (brokerage_id, created_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT fk_schedule_event_approved_by
        FOREIGN KEY (brokerage_id, approved_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_schedule_event_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE INDEX idx_schedule_event_date
    ON business_schedule_event (brokerage_id, starts_at);

CREATE INDEX idx_schedule_event_assignee
    ON business_schedule_event (brokerage_id, assigned_user_id, starts_at);

-- ============================================================================
-- 9. OBJECT STORAGE DOCUMENT METADATA / LINKS
-- ============================================================================

CREATE TABLE stored_document (
    id                          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id                BIGINT NOT NULL,
    document_type_group_code    VARCHAR(50) NOT NULL,
    document_type_code          VARCHAR(50) NOT NULL,
    original_filename           VARCHAR(500) NOT NULL,
    storage_object_key                  TEXT NOT NULL,
    mime_type                   VARCHAR(150) NOT NULL,
    file_size_bytes                  BIGINT NOT NULL,
    checksum_sha256             VARCHAR(64),
    issued_at                   DATE,
    expires_at                  DATE,
    access_security_level              VARCHAR(20) NOT NULL DEFAULT 'NORMAL',
    retention_until             TIMESTAMPTZ,
    document_metadata                    JSONB NOT NULL DEFAULT '{}'::jsonb,
    uploaded_by                 BIGINT,
    is_deleted                  BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at                  TIMESTAMPTZ,
    row_version                 BIGINT NOT NULL DEFAULT 1,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_document_brokerage
        FOREIGN KEY (brokerage_id)
        REFERENCES brokerage(id),
    CONSTRAINT fk_document_type_code
        FOREIGN KEY (
        brokerage_id,
        document_type_group_code,
        document_type_code
        )
        REFERENCES code_value (brokerage_id, group_code, code),
    CONSTRAINT fk_document_uploaded_by
        FOREIGN KEY (brokerage_id, uploaded_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_document_object_key
        UNIQUE (brokerage_id, storage_object_key),
    CONSTRAINT uq_document_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE INDEX idx_document_expiry
    ON stored_document (brokerage_id, expires_at)
    WHERE expires_at IS NOT NULL
      AND is_deleted = FALSE;

CREATE INDEX idx_document_security
    ON stored_document (brokerage_id, access_security_level, created_at DESC)
    WHERE is_deleted = FALSE;


CREATE TABLE property_unit_document (
    brokerage_id        BIGINT NOT NULL,
    unit_id             BIGINT NOT NULL,
    document_id         BIGINT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (brokerage_id, unit_id, document_id),
    CONSTRAINT fk_unit_document_unit
        FOREIGN KEY (brokerage_id, unit_id)
        REFERENCES property_unit (brokerage_id, id),
    CONSTRAINT fk_unit_document_document
        FOREIGN KEY (brokerage_id, document_id)
        REFERENCES stored_document (brokerage_id, id)
);

CREATE TABLE party_document (
    brokerage_id        BIGINT NOT NULL,
    party_id            BIGINT NOT NULL,
    document_id         BIGINT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (brokerage_id, party_id, document_id),
    CONSTRAINT fk_party_document_party
        FOREIGN KEY (brokerage_id, party_id)
        REFERENCES party (brokerage_id, id),
    CONSTRAINT fk_party_document_document
        FOREIGN KEY (brokerage_id, document_id)
        REFERENCES stored_document (brokerage_id, id)
);

CREATE TABLE property_requirement_document (
    brokerage_id        BIGINT NOT NULL,
    demand_id           BIGINT NOT NULL,
    document_id         BIGINT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (brokerage_id, demand_id, document_id),
    CONSTRAINT fk_demand_document_demand
        FOREIGN KEY (brokerage_id, demand_id)
        REFERENCES property_requirement (brokerage_id, id),
    CONSTRAINT fk_demand_document_document
        FOREIGN KEY (brokerage_id, document_id)
        REFERENCES stored_document (brokerage_id, id)
);

CREATE TABLE property_contract_document (
    brokerage_id        BIGINT NOT NULL,
    contract_id         BIGINT NOT NULL,
    document_id         BIGINT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (brokerage_id, contract_id, document_id),
    CONSTRAINT fk_contract_document_contract
        FOREIGN KEY (brokerage_id, contract_id)
        REFERENCES property_contract (brokerage_id, id),
    CONSTRAINT fk_contract_document_document
        FOREIGN KEY (brokerage_id, document_id)
        REFERENCES stored_document (brokerage_id, id)
);

CREATE TABLE client_interaction_document (
    brokerage_id        BIGINT NOT NULL,
    interaction_id      BIGINT NOT NULL,
    document_id         BIGINT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (brokerage_id, interaction_id, document_id),
    CONSTRAINT fk_interaction_document_interaction
        FOREIGN KEY (brokerage_id, interaction_id)
        REFERENCES client_interaction (brokerage_id, id),
    CONSTRAINT fk_interaction_document_document
        FOREIGN KEY (brokerage_id, document_id)
        REFERENCES stored_document (brokerage_id, id)
);

-- ============================================================================
-- 10. OPTIONAL F1 P2 DATA
-- ============================================================================

CREATE TABLE facility_history (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id        BIGINT NOT NULL,
    unit_id             BIGINT NOT NULL,
    occurred_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    category            VARCHAR(80),
    description         TEXT NOT NULL,
    interaction_id      BIGINT,
    created_by          BIGINT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_facility_history_unit
        FOREIGN KEY (brokerage_id, unit_id)
        REFERENCES property_unit (brokerage_id, id),
    CONSTRAINT fk_facility_history_interaction
        FOREIGN KEY (brokerage_id, interaction_id)
        REFERENCES client_interaction (brokerage_id, id),
    CONSTRAINT fk_facility_history_created_by
        FOREIGN KEY (brokerage_id, created_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_facility_history_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE INDEX idx_facility_history_unit
    ON facility_history (brokerage_id, unit_id, occurred_at DESC);


CREATE TABLE business_memo (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id        BIGINT NOT NULL,
    title               VARCHAR(200),
    memo_content                TEXT NOT NULL,
    is_pinned           BOOLEAN NOT NULL DEFAULT FALSE,
    created_by          BIGINT NOT NULL,
    updated_by          BIGINT,
    is_deleted          BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at          TIMESTAMPTZ,
    row_version         BIGINT NOT NULL DEFAULT 1,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_general_memo_brokerage
        FOREIGN KEY (brokerage_id)
        REFERENCES brokerage(id),
    CONSTRAINT fk_general_memo_created_by
        FOREIGN KEY (brokerage_id, created_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT fk_general_memo_updated_by
        FOREIGN KEY (brokerage_id, updated_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_general_memo_tenant_id
        UNIQUE (brokerage_id, id)
);

-- ============================================================================
-- 11. MESSAGE TEMPLATE / SEND / RECIPIENT HISTORY
-- ============================================================================

CREATE TABLE message_template (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id        BIGINT NOT NULL,
    owner_user_id       BIGINT,
    name                VARCHAR(120) NOT NULL,
    body                TEXT NOT NULL,
    variables           JSONB NOT NULL DEFAULT '[]'::jsonb,
    is_shared           BOOLEAN NOT NULL DEFAULT TRUE,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_by          BIGINT NOT NULL,
    row_version         BIGINT NOT NULL DEFAULT 1,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_message_template_brokerage
        FOREIGN KEY (brokerage_id)
        REFERENCES brokerage(id),
    CONSTRAINT fk_message_template_owner
        FOREIGN KEY (brokerage_id, owner_user_id)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT fk_message_template_created_by
        FOREIGN KEY (brokerage_id, created_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_message_template_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE UNIQUE INDEX uq_message_template_scope_name
    ON message_template (
        brokerage_id,
        COALESCE(owner_user_id, 0),
        name
    )
    WHERE is_active = TRUE;

CREATE TABLE message_delivery (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id        BIGINT NOT NULL,
    delivery_scope           VARCHAR(20) NOT NULL,
    delivery_mode       VARCHAR(20) NOT NULL DEFAULT 'COPY_ONLY',
    status              VARCHAR(20) NOT NULL DEFAULT 'DRAFT',
    source_type         VARCHAR(10) NOT NULL DEFAULT 'HUMAN',
    template_id         BIGINT,
    subject             VARCHAR(200),
    message_body_template       TEXT NOT NULL,
    total_recipient_count     INTEGER NOT NULL DEFAULT 0,
    excluded_recipient_count      INTEGER NOT NULL DEFAULT 0,
    successful_recipient_count       INTEGER NOT NULL DEFAULT 0,
    failed_recipient_count       INTEGER NOT NULL DEFAULT 0,
    sender_user_id      BIGINT NOT NULL,
    approved_by         BIGINT,
    approved_at         TIMESTAMPTZ,
    copied_at           TIMESTAMPTZ,
    sent_at             TIMESTAMPTZ,
    delivery_provider_response    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_message_send_brokerage
        FOREIGN KEY (brokerage_id)
        REFERENCES brokerage(id),
    CONSTRAINT fk_message_send_template
        FOREIGN KEY (brokerage_id, template_id)
        REFERENCES message_template (brokerage_id, id),
    CONSTRAINT fk_message_send_sender
        FOREIGN KEY (brokerage_id, sender_user_id)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT fk_message_send_approved_by
        FOREIGN KEY (brokerage_id, approved_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_message_send_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE INDEX idx_message_send_date
    ON message_delivery (brokerage_id, created_at DESC);

CREATE INDEX idx_message_send_status
    ON message_delivery (brokerage_id, status, created_at DESC);

CREATE TABLE message_recipient (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id            BIGINT NOT NULL,
    message_delivery_id         BIGINT NOT NULL,
    party_id                BIGINT NOT NULL,
    party_contact_id        BIGINT NOT NULL,
    unit_id                 BIGINT,
    demand_id               BIGINT,
    interaction_id          BIGINT,
    recipient_name_snapshot VARCHAR(150),
    phone_raw_snapshot      VARCHAR(30) NOT NULL,
    phone_normalized        VARCHAR(20) NOT NULL,
    rendered_body           TEXT NOT NULL,
    status                  VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    excluded_reason         TEXT,
    failure_reason          TEXT,
    processed_at            TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_message_recipient_send
        FOREIGN KEY (brokerage_id, message_delivery_id)
        REFERENCES message_delivery (brokerage_id, id),
    CONSTRAINT fk_message_recipient_contact
        FOREIGN KEY (brokerage_id, party_contact_id)
        REFERENCES party_contact (brokerage_id, id),
    CONSTRAINT fk_message_recipient_unit
        FOREIGN KEY (brokerage_id, unit_id)
        REFERENCES property_unit (brokerage_id, id),
    CONSTRAINT fk_message_recipient_demand
        FOREIGN KEY (brokerage_id, demand_id)
        REFERENCES property_requirement (brokerage_id, id),
    CONSTRAINT fk_message_recipient_interaction
        FOREIGN KEY (brokerage_id, interaction_id)
        REFERENCES client_interaction (brokerage_id, id),
    CONSTRAINT uq_message_recipient_tenant_id
        UNIQUE (brokerage_id, id),
    CONSTRAINT uq_message_recipient_phone
        UNIQUE (brokerage_id, message_delivery_id, phone_normalized)
);

CREATE INDEX idx_message_recipient_party
    ON message_recipient (brokerage_id, party_id, created_at DESC);

CREATE INDEX idx_message_recipient_contact
    ON message_recipient (brokerage_id, party_contact_id, created_at DESC);


-- ============================================================================
-- 12. NOTIFICATION CENTER / USER RULES
-- ============================================================================

CREATE TABLE notification_preference (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id        BIGINT NOT NULL,
    user_id             BIGINT NOT NULL,
    notification_type   VARCHAR(30) NOT NULL,
    is_enabled          BOOLEAN NOT NULL DEFAULT TRUE,
    threshold_days      INTEGER,
    config              JSONB NOT NULL DEFAULT '{}'::jsonb,
    row_version         BIGINT NOT NULL DEFAULT 1,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_notification_preference_user
        FOREIGN KEY (brokerage_id, user_id)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_notification_preference
        UNIQUE (brokerage_id, user_id, notification_type),
    CONSTRAINT uq_notification_preference_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE TABLE notification (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id        BIGINT NOT NULL,
    user_id             BIGINT NOT NULL,
    notification_type   VARCHAR(30) NOT NULL,
    title               VARCHAR(200) NOT NULL,
    message             TEXT,
    due_at              TIMESTAMPTZ,
    unit_id             BIGINT,
    listing_id          BIGINT,
    demand_id           BIGINT,
    schedule_event_id   BIGINT,
    contract_id         BIGINT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    read_at             TIMESTAMPTZ,
    dismissed_at        TIMESTAMPTZ,
    CONSTRAINT fk_notification_user
        FOREIGN KEY (brokerage_id, user_id)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT fk_notification_unit
        FOREIGN KEY (brokerage_id, unit_id)
        REFERENCES property_unit (brokerage_id, id),
    CONSTRAINT fk_notification_listing
        FOREIGN KEY (brokerage_id, listing_id)
        REFERENCES property_listing (brokerage_id, id),
    CONSTRAINT fk_notification_demand
        FOREIGN KEY (brokerage_id, demand_id)
        REFERENCES property_requirement (brokerage_id, id),
    CONSTRAINT fk_notification_schedule
        FOREIGN KEY (brokerage_id, schedule_event_id)
        REFERENCES business_schedule_event (brokerage_id, id),
    CONSTRAINT fk_notification_contract
        FOREIGN KEY (brokerage_id, contract_id)
        REFERENCES property_contract (brokerage_id, id),
    CONSTRAINT uq_notification_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE INDEX idx_notification_unread
    ON notification (brokerage_id, user_id, created_at DESC)
    WHERE read_at IS NULL
      AND dismissed_at IS NULL;

CREATE INDEX idx_notification_due
    ON notification (brokerage_id, due_at)
    WHERE due_at IS NOT NULL
      AND dismissed_at IS NULL;

-- ============================================================================
-- 13. CHANGE HISTORY / ACCESS AUDIT
-- ============================================================================

CREATE TABLE change_history (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id        BIGINT NOT NULL,
    entity_type         VARCHAR(40) NOT NULL,
    entity_id           BIGINT NOT NULL,
    action              VARCHAR(20) NOT NULL,
    changes             JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_type         VARCHAR(10) NOT NULL DEFAULT 'HUMAN',
    batch_id            UUID,
    request_id          UUID,
    changed_by          BIGINT,
    changed_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_change_history_brokerage
        FOREIGN KEY (brokerage_id)
        REFERENCES brokerage(id),
    CONSTRAINT fk_change_history_changed_by
        FOREIGN KEY (brokerage_id, changed_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_change_history_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE INDEX idx_change_history_entity
    ON change_history (
        brokerage_id,
        entity_type,
        entity_id,
        changed_at DESC
    );

CREATE INDEX idx_change_history_batch
    ON change_history (brokerage_id, batch_id, changed_at)
    WHERE batch_id IS NOT NULL;


CREATE TABLE access_audit_log (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id        BIGINT NOT NULL,
    user_id             BIGINT,
    actor_source        VARCHAR(10) NOT NULL DEFAULT 'HUMAN',
    action              VARCHAR(40) NOT NULL,
    entity_type         VARCHAR(40),
    entity_id           BIGINT,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_access_audit_brokerage
        FOREIGN KEY (brokerage_id)
        REFERENCES brokerage(id),
    CONSTRAINT fk_access_audit_user
        FOREIGN KEY (brokerage_id, user_id)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_access_audit_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE INDEX idx_access_audit_date
    ON access_audit_log (brokerage_id, occurred_at DESC);

CREATE INDEX idx_access_audit_user
    ON access_audit_log (brokerage_id, user_id, occurred_at DESC);

CREATE INDEX idx_access_audit_ai
    ON access_audit_log (brokerage_id, actor_source, occurred_at DESC)
    WHERE actor_source IN ('F2', 'F3');


-- ============================================================================
-- 14. LEGACY DATA MIGRATION TRACKING
-- ============================================================================

CREATE TABLE migration_batch (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id        BIGINT NOT NULL,
    ledger_type         VARCHAR(20) NOT NULL,
    status              VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    baseline_row_count  INTEGER,
    loaded_row_count    INTEGER NOT NULL DEFAULT 0,
    failed_row_count    INTEGER NOT NULL DEFAULT 0,
    reviewed_row_count  INTEGER NOT NULL DEFAULT 0,
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    created_by          BIGINT NOT NULL,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_migration_batch_brokerage
        FOREIGN KEY (brokerage_id)
        REFERENCES brokerage(id),
    CONSTRAINT fk_migration_batch_created_by
        FOREIGN KEY (brokerage_id, created_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_migration_batch_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE TABLE migration_source (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id        BIGINT NOT NULL,
    migration_batch_id  BIGINT NOT NULL,
    source_type         VARCHAR(20) NOT NULL,
    document_id         BIGINT,
    source_raw_text            TEXT,
    capture_metadata    JSONB NOT NULL DEFAULT '{}'::jsonb,
    checksum_sha256     VARCHAR(64),
    source_order        INTEGER NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_migration_source_batch
        FOREIGN KEY (brokerage_id, migration_batch_id)
        REFERENCES migration_batch (brokerage_id, id),
    CONSTRAINT fk_migration_source_document
        FOREIGN KEY (brokerage_id, document_id)
        REFERENCES stored_document (brokerage_id, id),
    CONSTRAINT uq_migration_source_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE TABLE migration_row_processing_result (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id        BIGINT NOT NULL,
    migration_source_id BIGINT NOT NULL,
    source_row_key      VARCHAR(200),
    source_row_data           JSONB NOT NULL DEFAULT '{}'::jsonb,
    parsed_row_data        JSONB NOT NULL DEFAULT '{}'::jsonb,
    status              VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    error_code          VARCHAR(80),
    error_message       TEXT,
    unit_id             BIGINT,
    listing_id          BIGINT,
    demand_id           BIGINT,
    reviewed_by         BIGINT,
    reviewed_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_migration_row_source
        FOREIGN KEY (brokerage_id, migration_source_id)
        REFERENCES migration_source (brokerage_id, id),
    CONSTRAINT fk_migration_row_unit
        FOREIGN KEY (brokerage_id, unit_id)
        REFERENCES property_unit (brokerage_id, id),
    CONSTRAINT fk_migration_row_listing
        FOREIGN KEY (brokerage_id, listing_id)
        REFERENCES property_listing (brokerage_id, id),
    CONSTRAINT fk_migration_row_demand
        FOREIGN KEY (brokerage_id, demand_id)
        REFERENCES property_requirement (brokerage_id, id),
    CONSTRAINT fk_migration_row_reviewed_by
        FOREIGN KEY (brokerage_id, reviewed_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_migration_row_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE INDEX idx_migration_row_status
    ON migration_row_processing_result (brokerage_id, migration_source_id, status);

CREATE TABLE migration_progress (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id        BIGINT NOT NULL,
    migration_batch_id  BIGINT NOT NULL,
    complex_id          BIGINT,
    building_number         VARCHAR(50),
    status              VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    expected_count      INTEGER,
    loaded_count        INTEGER NOT NULL DEFAULT 0,
    failed_count        INTEGER NOT NULL DEFAULT 0,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_migration_progress_batch
        FOREIGN KEY (brokerage_id, migration_batch_id)
        REFERENCES migration_batch (brokerage_id, id),
    CONSTRAINT fk_migration_progress_complex
        FOREIGN KEY (brokerage_id, complex_id)
        REFERENCES property_complex (brokerage_id, id),
    CONSTRAINT uq_migration_progress_scope
        UNIQUE (brokerage_id, migration_batch_id, complex_id, building_number),
    CONSTRAINT uq_migration_progress_tenant_id
        UNIQUE (brokerage_id, id)
);

-- ============================================================================
-- 15. F2 STT JOB / FIELD PROPOSAL
-- ============================================================================

CREATE TABLE consultation_transcription_job (
    id                          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id                BIGINT NOT NULL,
    request_id                  UUID NOT NULL DEFAULT gen_random_uuid(),
    ledger_draft_id             BIGINT NOT NULL,
    input_mode                  VARCHAR(20) NOT NULL,
    source_audio_document_id    BIGINT,
    status                      VARCHAR(30) NOT NULL DEFAULT 'DRAFT',
    transcription_model_config_id         BIGINT,
    analysis_model_config_id    BIGINT,
    transcribed_text                    TEXT,
    consultation_type           VARCHAR(30),
    ledger_match_result                VARCHAR(20) NOT NULL DEFAULT 'UNKNOWN',
    analysis_summary            JSONB NOT NULL DEFAULT '{}'::jsonb,
    retry_count                 INTEGER NOT NULL DEFAULT 0,
    failed_stage               VARCHAR(40),
    failure_code                VARCHAR(80),
    failure_message             TEXT,
    started_at                  TIMESTAMPTZ,
    transcribed_at              TIMESTAMPTZ,
    analyzed_at                 TIMESTAMPTZ,
    approved_by                 BIGINT,
    approved_at                 TIMESTAMPTZ,
    ledger_saved_at                    TIMESTAMPTZ,
    retention_until             TIMESTAMPTZ,
    purged_at                   TIMESTAMPTZ,
    created_by                  BIGINT NOT NULL,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_f2_stt_job_draft
        FOREIGN KEY (brokerage_id, ledger_draft_id)
        REFERENCES ledger_draft (brokerage_id, id),
    CONSTRAINT fk_f2_stt_job_audio_document
        FOREIGN KEY (brokerage_id, source_audio_document_id)
        REFERENCES stored_document (brokerage_id, id),
    CONSTRAINT fk_f2_stt_job_stt_model
        FOREIGN KEY (brokerage_id, transcription_model_config_id)
        REFERENCES ai_model_config (brokerage_id, id),
    CONSTRAINT fk_f2_stt_job_analysis_model
        FOREIGN KEY (brokerage_id, analysis_model_config_id)
        REFERENCES ai_model_config (brokerage_id, id),
    CONSTRAINT fk_f2_stt_job_approved_by
        FOREIGN KEY (brokerage_id, approved_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT fk_f2_stt_job_created_by
        FOREIGN KEY (brokerage_id, created_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_f2_stt_job_request
        UNIQUE (brokerage_id, request_id),
    CONSTRAINT uq_f2_stt_job_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE INDEX idx_f2_stt_job_status
    ON consultation_transcription_job (brokerage_id, status, created_at DESC);

CREATE INDEX idx_f2_stt_job_draft
    ON consultation_transcription_job (brokerage_id, ledger_draft_id, created_at DESC);

CREATE TABLE transcription_field_proposal (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id        BIGINT NOT NULL,
    transcription_job_id       BIGINT NOT NULL,
    target_entity       VARCHAR(30) NOT NULL,
    field_name          VARCHAR(120) NOT NULL,
    current_value       JSONB,
    proposed_value      JSONB,
    final_value         JSONB,
    proposal_status     VARCHAR(20) NOT NULL,
    confidence          NUMERIC(6,5),
    evidence_text       TEXT,
    is_selected         BOOLEAN NOT NULL DEFAULT FALSE,
    applied_by          BIGINT,
    applied_at          TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_f2_field_proposal_job
        FOREIGN KEY (brokerage_id, transcription_job_id)
        REFERENCES consultation_transcription_job (brokerage_id, id),
    CONSTRAINT fk_f2_field_proposal_applied_by
        FOREIGN KEY (brokerage_id, applied_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_f2_field_proposal
        UNIQUE (brokerage_id, transcription_job_id, target_entity, field_name),
    CONSTRAINT uq_f2_field_proposal_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE INDEX idx_f2_field_proposal_job
    ON transcription_field_proposal (
        brokerage_id,
        transcription_job_id,
        proposal_status
    );

CREATE TABLE interaction_log_proposal (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id            BIGINT NOT NULL,
    transcription_job_id           BIGINT NOT NULL,
    draft_interaction_content              TEXT NOT NULL,
    final_interaction_content              TEXT,
    proposal_status         VARCHAR(20) NOT NULL DEFAULT 'NEEDS_REVIEW',
    is_selected             BOOLEAN NOT NULL DEFAULT TRUE,
    final_client_interaction_id    BIGINT,
    approved_by             BIGINT,
    approved_at             TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_f2_log_proposal_job
        FOREIGN KEY (brokerage_id, transcription_job_id)
        REFERENCES consultation_transcription_job (brokerage_id, id),
    CONSTRAINT fk_f2_log_proposal_interaction
        FOREIGN KEY (brokerage_id, final_client_interaction_id)
        REFERENCES client_interaction (brokerage_id, id),
    CONSTRAINT fk_f2_log_proposal_approved_by
        FOREIGN KEY (brokerage_id, approved_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_f2_log_proposal_job
        UNIQUE (brokerage_id, transcription_job_id),
    CONSTRAINT uq_f2_log_proposal_tenant_id
        UNIQUE (brokerage_id, id)
);

-- ============================================================================
-- 16. F3 AGENT RUN / TOOL CALL
-- ============================================================================

CREATE TABLE f3_agent_run (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id            BIGINT NOT NULL,
    parent_run_id           BIGINT,
    run_type                VARCHAR(30) NOT NULL,
    agent_type              VARCHAR(30) NOT NULL,
    status                  VARCHAR(20) NOT NULL DEFAULT 'QUEUED',
    trigger_type            VARCHAR(50) NOT NULL,
    model_config_id         BIGINT,
    requested_by            BIGINT NOT NULL,
    target_unit_id          BIGINT,
    target_listing_id       BIGINT,
    target_demand_id        BIGINT,
    data_version            BIGINT NOT NULL DEFAULT 1,
    last_log_at             TIMESTAMPTZ,
    input_snapshot          JSONB NOT NULL DEFAULT '{}'::jsonb,
    output_snapshot         JSONB NOT NULL DEFAULT '{}'::jsonb,
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
    CONSTRAINT fk_f3_agent_run_brokerage
        FOREIGN KEY (brokerage_id)
        REFERENCES brokerage(id),
    CONSTRAINT fk_f3_agent_run_parent
        FOREIGN KEY (brokerage_id, parent_run_id)
        REFERENCES f3_agent_run (brokerage_id, id),
    CONSTRAINT fk_f3_agent_run_model
        FOREIGN KEY (brokerage_id, model_config_id)
        REFERENCES ai_model_config (brokerage_id, id),
    CONSTRAINT fk_f3_agent_run_requested_by
        FOREIGN KEY (brokerage_id, requested_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT fk_f3_agent_run_unit
        FOREIGN KEY (brokerage_id, target_unit_id)
        REFERENCES property_unit (brokerage_id, id),
    CONSTRAINT fk_f3_agent_run_listing
        FOREIGN KEY (brokerage_id, target_listing_id)
        REFERENCES property_listing (brokerage_id, id),
    CONSTRAINT fk_f3_agent_run_demand
        FOREIGN KEY (brokerage_id, target_demand_id)
        REFERENCES property_requirement (brokerage_id, id),
    CONSTRAINT uq_f3_agent_run_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE INDEX idx_f3_agent_run_status
    ON f3_agent_run (brokerage_id, status, created_at DESC);

CREATE INDEX idx_f3_agent_run_target_unit
    ON f3_agent_run (brokerage_id, target_unit_id, created_at DESC)
    WHERE target_unit_id IS NOT NULL;

CREATE INDEX idx_f3_agent_run_target_demand
    ON f3_agent_run (brokerage_id, target_demand_id, created_at DESC)
    WHERE target_demand_id IS NOT NULL;

CREATE TABLE f3_tool_call (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id        BIGINT NOT NULL,
    agent_run_id        BIGINT NOT NULL,
    tool_name           VARCHAR(100) NOT NULL,
    status              VARCHAR(20) NOT NULL DEFAULT 'RUNNING',
    request_payload     JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_payload    JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at        TIMESTAMPTZ,
    latency_ms          INTEGER,
    failure_message     TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_f3_tool_call_run
        FOREIGN KEY (brokerage_id, agent_run_id)
        REFERENCES f3_agent_run (brokerage_id, id),
    CONSTRAINT uq_f3_tool_call_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE INDEX idx_f3_tool_call_run
    ON f3_tool_call (brokerage_id, agent_run_id, started_at);


-- ============================================================================
-- 17. F3 POSITION CARD / EVIDENCE / CORRECTION
-- ============================================================================

CREATE TABLE negotiation_position_analysis (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id            BIGINT NOT NULL,
    agent_run_id            BIGINT NOT NULL,
    negotiation_side             VARCHAR(20) NOT NULL,
    unit_id                 BIGINT,
    listing_id              BIGINT,
    demand_id               BIGINT,
    target_label            VARCHAR(200),
    cache_key               VARCHAR(500) NOT NULL,
    source_log_count        INTEGER NOT NULL DEFAULT 0,
    last_log_at             TIMESTAMPTZ,
    data_version            BIGINT NOT NULL,
    negotiation_intent                  VARCHAR(20) NOT NULL DEFAULT 'UNKNOWN',
    stated_price_amount            BIGINT,
    estimated_price_amount         BIGINT,
    price_estimation_basis             TEXT,
    urgency                 VARCHAR(20) NOT NULL DEFAULT 'UNKNOWN',
    preferred_timing                  JSONB NOT NULL DEFAULT '{}'::jsonb,
    flexible_conditions     JSONB NOT NULL DEFAULT '[]'::jsonb,
    inflexible_conditions   JSONB NOT NULL DEFAULT '[]'::jsonb,
    contact_availability          VARCHAR(20) NOT NULL DEFAULT 'CAUTION',
    contactability_note     TEXT,
    analysis_snapshot           JSONB NOT NULL DEFAULT '{}'::jsonb,
    generated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    invalidated_at          TIMESTAMPTZ,
    invalidation_reason     TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_f3_position_card_run
        FOREIGN KEY (brokerage_id, agent_run_id)
        REFERENCES f3_agent_run (brokerage_id, id),
    CONSTRAINT fk_f3_position_card_unit
        FOREIGN KEY (brokerage_id, unit_id)
        REFERENCES property_unit (brokerage_id, id),
    CONSTRAINT fk_f3_position_card_listing
        FOREIGN KEY (brokerage_id, listing_id)
        REFERENCES property_listing (brokerage_id, id),
    CONSTRAINT fk_f3_position_card_demand
        FOREIGN KEY (brokerage_id, demand_id)
        REFERENCES property_requirement (brokerage_id, id),
    CONSTRAINT uq_f3_position_card_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE UNIQUE INDEX uq_f3_position_card_active_cache_key
    ON negotiation_position_analysis (brokerage_id, cache_key)
    WHERE invalidated_at IS NULL;

CREATE INDEX idx_f3_position_card_listing_target
    ON negotiation_position_analysis (brokerage_id, unit_id, generated_at DESC)
    WHERE negotiation_side = 'LISTING';

CREATE INDEX idx_f3_position_card_customer_target
    ON negotiation_position_analysis (brokerage_id, demand_id, generated_at DESC)
    WHERE negotiation_side = 'CUSTOMER';

CREATE INDEX idx_f3_position_card_active
    ON negotiation_position_analysis (brokerage_id, negotiation_side, generated_at DESC)
    WHERE invalidated_at IS NULL;


CREATE TABLE negotiation_position_evidence (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id        BIGINT NOT NULL,
    position_analysis_id    BIGINT NOT NULL,
    field_name          VARCHAR(100) NOT NULL,
    evidence_type       VARCHAR(20) NOT NULL,
    interaction_id      BIGINT,
    quote_text          TEXT,
    note                TEXT,
    display_order       INTEGER NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_f3_card_evidence_card
        FOREIGN KEY (brokerage_id, position_analysis_id)
        REFERENCES negotiation_position_analysis (brokerage_id, id),
    CONSTRAINT fk_f3_card_evidence_interaction
        FOREIGN KEY (brokerage_id, interaction_id)
        REFERENCES client_interaction (brokerage_id, id),
    CONSTRAINT uq_f3_card_evidence_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE INDEX idx_f3_card_evidence_card
    ON negotiation_position_evidence (brokerage_id, position_card_id, display_order);


CREATE TABLE negotiation_position_correction (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id            BIGINT NOT NULL,
    position_analysis_id        BIGINT NOT NULL,
    field_name              VARCHAR(100) NOT NULL,
    original_value          JSONB,
    corrected_value         JSONB NOT NULL,
    correction_reason       TEXT,
    corrected_by            BIGINT NOT NULL,
    correction_interaction_id BIGINT NOT NULL,
    corrected_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_f3_card_correction_card
        FOREIGN KEY (brokerage_id, position_analysis_id)
        REFERENCES negotiation_position_analysis (brokerage_id, id),
    CONSTRAINT fk_f3_card_correction_user
        FOREIGN KEY (brokerage_id, corrected_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT fk_f3_card_correction_interaction
        FOREIGN KEY (brokerage_id, correction_interaction_id)
        REFERENCES client_interaction (brokerage_id, id),
    CONSTRAINT uq_f3_card_correction_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE INDEX idx_f3_card_correction_card
    ON negotiation_position_correction (brokerage_id, position_card_id, corrected_at DESC);


-- ============================================================================
-- 18. F3 CROSS JUDGMENT / CANDIDATES / FEEDBACK LOOP
-- ============================================================================

CREATE TABLE match_evaluation (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id        BIGINT NOT NULL,
    agent_run_id        BIGINT NOT NULL,
    anchor_position_analysis_id      BIGINT NOT NULL,
    candidate_count     INTEGER NOT NULL DEFAULT 0,
    data_version        BIGINT NOT NULL,
    generated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_f3_cross_judgment_run
        FOREIGN KEY (brokerage_id, agent_run_id)
        REFERENCES f3_agent_run (brokerage_id, id),
    CONSTRAINT fk_f3_cross_judgment_anchor
        FOREIGN KEY (brokerage_id, anchor_position_analysis_id)
        REFERENCES negotiation_position_analysis (brokerage_id, id),
    CONSTRAINT uq_f3_cross_judgment_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE INDEX idx_f3_cross_judgment_anchor
    ON match_evaluation (
        brokerage_id,
        anchor_position_analysis_id,
        generated_at DESC
    );


CREATE TABLE match_candidate_evaluation (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id            BIGINT NOT NULL,
    match_evaluation_id       BIGINT NOT NULL,
    candidate_position_analysis_id       BIGINT NOT NULL,
    match_grade                   VARCHAR(20) NOT NULL,
    match_rank              INTEGER NOT NULL,
    evaluation_basis        TEXT NOT NULL,
    primary_obstacle       TEXT,
    possible_concession        TEXT,
    recommended_action             JSONB NOT NULL DEFAULT '{}'::jsonb,
    proposed_schedule       JSONB NOT NULL DEFAULT '{}'::jsonb,
    exclusion_reason        TEXT,
    schedule_event_id       BIGINT,
    message_delivery_id         BIGINT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_f3_judgment_candidate_judgment
        FOREIGN KEY (brokerage_id, match_evaluation_id)
        REFERENCES match_evaluation (brokerage_id, id),
    CONSTRAINT fk_f3_judgment_candidate_card
        FOREIGN KEY (brokerage_id, candidate_position_analysis_id)
        REFERENCES negotiation_position_analysis (brokerage_id, id),
    CONSTRAINT fk_f3_judgment_candidate_schedule
        FOREIGN KEY (brokerage_id, schedule_event_id)
        REFERENCES business_schedule_event (brokerage_id, id),
    CONSTRAINT fk_f3_judgment_candidate_message
        FOREIGN KEY (brokerage_id, message_delivery_id)
        REFERENCES message_delivery (brokerage_id, id),
    CONSTRAINT uq_f3_judgment_candidate
        UNIQUE (brokerage_id, match_evaluation_id, candidate_position_analysis_id),
    CONSTRAINT uq_f3_judgment_candidate_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE INDEX idx_f3_judgment_candidate_rank
    ON match_candidate_evaluation (
        brokerage_id,
        match_evaluation_id,
        match_rank
    );

CREATE INDEX idx_f3_judgment_candidate_grade
    ON match_candidate_evaluation (brokerage_id, match_evaluation_id, match_grade, match_rank);


CREATE TABLE match_candidate_evidence (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id            BIGINT NOT NULL,
    match_candidate_evaluation_id   BIGINT NOT NULL,
    evidence_side           VARCHAR(20) NOT NULL,
    field_name              VARCHAR(100),
    evidence_type           VARCHAR(20) NOT NULL,
    interaction_id          BIGINT,
    quote_text              TEXT,
    note                    TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_f3_judgment_evidence_candidate
        FOREIGN KEY (brokerage_id, match_candidate_evaluation_id)
        REFERENCES match_candidate_evaluation (brokerage_id, id),
    CONSTRAINT fk_f3_judgment_evidence_interaction
        FOREIGN KEY (brokerage_id, interaction_id)
        REFERENCES client_interaction (brokerage_id, id),
    CONSTRAINT uq_f3_judgment_evidence_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE TABLE match_pair_exclusion (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id        BIGINT NOT NULL,
    unit_id             BIGINT NOT NULL,
    listing_id          BIGINT,
    demand_id           BIGINT NOT NULL,
    rejection_occurrence_count     INTEGER NOT NULL DEFAULT 0,
    is_excluded         BOOLEAN NOT NULL DEFAULT FALSE,
    exclusion_reason    TEXT,
    excluded_by         BIGINT,
    excluded_at         TIMESTAMPTZ,
    exclusion_released_by         BIGINT,
    exclusion_released_at         TIMESTAMPTZ,
    row_version         BIGINT NOT NULL DEFAULT 1,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_f3_pair_exclusion_unit
        FOREIGN KEY (brokerage_id, unit_id)
        REFERENCES property_unit (brokerage_id, id),
    CONSTRAINT fk_f3_pair_exclusion_listing
        FOREIGN KEY (brokerage_id, listing_id)
        REFERENCES property_listing (brokerage_id, id),
    CONSTRAINT fk_f3_pair_exclusion_demand
        FOREIGN KEY (brokerage_id, demand_id)
        REFERENCES property_requirement (brokerage_id, id),
    CONSTRAINT fk_f3_pair_exclusion_excluded_by
        FOREIGN KEY (brokerage_id, excluded_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT fk_f3_pair_exclusion_released_by
        FOREIGN KEY (brokerage_id, exclusion_released_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_f3_pair_exclusion_pair
        UNIQUE (brokerage_id, unit_id, demand_id),
    CONSTRAINT uq_f3_pair_exclusion_tenant_id
        UNIQUE (brokerage_id, id)
);

-- ============================================================================
-- 19. F3 CAMPAIGN / SEGMENT / TARGET
-- ============================================================================

CREATE TABLE f3_campaign (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id            BIGINT NOT NULL,
    name                    VARCHAR(200) NOT NULL,
    target_side             VARCHAR(20) NOT NULL,
    selection_method        VARCHAR(30) NOT NULL,
    natural_language_query  TEXT,
    condition_spec          JSONB NOT NULL DEFAULT '{}'::jsonb,
    status                  VARCHAR(30) NOT NULL DEFAULT 'DRAFT',
    max_target_count        INTEGER NOT NULL DEFAULT 200,
    selected_count          INTEGER NOT NULL DEFAULT 0,
    analyzed_count          INTEGER NOT NULL DEFAULT 0,
    excluded_count          INTEGER NOT NULL DEFAULT 0,
    created_by              BIGINT NOT NULL,
    approved_by             BIGINT,
    approved_at             TIMESTAMPTZ,
    executed_at             TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_f3_campaign_brokerage
        FOREIGN KEY (brokerage_id)
        REFERENCES brokerage(id),
    CONSTRAINT fk_f3_campaign_created_by
        FOREIGN KEY (brokerage_id, created_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT fk_f3_campaign_approved_by
        FOREIGN KEY (brokerage_id, approved_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_f3_campaign_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE INDEX idx_f3_campaign_status
    ON f3_campaign (brokerage_id, status, created_at DESC);

CREATE TABLE f3_campaign_segment (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id        BIGINT NOT NULL,
    campaign_id         BIGINT NOT NULL,
    segment_code        VARCHAR(80) NOT NULL,
    name                VARCHAR(160) NOT NULL,
    description         TEXT,
    is_excluded         BOOLEAN NOT NULL DEFAULT FALSE,
    exclusion_reason    TEXT,
    target_count        INTEGER NOT NULL DEFAULT 0,
    message_body        TEXT,
    message_generation_run_id BIGINT,
    message_delivery_id     BIGINT,
    display_order       INTEGER NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_f3_campaign_segment_campaign
        FOREIGN KEY (brokerage_id, campaign_id)
        REFERENCES f3_campaign (brokerage_id, id),
    CONSTRAINT fk_f3_campaign_segment_generation_run
        FOREIGN KEY (brokerage_id, message_generation_run_id)
        REFERENCES f3_agent_run (brokerage_id, id),
    CONSTRAINT fk_f3_campaign_segment_message
        FOREIGN KEY (brokerage_id, message_delivery_id)
        REFERENCES message_delivery (brokerage_id, id),
    CONSTRAINT uq_f3_campaign_segment_code
        UNIQUE (brokerage_id, campaign_id, segment_code),
    CONSTRAINT uq_f3_campaign_segment_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE TABLE f3_campaign_target (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id            BIGINT NOT NULL,
    campaign_id             BIGINT NOT NULL,
    unit_id                 BIGINT,
    listing_id              BIGINT,
    demand_id               BIGINT,
    party_id                BIGINT,
    party_contact_id        BIGINT,
    agent_run_id            BIGINT,
    position_analysis_id        BIGINT,
    segment_id              BIGINT,
    status                  VARCHAR(20) NOT NULL DEFAULT 'SELECTED',
    preliminary_evaluation        JSONB NOT NULL DEFAULT '{}'::jsonb,
    exclusion_reason        TEXT,
    last_contact_at_snapshot TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_f3_campaign_target_campaign
        FOREIGN KEY (brokerage_id, campaign_id)
        REFERENCES f3_campaign (brokerage_id, id),
    CONSTRAINT fk_f3_campaign_target_unit
        FOREIGN KEY (brokerage_id, unit_id)
        REFERENCES property_unit (brokerage_id, id),
    CONSTRAINT fk_f3_campaign_target_listing
        FOREIGN KEY (brokerage_id, listing_id)
        REFERENCES property_listing (brokerage_id, id),
    CONSTRAINT fk_f3_campaign_target_demand
        FOREIGN KEY (brokerage_id, demand_id)
        REFERENCES property_requirement (brokerage_id, id),
    CONSTRAINT fk_f3_campaign_target_party
        FOREIGN KEY (brokerage_id, party_id)
        REFERENCES party (brokerage_id, id),
    CONSTRAINT fk_f3_campaign_target_contact
        FOREIGN KEY (brokerage_id, party_contact_id)
        REFERENCES party_contact (brokerage_id, id),
    CONSTRAINT fk_f3_campaign_target_run
        FOREIGN KEY (brokerage_id, agent_run_id)
        REFERENCES f3_agent_run (brokerage_id, id),
    CONSTRAINT fk_f3_campaign_target_card
        FOREIGN KEY (brokerage_id, position_analysis_id)
        REFERENCES negotiation_position_analysis (brokerage_id, id),
    CONSTRAINT fk_f3_campaign_target_segment
        FOREIGN KEY (brokerage_id, segment_id)
        REFERENCES f3_campaign_segment (brokerage_id, id),
    CONSTRAINT uq_f3_campaign_target_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE UNIQUE INDEX uq_f3_campaign_target_subject
    ON f3_campaign_target (
        brokerage_id,
        campaign_id,
        COALESCE(unit_id, 0),
        COALESCE(demand_id, 0)
    );

CREATE INDEX idx_f3_campaign_target_segment
    ON f3_campaign_target (brokerage_id, campaign_id, segment_id, status);

CREATE TABLE f3_campaign_target_evidence (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id        BIGINT NOT NULL,
    campaign_target_id  BIGINT NOT NULL,
    evidence_type       VARCHAR(20) NOT NULL,
    interaction_id      BIGINT,
    quote_text          TEXT,
    note                TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_f3_campaign_evidence_target
        FOREIGN KEY (brokerage_id, campaign_target_id)
        REFERENCES f3_campaign_target (brokerage_id, id),
    CONSTRAINT fk_f3_campaign_evidence_interaction
        FOREIGN KEY (brokerage_id, interaction_id)
        REFERENCES client_interaction (brokerage_id, id),
    CONSTRAINT uq_f3_campaign_evidence_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE TABLE f3_feedback (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id            BIGINT NOT NULL,
    position_analysis_id        BIGINT,
    match_candidate_evaluation_id   BIGINT,
    campaign_target_id      BIGINT,
    reason                  VARCHAR(30) NOT NULL,
    detail                  TEXT,
    created_by              BIGINT NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_f3_feedback_card
        FOREIGN KEY (brokerage_id, position_analysis_id)
        REFERENCES negotiation_position_analysis (brokerage_id, id),
    CONSTRAINT fk_f3_feedback_candidate
        FOREIGN KEY (brokerage_id, match_candidate_evaluation_id)
        REFERENCES match_candidate_evaluation (brokerage_id, id),
    CONSTRAINT fk_f3_feedback_campaign_target
        FOREIGN KEY (brokerage_id, campaign_target_id)
        REFERENCES f3_campaign_target (brokerage_id, id),
    CONSTRAINT fk_f3_feedback_created_by
        FOREIGN KEY (brokerage_id, created_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_f3_feedback_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE INDEX idx_f3_feedback_reason
    ON f3_feedback (brokerage_id, reason, created_at DESC);


-- ============================================================================
-- TABLE / COLUMN COMMENTS
-- ============================================================================
COMMENT ON TABLE brokerage IS '서비스를 사용하는 중개사무소. F1·F2·F3 전체 데이터의 최상위 tenant.';
COMMENT ON COLUMN brokerage.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN brokerage.name IS '표시 이름 또는 명칭.';
COMMENT ON COLUMN brokerage.business_registration_number IS '중개사무소 사업자등록번호.';
COMMENT ON COLUMN brokerage.phone IS '중개사무소 대표 연락처.';
COMMENT ON COLUMN brokerage.address IS '중개사무소 주소.';
COMMENT ON COLUMN brokerage.settings IS '사무소 설정 JSON.';
COMMENT ON COLUMN brokerage.status IS '현재 상태 값. 상태 전이는 서버에서 관리한다.';
COMMENT ON COLUMN brokerage.row_version IS '낙관적 동시성 제어용 버전 값. 서버가 증가시킨다.';
COMMENT ON COLUMN brokerage.created_at IS '레코드 생성 시각.';
COMMENT ON COLUMN brokerage.updated_at IS '레코드 최종 수정 시각. 서버가 갱신한다.';

COMMENT ON TABLE app_user IS '개업공인중개사·직원·읽기전용 사용자를 관리한다. 계정은 삭제보다 비활성화를 사용한다.';
COMMENT ON COLUMN app_user.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN app_user.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN app_user.login_id IS '사용자 로그인 식별자.';
COMMENT ON COLUMN app_user.password_hash IS '비밀번호 해시 값.';
COMMENT ON COLUMN app_user.display_name IS '화면 표시 사용자명.';
COMMENT ON COLUMN app_user.role IS '사용자 역할 값.';
COMMENT ON COLUMN app_user.phone IS 'phone 값.';
COMMENT ON COLUMN app_user.ui_preferences IS '사용자 UI 설정 JSON.';
COMMENT ON COLUMN app_user.is_active IS '사용 가능 여부.';
COMMENT ON COLUMN app_user.last_login_at IS '마지막 로그인 시각.';
COMMENT ON COLUMN app_user.row_version IS '낙관적 동시성 제어용 버전 값. 서버가 증가시킨다.';
COMMENT ON COLUMN app_user.created_at IS '레코드 생성 시각.';
COMMENT ON COLUMN app_user.updated_at IS '레코드 최종 수정 시각. 서버가 갱신한다.';

COMMENT ON TABLE code_group IS '사무소가 관리하는 현상태·분류·연락처 마커·문서 유형 등 코드 그룹. F1-MD-06.';
COMMENT ON COLUMN code_group.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN code_group.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN code_group.code IS '사무소 내 코드 그룹 식별 코드.';
COMMENT ON COLUMN code_group.name IS '표시 이름 또는 명칭.';
COMMENT ON COLUMN code_group.description IS '설명.';
COMMENT ON COLUMN code_group.is_system_group IS '시스템 기본 코드 그룹 여부.';
COMMENT ON COLUMN code_group.is_active IS '사용 가능 여부.';
COMMENT ON COLUMN code_group.created_by IS '생성 사용자 식별자.';
COMMENT ON COLUMN code_group.row_version IS '낙관적 동시성 제어용 버전 값. 서버가 증가시킨다.';
COMMENT ON COLUMN code_group.created_at IS '레코드 생성 시각.';
COMMENT ON COLUMN code_group.updated_at IS '레코드 최종 수정 시각. 서버가 갱신한다.';

COMMENT ON TABLE code_value IS '코드 그룹별 실제 선택 값. 비활성화해도 과거 레코드의 참조는 보존한다.';
COMMENT ON COLUMN code_value.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN code_value.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN code_value.group_code IS '소속 코드 그룹 코드.';
COMMENT ON COLUMN code_value.code IS '코드 값 식별 코드.';
COMMENT ON COLUMN code_value.label IS '화면 표시 라벨.';
COMMENT ON COLUMN code_value.description IS '설명.';
COMMENT ON COLUMN code_value.display_order IS '화면 표시 순서.';
COMMENT ON COLUMN code_value.metadata IS '부가 메타데이터 JSON.';
COMMENT ON COLUMN code_value.is_active IS '사용 가능 여부.';
COMMENT ON COLUMN code_value.created_by IS '생성 사용자 식별자.';
COMMENT ON COLUMN code_value.row_version IS '낙관적 동시성 제어용 버전 값. 서버가 증가시킨다.';
COMMENT ON COLUMN code_value.created_at IS '레코드 생성 시각.';
COMMENT ON COLUMN code_value.updated_at IS '레코드 최종 수정 시각. 서버가 갱신한다.';

COMMENT ON TABLE ai_model_config IS 'F2 STT·슬롯필링과 F3 에이전트·임베딩 모델을 설정으로 교체하기 위한 메타데이터. 비밀키는 저장하지 않는다.';
COMMENT ON COLUMN ai_model_config.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN ai_model_config.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN ai_model_config.capability IS '모델이 담당하는 AI 기능 구분 값.';
COMMENT ON COLUMN ai_model_config.provider IS '모델 제공자 또는 서빙 환경.';
COMMENT ON COLUMN ai_model_config.model_name IS '모델 이름.';
COMMENT ON COLUMN ai_model_config.endpoint_alias IS '서버에서 참조할 엔드포인트 별칭.';
COMMENT ON COLUMN ai_model_config.parameters IS '모델 호출 파라미터 JSON.';
COMMENT ON COLUMN ai_model_config.embedding_dimension IS '임베딩 벡터 차원.';
COMMENT ON COLUMN ai_model_config.max_context_tokens IS '모델 최대 컨텍스트 토큰 수.';
COMMENT ON COLUMN ai_model_config.is_active IS '사용 가능 여부.';
COMMENT ON COLUMN ai_model_config.created_by IS '생성 사용자 식별자.';
COMMENT ON COLUMN ai_model_config.updated_by IS '레코드를 마지막으로 수정한 사용자 식별자.';
COMMENT ON COLUMN ai_model_config.row_version IS '낙관적 동시성 제어용 버전 값. 서버가 증가시킨다.';
COMMENT ON COLUMN ai_model_config.created_at IS '레코드 생성 시각.';
COMMENT ON COLUMN ai_model_config.updated_at IS '레코드 최종 수정 시각. 서버가 갱신한다.';

COMMENT ON TABLE property_complex IS '아파트 단지 또는 오피스텔·빌라·상가 등 관리 대상 건물 묶음. F1-MD-01~03.';
COMMENT ON COLUMN property_complex.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN property_complex.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN property_complex.property_type IS '부동산 유형.';
COMMENT ON COLUMN property_complex.name IS '표시 이름 또는 명칭.';
COMMENT ON COLUMN property_complex.road_address IS '도로명 주소.';
COMMENT ON COLUMN property_complex.jibun_address IS '지번 주소.';
COMMENT ON COLUMN property_complex.legal_dong_code IS '법정동 코드.';
COMMENT ON COLUMN property_complex.household_count IS '세대 수.';
COMMENT ON COLUMN property_complex.completion_year IS '준공 연도.';
COMMENT ON COLUMN property_complex.contacts IS '단지 관련 연락처 목록 JSON.';
COMMENT ON COLUMN property_complex.extra_info IS '단지 부가 정보 JSON.';
COMMENT ON COLUMN property_complex.memo IS '업무 메모.';
COMMENT ON COLUMN property_complex.is_deleted IS '소프트 삭제 여부.';
COMMENT ON COLUMN property_complex.deleted_at IS '소프트 삭제 처리 시각.';
COMMENT ON COLUMN property_complex.row_version IS '낙관적 동시성 제어용 버전 값. 서버가 증가시킨다.';
COMMENT ON COLUMN property_complex.created_at IS '레코드 생성 시각.';
COMMENT ON COLUMN property_complex.updated_at IS '레코드 최종 수정 시각. 서버가 갱신한다.';

COMMENT ON TABLE property_complex_unit_type IS '단지·타입별 평형, 전용면적, 공급면적 마스터. F1-MD-07.';
COMMENT ON COLUMN property_complex_unit_type.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN property_complex_unit_type.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN property_complex_unit_type.complex_id IS '소속 단지 식별자.';
COMMENT ON COLUMN property_complex_unit_type.type_code IS '단지 내 평형·타입 식별 코드.';
COMMENT ON COLUMN property_complex_unit_type.pyeong IS '평형 값.';
COMMENT ON COLUMN property_complex_unit_type.exclusive_area_sqm IS '전용면적 제곱미터.';
COMMENT ON COLUMN property_complex_unit_type.supply_area_sqm IS '공급면적 제곱미터.';
COMMENT ON COLUMN property_complex_unit_type.description IS '설명.';
COMMENT ON COLUMN property_complex_unit_type.is_active IS '사용 가능 여부.';
COMMENT ON COLUMN property_complex_unit_type.row_version IS '낙관적 동시성 제어용 버전 값. 서버가 증가시킨다.';
COMMENT ON COLUMN property_complex_unit_type.created_at IS '레코드 생성 시각.';
COMMENT ON COLUMN property_complex_unit_type.updated_at IS '레코드 최종 수정 시각. 서버가 갱신한다.';

COMMENT ON TABLE property_unit IS '매물 여부와 무관한 세대 전수 대장의 기준 행. lifecycle_status는 현 임대차 상태와 별개의 업무 상태다. F1-GR-01, F1-TR-01.';
COMMENT ON COLUMN property_unit.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN property_unit.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN property_unit.complex_id IS '소속 단지 식별자.';
COMMENT ON COLUMN property_unit.unit_type_id IS '단지 내 평형·타입 식별자.';
COMMENT ON COLUMN property_unit.building_number IS '동 번호.';
COMMENT ON COLUMN property_unit.unit_number IS '호 번호.';
COMMENT ON COLUMN property_unit.unit_usage_type IS '세대 사용 용도.';
COMMENT ON COLUMN property_unit.floor_number IS '층 표기.';
COMMENT ON COLUMN property_unit.orientation IS '세대 방향.';
COMMENT ON COLUMN property_unit.tenancy_status_group_code IS '현 임대차 상태 코드 그룹. 서버가 TENANCY_STATUS 값을 저장한다.';
COMMENT ON COLUMN property_unit.tenancy_status_code IS '현 임대차 상태 코드.';
COMMENT ON COLUMN property_unit.current_deposit_amount IS '현재 임대차 보증금.';
COMMENT ON COLUMN property_unit.current_monthly_rent_amount IS '현재 월 차임.';
COMMENT ON COLUMN property_unit.loan_amount IS '현재 융자 금액.';
COMMENT ON COLUMN property_unit.tenancy_expiry_date IS '현재 임대차 만기일.';
COMMENT ON COLUMN property_unit.tenancy_raw_text IS '현 임대차 원문 표기.';
COMMENT ON COLUMN property_unit.is_expanded IS '확장 여부.';
COMMENT ON COLUMN property_unit.built_in_features IS '붙박이·고정 옵션 원문.';
COMMENT ON COLUMN property_unit.facility_condition IS '시설 상태.';
COMMENT ON COLUMN property_unit.assigned_user_id IS '업무 담당 사용자 식별자.';
COMMENT ON COLUMN property_unit.memo IS '업무 메모.';
COMMENT ON COLUMN property_unit.custom_fields IS '사무소별 확장 필드 JSON.';
COMMENT ON COLUMN property_unit.display_color IS '사용자 지정 행 또는 셀 배경색 값.';
COMMENT ON COLUMN property_unit.last_contact_at IS '가장 최근 접촉 시각. 서버가 상담 로그 기준으로 갱신한다.';
COMMENT ON COLUMN property_unit.lifecycle_status IS '세대 업무 생명주기 상태 값.';
COMMENT ON COLUMN property_unit.row_version IS '낙관적 동시성 제어용 버전 값. 서버가 증가시킨다.';
COMMENT ON COLUMN property_unit.is_deleted IS '소프트 삭제 여부.';
COMMENT ON COLUMN property_unit.deleted_at IS '소프트 삭제 처리 시각.';
COMMENT ON COLUMN property_unit.created_at IS '레코드 생성 시각.';
COMMENT ON COLUMN property_unit.updated_at IS '레코드 최종 수정 시각. 서버가 갱신한다.';

COMMENT ON TABLE party IS '임대인·임차인·구입자·공동중개 업소를 통합 관리하는 참여자. 주민등록번호는 저장하지 않는다.';
COMMENT ON COLUMN party.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN party.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN party.party_type IS '인물 또는 조직 구분.';
COMMENT ON COLUMN party.name IS '표시 이름 또는 명칭.';
COMMENT ON COLUMN party.alternate_name IS '업무용 별칭.';
COMMENT ON COLUMN party.birth_date IS '생년월일.';
COMMENT ON COLUMN party.business_registration_number IS '조직 사업자등록번호.';
COMMENT ON COLUMN party.memo IS '업무 메모.';
COMMENT ON COLUMN party.merged_target_party_id IS '병합된 경우 최종 인물 식별자.';
COMMENT ON COLUMN party.is_deleted IS '소프트 삭제 여부.';
COMMENT ON COLUMN party.deleted_at IS '소프트 삭제 처리 시각.';
COMMENT ON COLUMN party.row_version IS '낙관적 동시성 제어용 버전 값. 서버가 증가시킨다.';
COMMENT ON COLUMN party.created_at IS '레코드 생성 시각.';
COMMENT ON COLUMN party.updated_at IS '레코드 최종 수정 시각. 서버가 갱신한다.';

COMMENT ON TABLE party_contact IS '인물별 복수 연락처·마커·수신거부를 연락처 단위로 관리한다. F1-UD-12~13, F1-MS-15.';
COMMENT ON COLUMN party_contact.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN party_contact.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN party_contact.party_id IS '연결된 인물 식별자.';
COMMENT ON COLUMN party_contact.contact_method IS '연락처 종류.';
COMMENT ON COLUMN party_contact.contact_value IS '사용자가 입력한 연락처 원문.';
COMMENT ON COLUMN party_contact.normalized_contact_value IS '검색·중복 확인용 정규화 연락처 값. 서버가 생성해 저장한다.';
COMMENT ON COLUMN party_contact.contact_label IS '연락처 표시 라벨.';
COMMENT ON COLUMN party_contact.marker_group_code IS '연락처 마커 코드 그룹. 서버가 CONTACT_MARKER 값을 저장한다.';
COMMENT ON COLUMN party_contact.marker_code IS '연락처 마커 코드.';
COMMENT ON COLUMN party_contact.display_order IS '화면 표시 순서.';
COMMENT ON COLUMN party_contact.is_primary IS '주 연락처 여부.';
COMMENT ON COLUMN party_contact.is_sms_opted_out IS '문자 수신 거부 여부.';
COMMENT ON COLUMN party_contact.sms_opted_out_at IS '문자 수신 거부 확인 시각.';
COMMENT ON COLUMN party_contact.sms_opt_out_reason IS '문자 수신 거부 사유.';
COMMENT ON COLUMN party_contact.is_deleted IS '소프트 삭제 여부.';
COMMENT ON COLUMN party_contact.deleted_at IS '소프트 삭제 처리 시각.';
COMMENT ON COLUMN party_contact.row_version IS '낙관적 동시성 제어용 버전 값. 서버가 증가시킨다.';
COMMENT ON COLUMN party_contact.created_at IS '레코드 생성 시각.';
COMMENT ON COLUMN party_contact.updated_at IS '레코드 최종 수정 시각. 서버가 갱신한다.';

COMMENT ON TABLE property_unit_party_relation IS '세대와 임대인·임차인 등의 시간 관계. role_index는 상담 로그 ①②③ 인물 인덱스의 기준이다.';
COMMENT ON COLUMN property_unit_party_relation.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN property_unit_party_relation.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN property_unit_party_relation.unit_id IS '연결된 세대 식별자.';
COMMENT ON COLUMN property_unit_party_relation.party_id IS '연결된 인물 식별자.';
COMMENT ON COLUMN property_unit_party_relation.role IS '세대에서 인물이 담당하는 관계 역할.';
COMMENT ON COLUMN property_unit_party_relation.role_index IS '같은 역할 인물의 업무상 순번.';
COMMENT ON COLUMN property_unit_party_relation.is_primary IS '해당 역할의 대표 인물 여부.';
COMMENT ON COLUMN property_unit_party_relation.is_co_owner IS '공동명의자 여부.';
COMMENT ON COLUMN property_unit_party_relation.valid_from IS '관계 시작일.';
COMMENT ON COLUMN property_unit_party_relation.valid_to IS '관계 종료일.';
COMMENT ON COLUMN property_unit_party_relation.memo IS '업무 메모.';
COMMENT ON COLUMN property_unit_party_relation.created_at IS '레코드 생성 시각.';

COMMENT ON TABLE party_merge_history IS '중복 인물 병합 시 양쪽 스냅샷과 수행자를 보존한다. F1-UD-22.';
COMMENT ON COLUMN party_merge_history.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN party_merge_history.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN party_merge_history.source_party_id IS '병합 전 원본 인물 식별자.';
COMMENT ON COLUMN party_merge_history.target_party_id IS '병합 대상 최종 인물 식별자.';
COMMENT ON COLUMN party_merge_history.source_snapshot IS '병합 당시 원본 인물 스냅샷.';
COMMENT ON COLUMN party_merge_history.target_snapshot IS '병합 당시 대상 인물 스냅샷.';
COMMENT ON COLUMN party_merge_history.merged_by IS '병합 수행 사용자 식별자.';
COMMENT ON COLUMN party_merge_history.merged_at IS '병합 수행 시각.';
COMMENT ON COLUMN party_merge_history.memo IS '업무 메모.';

COMMENT ON TABLE consent_event IS '개인정보 활용 동의·철회 이벤트. 현재 상태는 최신 이벤트로 계산한다.';
COMMENT ON COLUMN consent_event.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN consent_event.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN consent_event.party_id IS '연결된 인물 식별자.';
COMMENT ON COLUMN consent_event.event_type IS '개인정보 동의 또는 철회 이벤트 유형.';
COMMENT ON COLUMN consent_event.document_version IS '동의 문서 버전.';
COMMENT ON COLUMN consent_event.purpose IS '개인정보 이용 목적.';
COMMENT ON COLUMN consent_event.items IS '동의 대상 개인정보 항목.';
COMMENT ON COLUMN consent_event.retention_period IS '고지된 보유 기간.';
COMMENT ON COLUMN consent_event.source_type IS '데이터 생성 출처를 구분하는 값.';
COMMENT ON COLUMN consent_event.occurred_at IS '이벤트 또는 상담이 발생한 시각.';
COMMENT ON COLUMN consent_event.recorded_by IS '동의 이벤트 기록 사용자 식별자.';
COMMENT ON COLUMN consent_event.created_at IS '레코드 생성 시각.';

COMMENT ON TABLE property_listing IS '특정 세대가 시간에 따라 반복해서 매물화되는 개별 업무 건. 세대 원장과 분리한다.';
COMMENT ON COLUMN property_listing.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN property_listing.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN property_listing.unit_id IS '연결된 세대 식별자.';
COMMENT ON COLUMN property_listing.received_at IS '매물 접수일.';
COMMENT ON COLUMN property_listing.status IS '현재 상태 값. 상태 전이는 서버에서 관리한다.';
COMMENT ON COLUMN property_listing.handover_condition IS '명도 조건.';
COMMENT ON COLUMN property_listing.is_sale_available IS '매매 조건 사용 여부.';
COMMENT ON COLUMN property_listing.sale_price IS '매매 희망 가격.';
COMMENT ON COLUMN property_listing.is_jeonse_available IS '전세 조건 사용 여부.';
COMMENT ON COLUMN property_listing.jeonse_deposit_amount IS '전세 보증금.';
COMMENT ON COLUMN property_listing.is_monthly_rent_available IS '월세 조건 사용 여부.';
COMMENT ON COLUMN property_listing.monthly_rent_deposit_amount IS '월세 보증금.';
COMMENT ON COLUMN property_listing.monthly_rent_amount IS '월 차임.';
COMMENT ON COLUMN property_listing.price_raw_text IS '가격 조건 원문.';
COMMENT ON COLUMN property_listing.client_party_id IS '매물 의뢰인 식별자.';
COMMENT ON COLUMN property_listing.co_broker_party_id IS '공동중개 상대 업소 또는 인물 식별자.';
COMMENT ON COLUMN property_listing.assigned_user_id IS '업무 담당 사용자 식별자.';
COMMENT ON COLUMN property_listing.memo IS '업무 메모.';
COMMENT ON COLUMN property_listing.custom_fields IS '사무소별 확장 필드 JSON.';
COMMENT ON COLUMN property_listing.closed_at IS '매물 업무 종료일.';
COMMENT ON COLUMN property_listing.closed_price_amount IS '업무 종료 시 확인된 거래 가격.';
COMMENT ON COLUMN property_listing.row_version IS '낙관적 동시성 제어용 버전 값. 서버가 증가시킨다.';
COMMENT ON COLUMN property_listing.is_deleted IS '소프트 삭제 여부.';
COMMENT ON COLUMN property_listing.deleted_at IS '소프트 삭제 처리 시각.';
COMMENT ON COLUMN property_listing.created_at IS '레코드 생성 시각.';
COMMENT ON COLUMN property_listing.updated_at IS '레코드 최종 수정 시각. 서버가 갱신한다.';

COMMENT ON TABLE property_requirement IS '구입장 한 건. 완료 시 성사 세대 또는 연결 없이 종료한 사유와 완료 시각을 보존한다.';
COMMENT ON COLUMN property_requirement.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN property_requirement.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN property_requirement.party_id IS '연결된 인물 식별자.';
COMMENT ON COLUMN property_requirement.consent_grant_event_id IS '수요 등록 시 서버가 선택한 개인정보 동의 근거 이벤트 식별자.';
COMMENT ON COLUMN property_requirement.received_at IS '수요 접수일.';
COMMENT ON COLUMN property_requirement.demand_type IS '매수·매도·전세·월세 수요 유형.';
COMMENT ON COLUMN property_requirement.desired_pyeongs IS '희망 평형 목록.';
COMMENT ON COLUMN property_requirement.min_area_sqm IS '희망 최소 면적.';
COMMENT ON COLUMN property_requirement.max_area_sqm IS '희망 최대 면적.';
COMMENT ON COLUMN property_requirement.area_requirement_raw_text IS '희망 면적 원문.';
COMMENT ON COLUMN property_requirement.min_budget_amount IS '희망 예산 하한.';
COMMENT ON COLUMN property_requirement.max_budget_amount IS '희망 예산 상한.';
COMMENT ON COLUMN property_requirement.budget_raw_text IS '예산 원문.';
COMMENT ON COLUMN property_requirement.desired_move_in_date IS '희망 이사일.';
COMMENT ON COLUMN property_requirement.move_in_date_raw_text IS '희망 이사일 원문.';
COMMENT ON COLUMN property_requirement.request_expiry_date IS '현 거주지 만기일.';
COMMENT ON COLUMN property_requirement.workflow_stage IS '업무 진행 단계 자유 입력값.';
COMMENT ON COLUMN property_requirement.status IS '현재 상태 값. 상태 전이는 서버에서 관리한다.';
COMMENT ON COLUMN property_requirement.completed_at IS '수요 업무 완료 시각.';
COMMENT ON COLUMN property_requirement.matched_unit_id IS '성사된 세대 식별자.';
COMMENT ON COLUMN property_requirement.closure_reason IS '세대 연결 없이 완료한 경우 사유.';
COMMENT ON COLUMN property_requirement.co_broker_party_id IS '공동중개 상대 업소 또는 인물 식별자.';
COMMENT ON COLUMN property_requirement.assigned_user_id IS '업무 담당 사용자 식별자.';
COMMENT ON COLUMN property_requirement.classification_group_code IS '수요 분류 코드 그룹. 서버가 DEMAND_CLASSIFICATION 값을 저장한다.';
COMMENT ON COLUMN property_requirement.classification_code IS '수요 분류 코드.';
COMMENT ON COLUMN property_requirement.display_color IS '사용자 지정 배경색 값.';
COMMENT ON COLUMN property_requirement.memo IS '업무 메모.';
COMMENT ON COLUMN property_requirement.custom_fields IS '사무소별 확장 필드 JSON.';
COMMENT ON COLUMN property_requirement.last_contact_at IS '가장 최근 접촉 시각. 서버가 상담 로그 기준으로 갱신한다.';
COMMENT ON COLUMN property_requirement.row_version IS '낙관적 동시성 제어용 버전 값. 서버가 증가시킨다.';
COMMENT ON COLUMN property_requirement.is_deleted IS '소프트 삭제 여부.';
COMMENT ON COLUMN property_requirement.deleted_at IS '소프트 삭제 처리 시각.';
COMMENT ON COLUMN property_requirement.created_at IS '레코드 생성 시각.';
COMMENT ON COLUMN property_requirement.updated_at IS '레코드 최종 수정 시각. 서버가 갱신한다.';

COMMENT ON TABLE property_requirement_complex IS '구입장과 희망 단지의 실제 다대다 관계.';
COMMENT ON COLUMN property_requirement_complex.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN property_requirement_complex.demand_id IS '연결된 구입장 수요 건 식별자.';
COMMENT ON COLUMN property_requirement_complex.complex_id IS 'complex 관련 식별자.';
COMMENT ON COLUMN property_requirement_complex.preference_order IS '희망 단지 우선순위.';
COMMENT ON COLUMN property_requirement_complex.created_at IS '레코드 생성 시각.';

COMMENT ON TABLE ledger_draft IS 'F1 빈 행과 F2 분석 전후 미완성 값을 보존하는 임시 레코드. 핵심 원장의 NOT NULL 무결성을 훼손하지 않는다.';
COMMENT ON COLUMN ledger_draft.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN ledger_draft.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN ledger_draft.ledger_type IS '임시 작성 대상 장부 유형.';
COMMENT ON COLUMN ledger_draft.status IS '현재 상태 값. 상태 전이는 서버에서 관리한다.';
COMMENT ON COLUMN ledger_draft.source_type IS '데이터 생성 출처를 구분하는 값.';
COMMENT ON COLUMN ledger_draft.target_unit_id IS '기존 세대 수정 초안의 대상 세대 식별자.';
COMMENT ON COLUMN ledger_draft.target_listing_id IS '기존 매물 수정 초안의 대상 매물 식별자.';
COMMENT ON COLUMN ledger_draft.target_demand_id IS '기존 수요 수정 초안의 대상 수요 식별자.';
COMMENT ON COLUMN ledger_draft.final_unit_id IS '확정 저장 후 생성 또는 연결된 세대 식별자.';
COMMENT ON COLUMN ledger_draft.final_listing_id IS '확정 저장 후 생성 또는 연결된 매물 식별자.';
COMMENT ON COLUMN ledger_draft.final_demand_id IS '확정 저장 후 생성 또는 연결된 수요 식별자.';
COMMENT ON COLUMN ledger_draft.draft_payload IS '작성 중인 입력값 JSON.';
COMMENT ON COLUMN ledger_draft.created_by IS '생성 사용자 식별자.';
COMMENT ON COLUMN ledger_draft.last_saved_by IS '마지막 임시 저장 사용자 식별자.';
COMMENT ON COLUMN ledger_draft.expires_at IS '임시 초안 만료 예정 시각.';
COMMENT ON COLUMN ledger_draft.completed_at IS '초안 처리 완료 시각.';
COMMENT ON COLUMN ledger_draft.row_version IS '낙관적 동시성 제어용 버전 값. 서버가 증가시킨다.';
COMMENT ON COLUMN ledger_draft.created_at IS '레코드 생성 시각.';
COMMENT ON COLUMN ledger_draft.updated_at IS '레코드 최종 수정 시각. 서버가 갱신한다.';

COMMENT ON TABLE client_interaction IS '상담 로그의 단일 원장. 로그는 append-only이며 삭제 대신 무효 처리한다. F2/F3 로그는 승인된 결과만 확정한다.';
COMMENT ON COLUMN client_interaction.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN client_interaction.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN client_interaction.interaction_at IS '이벤트 또는 상담이 발생한 시각.';
COMMENT ON COLUMN client_interaction.interaction_channel IS '상담 채널.';
COMMENT ON COLUMN client_interaction.communication_direction IS '연락 방향.';
COMMENT ON COLUMN client_interaction.interaction_result IS '상담 또는 연락 결과.';
COMMENT ON COLUMN client_interaction.counterparty_role IS '상대방의 세대 관계 역할.';
COMMENT ON COLUMN client_interaction.counterparty_index IS '같은 역할 상대방의 업무상 순번.';
COMMENT ON COLUMN client_interaction.marker_text IS '기존 장부 호환용 마커 원문.';
COMMENT ON COLUMN client_interaction.interaction_content IS '본문 내용.';
COMMENT ON COLUMN client_interaction.legacy_format_type IS '기존 장부 상담 로그 원문 형식.';
COMMENT ON COLUMN client_interaction.party_id IS '연결된 인물 식별자.';
COMMENT ON COLUMN client_interaction.unit_id IS '연결된 세대 식별자.';
COMMENT ON COLUMN client_interaction.listing_id IS '연결된 매물 업무 건 식별자.';
COMMENT ON COLUMN client_interaction.demand_id IS '연결된 구입장 수요 건 식별자.';
COMMENT ON COLUMN client_interaction.related_context IS '상담 당시 추가 연결 문맥 JSON.';
COMMENT ON COLUMN client_interaction.source_type IS '데이터 생성 출처를 구분하는 값.';
COMMENT ON COLUMN client_interaction.approval_status IS 'AI 생성 상담 로그의 승인 상태 값.';
COMMENT ON COLUMN client_interaction.approved_by IS '승인을 수행한 사용자 식별자.';
COMMENT ON COLUMN client_interaction.approved_at IS '승인 처리 시각.';
COMMENT ON COLUMN client_interaction.source_metadata IS '데이터 생성 출처의 부가 메타데이터.';
COMMENT ON COLUMN client_interaction.created_by IS '생성 사용자 식별자.';
COMMENT ON COLUMN client_interaction.is_voided IS '상담 로그 무효 처리 여부.';
COMMENT ON COLUMN client_interaction.void_reason IS '무효 처리 사유.';
COMMENT ON COLUMN client_interaction.voided_by IS '무효 처리 사용자 식별자.';
COMMENT ON COLUMN client_interaction.voided_at IS '무효 처리 시각.';
COMMENT ON COLUMN client_interaction.created_at IS '레코드 생성 시각.';

COMMENT ON TABLE tenancy_history IS '현 임대차 갱신 전 값을 업무 이력으로 보존한다. unit의 현재 임대차 컬럼은 조회용 최신 스냅샷이다. F1-TR-04.';
COMMENT ON COLUMN tenancy_history.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN tenancy_history.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN tenancy_history.unit_id IS '연결된 세대 식별자.';
COMMENT ON COLUMN tenancy_history.valid_from IS '임대차 정보 적용 시작일.';
COMMENT ON COLUMN tenancy_history.valid_to IS '임대차 정보 적용 종료일.';
COMMENT ON COLUMN tenancy_history.tenancy_status_group_code IS '임대차 상태 코드 그룹. 서버가 TENANCY_STATUS 값을 저장한다.';
COMMENT ON COLUMN tenancy_history.tenancy_status_code IS '임대차 상태 코드.';
COMMENT ON COLUMN tenancy_history.deposit_amount IS '당시 보증금.';
COMMENT ON COLUMN tenancy_history.monthly_rent_amount IS '당시 월 차임.';
COMMENT ON COLUMN tenancy_history.loan_amount IS '당시 융자 금액.';
COMMENT ON COLUMN tenancy_history.expiry_date IS '당시 임대차 만기일.';
COMMENT ON COLUMN tenancy_history.tenancy_raw_text IS '당시 임대차 원문.';
COMMENT ON COLUMN tenancy_history.tenant_parties_snapshot IS '당시 임대차 관계자 스냅샷.';
COMMENT ON COLUMN tenancy_history.source_interaction_id IS '변경 근거 상담 로그 식별자.';
COMMENT ON COLUMN tenancy_history.created_by IS '생성 사용자 식별자.';
COMMENT ON COLUMN tenancy_history.created_at IS '레코드 생성 시각.';

COMMENT ON TABLE property_contract IS '가계약·계약·중도금·잔금·완료 단계를 관리하며 계약 당시 당사자와 체크리스트를 스냅샷으로 보존한다.';
COMMENT ON COLUMN property_contract.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN property_contract.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN property_contract.unit_id IS '연결된 세대 식별자.';
COMMENT ON COLUMN property_contract.listing_id IS '연결된 매물 업무 건 식별자.';
COMMENT ON COLUMN property_contract.demand_id IS '연결된 구입장 수요 건 식별자.';
COMMENT ON COLUMN property_contract.contract_type IS '계약 거래 유형.';
COMMENT ON COLUMN property_contract.status IS '현재 상태 값. 상태 전이는 서버에서 관리한다.';
COMMENT ON COLUMN property_contract.executed_at IS '계약 체결일.';
COMMENT ON COLUMN property_contract.contract_price_amount IS '매매 계약 금액.';
COMMENT ON COLUMN property_contract.contract_deposit_amount IS '계약 보증금.';
COMMENT ON COLUMN property_contract.monthly_rent_amount IS '월 차임.';
COMMENT ON COLUMN property_contract.intermediate_date IS '중도금 예정일.';
COMMENT ON COLUMN property_contract.balance_date IS '잔금 예정일.';
COMMENT ON COLUMN property_contract.contract_parties IS '계약 당시 당사자 스냅샷 JSON.';
COMMENT ON COLUMN property_contract.contract_checklist IS '계약·잔금 서류 체크리스트 JSON.';
COMMENT ON COLUMN property_contract.memo IS '업무 메모.';
COMMENT ON COLUMN property_contract.assigned_user_id IS '업무 담당 사용자 식별자.';
COMMENT ON COLUMN property_contract.row_version IS '낙관적 동시성 제어용 버전 값. 서버가 증가시킨다.';
COMMENT ON COLUMN property_contract.is_deleted IS '소프트 삭제 여부.';
COMMENT ON COLUMN property_contract.deleted_at IS '소프트 삭제 처리 시각.';
COMMENT ON COLUMN property_contract.created_at IS '레코드 생성 시각.';
COMMENT ON COLUMN property_contract.updated_at IS '레코드 최종 수정 시각. 서버가 갱신한다.';

COMMENT ON TABLE property_transaction_history IS '세대의 완료 거래를 시간순으로 직접 조회하기 위한 업무 이력. change_history 감사 로그와 분리한다. F1-TR-03~05.';
COMMENT ON COLUMN property_transaction_history.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN property_transaction_history.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN property_transaction_history.unit_id IS '연결된 세대 식별자.';
COMMENT ON COLUMN property_transaction_history.listing_id IS '연결된 매물 업무 건 식별자.';
COMMENT ON COLUMN property_transaction_history.demand_id IS '연결된 구입장 수요 건 식별자.';
COMMENT ON COLUMN property_transaction_history.contract_id IS '연결된 계약 식별자.';
COMMENT ON COLUMN property_transaction_history.transaction_type IS '완료 거래 유형.';
COMMENT ON COLUMN property_transaction_history.completed_at IS '거래 완료 시각.';
COMMENT ON COLUMN property_transaction_history.transaction_price_amount IS '완료 거래 매매 금액.';
COMMENT ON COLUMN property_transaction_history.deposit_amount IS '완료 거래 보증금.';
COMMENT ON COLUMN property_transaction_history.monthly_rent_amount IS '완료 거래 월 차임.';
COMMENT ON COLUMN property_transaction_history.co_broker_party_id IS '공동중개 상대 업소 또는 인물 식별자.';
COMMENT ON COLUMN property_transaction_history.assigned_user_id IS '업무 담당 사용자 식별자.';
COMMENT ON COLUMN property_transaction_history.parties_snapshot IS '거래 완료 당시 당사자 스냅샷.';
COMMENT ON COLUMN property_transaction_history.source_type IS '데이터 생성 출처를 구분하는 값.';
COMMENT ON COLUMN property_transaction_history.memo IS '업무 메모.';
COMMENT ON COLUMN property_transaction_history.created_at IS '레코드 생성 시각.';

COMMENT ON TABLE business_schedule_event IS '임장·계약·잔금·이사 일정. F3 제안 일정은 사용자 승인 후에만 F1 원장에 생성된다.';
COMMENT ON COLUMN business_schedule_event.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN business_schedule_event.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN business_schedule_event.title IS '표시 제목.';
COMMENT ON COLUMN business_schedule_event.event_type IS '일정 유형.';
COMMENT ON COLUMN business_schedule_event.starts_at IS '일정 시작 시각.';
COMMENT ON COLUMN business_schedule_event.ends_at IS '일정 종료 시각.';
COMMENT ON COLUMN business_schedule_event.location IS '일정 장소.';
COMMENT ON COLUMN business_schedule_event.memo IS '업무 메모.';
COMMENT ON COLUMN business_schedule_event.assigned_user_id IS '업무 담당 사용자 식별자.';
COMMENT ON COLUMN business_schedule_event.unit_id IS '연결된 세대 식별자.';
COMMENT ON COLUMN business_schedule_event.listing_id IS '연결된 매물 업무 건 식별자.';
COMMENT ON COLUMN business_schedule_event.demand_id IS '연결된 구입장 수요 건 식별자.';
COMMENT ON COLUMN business_schedule_event.contract_id IS '연결된 계약 식별자.';
COMMENT ON COLUMN business_schedule_event.status IS '현재 상태 값. 상태 전이는 서버에서 관리한다.';
COMMENT ON COLUMN business_schedule_event.source_type IS '데이터 생성 출처를 구분하는 값.';
COMMENT ON COLUMN business_schedule_event.approval_status IS 'F3 제안 일정의 승인 상태 값.';
COMMENT ON COLUMN business_schedule_event.approved_by IS '승인을 수행한 사용자 식별자.';
COMMENT ON COLUMN business_schedule_event.approved_at IS '승인 처리 시각.';
COMMENT ON COLUMN business_schedule_event.source_metadata IS '데이터 생성 출처의 부가 메타데이터.';
COMMENT ON COLUMN business_schedule_event.created_by IS '생성 사용자 식별자.';
COMMENT ON COLUMN business_schedule_event.row_version IS '낙관적 동시성 제어용 버전 값. 서버가 증가시킨다.';
COMMENT ON COLUMN business_schedule_event.created_at IS '레코드 생성 시각.';
COMMENT ON COLUMN business_schedule_event.updated_at IS '레코드 최종 수정 시각. 서버가 갱신한다.';

COMMENT ON TABLE stored_document IS 'Object Storage에 저장된 음성·PDF·사진·계약서·신분증 등의 메타데이터. 바이너리는 RDB에 저장하지 않는다.';
COMMENT ON COLUMN stored_document.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN stored_document.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN stored_document.document_type_group_code IS '문서 유형 코드 그룹. 서버가 DOCUMENT_TYPE 값을 저장한다.';
COMMENT ON COLUMN stored_document.document_type_code IS '문서 유형 코드.';
COMMENT ON COLUMN stored_document.original_filename IS '업로드 당시 원본 파일명.';
COMMENT ON COLUMN stored_document.storage_object_key IS 'Object Storage 객체 키.';
COMMENT ON COLUMN stored_document.mime_type IS '파일 MIME 유형.';
COMMENT ON COLUMN stored_document.file_size_bytes IS '파일 크기 바이트.';
COMMENT ON COLUMN stored_document.checksum_sha256 IS '파일 SHA-256 체크섬.';
COMMENT ON COLUMN stored_document.issued_at IS '문서 발급일.';
COMMENT ON COLUMN stored_document.expires_at IS '문서 유효 만료일.';
COMMENT ON COLUMN stored_document.access_security_level IS '문서 보안 등급.';
COMMENT ON COLUMN stored_document.retention_until IS '보관 예정 만료 시각.';
COMMENT ON COLUMN stored_document.document_metadata IS '부가 메타데이터 JSON.';
COMMENT ON COLUMN stored_document.uploaded_by IS '문서 업로드 사용자 식별자.';
COMMENT ON COLUMN stored_document.is_deleted IS '소프트 삭제 여부.';
COMMENT ON COLUMN stored_document.deleted_at IS '소프트 삭제 처리 시각.';
COMMENT ON COLUMN stored_document.row_version IS '낙관적 동시성 제어용 버전 값. 서버가 증가시킨다.';
COMMENT ON COLUMN stored_document.created_at IS '레코드 생성 시각.';
COMMENT ON COLUMN stored_document.updated_at IS '레코드 최종 수정 시각. 서버가 갱신한다.';

COMMENT ON TABLE property_unit_document IS '세대와 문서 메타데이터의 다대다 연결 테이블.';
COMMENT ON COLUMN property_unit_document.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN property_unit_document.unit_id IS '연결된 세대 식별자.';
COMMENT ON COLUMN property_unit_document.document_id IS '연결된 문서 메타데이터 식별자.';
COMMENT ON COLUMN property_unit_document.created_at IS '레코드 생성 시각.';

COMMENT ON TABLE party_document IS '인물과 문서 메타데이터의 다대다 연결 테이블.';
COMMENT ON COLUMN party_document.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN party_document.party_id IS '연결된 인물 식별자.';
COMMENT ON COLUMN party_document.document_id IS '연결된 문서 메타데이터 식별자.';
COMMENT ON COLUMN party_document.created_at IS '레코드 생성 시각.';

COMMENT ON TABLE property_requirement_document IS '구입장 수요 건과 문서 메타데이터의 다대다 연결 테이블.';
COMMENT ON COLUMN property_requirement_document.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN property_requirement_document.demand_id IS '연결된 구입장 수요 건 식별자.';
COMMENT ON COLUMN property_requirement_document.document_id IS '연결된 문서 메타데이터 식별자.';
COMMENT ON COLUMN property_requirement_document.created_at IS '레코드 생성 시각.';

COMMENT ON TABLE property_contract_document IS '계약과 문서 메타데이터의 다대다 연결 테이블.';
COMMENT ON COLUMN property_contract_document.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN property_contract_document.contract_id IS '연결된 계약 식별자.';
COMMENT ON COLUMN property_contract_document.document_id IS '연결된 문서 메타데이터 식별자.';
COMMENT ON COLUMN property_contract_document.created_at IS '레코드 생성 시각.';

COMMENT ON TABLE client_interaction_document IS '상담 로그에 연결된 녹취·전사 원문 등 첨부 파일. F1-LG-12, F1-ST-12.';
COMMENT ON COLUMN client_interaction_document.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN client_interaction_document.interaction_id IS '연결된 상담 로그 식별자.';
COMMENT ON COLUMN client_interaction_document.document_id IS '연결된 문서 메타데이터 식별자.';
COMMENT ON COLUMN client_interaction_document.created_at IS '레코드 생성 시각.';

COMMENT ON TABLE facility_history IS '설비·하자·수리 이력을 누적한다. F1-UD-20 선택 요구사항.';
COMMENT ON COLUMN facility_history.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN facility_history.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN facility_history.unit_id IS '연결된 세대 식별자.';
COMMENT ON COLUMN facility_history.occurred_at IS '이벤트 또는 상담이 발생한 시각.';
COMMENT ON COLUMN facility_history.category IS '시설·하자·수리 분류.';
COMMENT ON COLUMN facility_history.description IS '시설 이력 상세 내용.';
COMMENT ON COLUMN facility_history.interaction_id IS '연결된 상담 로그 식별자.';
COMMENT ON COLUMN facility_history.created_by IS '생성 사용자 식별자.';
COMMENT ON COLUMN facility_history.created_at IS '레코드 생성 시각.';

COMMENT ON TABLE business_memo IS '세대·손님과 무관한 사무소 공용 메모장. F1-ET-01 선택 요구사항.';
COMMENT ON COLUMN business_memo.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN business_memo.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN business_memo.title IS '표시 제목.';
COMMENT ON COLUMN business_memo.memo_content IS '본문 내용.';
COMMENT ON COLUMN business_memo.is_pinned IS '상단 고정 여부.';
COMMENT ON COLUMN business_memo.created_by IS '생성 사용자 식별자.';
COMMENT ON COLUMN business_memo.updated_by IS '레코드를 마지막으로 수정한 사용자 식별자.';
COMMENT ON COLUMN business_memo.is_deleted IS '소프트 삭제 여부.';
COMMENT ON COLUMN business_memo.deleted_at IS '소프트 삭제 처리 시각.';
COMMENT ON COLUMN business_memo.row_version IS '낙관적 동시성 제어용 버전 값. 서버가 증가시킨다.';
COMMENT ON COLUMN business_memo.created_at IS '레코드 생성 시각.';
COMMENT ON COLUMN business_memo.updated_at IS '레코드 최종 수정 시각. 서버가 갱신한다.';

COMMENT ON TABLE message_template IS '사무소 공용 또는 담당자 개인 문자 템플릿과 치환 변수. F1-MS-11~12.';
COMMENT ON COLUMN message_template.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN message_template.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN message_template.owner_user_id IS '개인 템플릿 소유 사용자 식별자. NULL이면 사무소 공유 템플릿.';
COMMENT ON COLUMN message_template.name IS '표시 이름 또는 명칭.';
COMMENT ON COLUMN message_template.body IS '본문 내용.';
COMMENT ON COLUMN message_template.variables IS '사용 가능한 치환 변수 목록 JSON.';
COMMENT ON COLUMN message_template.is_shared IS '사무소 공유 여부.';
COMMENT ON COLUMN message_template.is_active IS '사용 가능 여부.';
COMMENT ON COLUMN message_template.created_by IS '생성 사용자 식별자.';
COMMENT ON COLUMN message_template.row_version IS '낙관적 동시성 제어용 버전 값. 서버가 증가시킨다.';
COMMENT ON COLUMN message_template.created_at IS '레코드 생성 시각.';
COMMENT ON COLUMN message_template.updated_at IS '레코드 최종 수정 시각. 서버가 갱신한다.';

COMMENT ON TABLE message_delivery IS '개인·단체 문자 작성, 번호 복사 또는 SMS 어댑터 발송의 한 건. F3는 초안·대상 확정까지만 수행한다.';
COMMENT ON COLUMN message_delivery.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN message_delivery.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN message_delivery.delivery_scope IS '개인 또는 단체 발송 구분.';
COMMENT ON COLUMN message_delivery.delivery_mode IS '번호 복사 또는 SMS 어댑터 발송 모드.';
COMMENT ON COLUMN message_delivery.status IS '현재 상태 값. 상태 전이는 서버에서 관리한다.';
COMMENT ON COLUMN message_delivery.source_type IS '데이터 생성 출처를 구분하는 값.';
COMMENT ON COLUMN message_delivery.template_id IS '사용한 문자 템플릿 식별자.';
COMMENT ON COLUMN message_delivery.subject IS '발송 건 제목 또는 내부 구분명.';
COMMENT ON COLUMN message_delivery.message_body_template IS '수신자 치환 전 문자 본문.';
COMMENT ON COLUMN message_delivery.total_recipient_count IS '전체 수신 대상 수.';
COMMENT ON COLUMN message_delivery.excluded_recipient_count IS '발송 제외 대상 수.';
COMMENT ON COLUMN message_delivery.successful_recipient_count IS '성공 처리 수.';
COMMENT ON COLUMN message_delivery.failed_recipient_count IS '실패 처리 수.';
COMMENT ON COLUMN message_delivery.sender_user_id IS '발송 수행 사용자 식별자.';
COMMENT ON COLUMN message_delivery.approved_by IS '승인을 수행한 사용자 식별자.';
COMMENT ON COLUMN message_delivery.approved_at IS '승인 처리 시각.';
COMMENT ON COLUMN message_delivery.copied_at IS '번호 목록 복사 시각.';
COMMENT ON COLUMN message_delivery.sent_at IS '실제 발송 처리 시각.';
COMMENT ON COLUMN message_delivery.delivery_provider_response IS '발송 어댑터 응답 JSON.';
COMMENT ON COLUMN message_delivery.created_at IS '레코드 생성 시각.';
COMMENT ON COLUMN message_delivery.updated_at IS '레코드 최종 수정 시각. 서버가 갱신한다.';

COMMENT ON TABLE message_recipient IS '발송 건별 실제 수신자·치환 문안·개별 결과. 동일 번호는 발송 건 안에서 한 번만 존재한다.';
COMMENT ON COLUMN message_recipient.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN message_recipient.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN message_recipient.message_delivery_id IS '소속 문자 발송 건 식별자.';
COMMENT ON COLUMN message_recipient.party_id IS '연결된 인물 식별자.';
COMMENT ON COLUMN message_recipient.party_contact_id IS '사용한 연락처 식별자.';
COMMENT ON COLUMN message_recipient.unit_id IS '연결된 세대 식별자.';
COMMENT ON COLUMN message_recipient.demand_id IS '연결된 구입장 수요 건 식별자.';
COMMENT ON COLUMN message_recipient.interaction_id IS '연결된 상담 로그 식별자.';
COMMENT ON COLUMN message_recipient.recipient_name_snapshot IS '발송 당시 수신자 이름 스냅샷.';
COMMENT ON COLUMN message_recipient.phone_raw_snapshot IS '발송 당시 전화번호 원문 스냅샷.';
COMMENT ON COLUMN message_recipient.phone_normalized IS '발송 당시 정규화 전화번호.';
COMMENT ON COLUMN message_recipient.rendered_body IS '수신자별 치환이 끝난 최종 문안.';
COMMENT ON COLUMN message_recipient.status IS '현재 상태 값. 상태 전이는 서버에서 관리한다.';
COMMENT ON COLUMN message_recipient.excluded_reason IS '발송 제외 사유.';
COMMENT ON COLUMN message_recipient.failure_reason IS '개별 처리 실패 사유.';
COMMENT ON COLUMN message_recipient.processed_at IS '개별 수신자 처리 시각.';
COMMENT ON COLUMN message_recipient.created_at IS '레코드 생성 시각.';

COMMENT ON TABLE notification_preference IS '담당자별 알림 종류 켜기·끄기와 기준 기간. F1-AL-05.';
COMMENT ON COLUMN notification_preference.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN notification_preference.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN notification_preference.user_id IS '알림 설정 사용자 식별자.';
COMMENT ON COLUMN notification_preference.notification_type IS '알림 종류.';
COMMENT ON COLUMN notification_preference.is_enabled IS '알림 사용 여부.';
COMMENT ON COLUMN notification_preference.threshold_days IS '알림 기준 일수.';
COMMENT ON COLUMN notification_preference.config IS '알림 세부 설정 JSON.';
COMMENT ON COLUMN notification_preference.row_version IS '낙관적 동시성 제어용 버전 값. 서버가 증가시킨다.';
COMMENT ON COLUMN notification_preference.created_at IS '레코드 생성 시각.';
COMMENT ON COLUMN notification_preference.updated_at IS '레코드 최종 수정 시각. 서버가 갱신한다.';

COMMENT ON TABLE notification IS '만기·일정·미접촉 알림 센터의 개별 알림과 읽음 상태. F1-AL-01~06.';
COMMENT ON COLUMN notification.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN notification.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN notification.user_id IS '알림 수신 사용자 식별자.';
COMMENT ON COLUMN notification.notification_type IS '알림 종류.';
COMMENT ON COLUMN notification.title IS '표시 제목.';
COMMENT ON COLUMN notification.message IS '알림 상세 메시지.';
COMMENT ON COLUMN notification.due_at IS '알림 기준 예정 시각.';
COMMENT ON COLUMN notification.unit_id IS '연결된 세대 식별자.';
COMMENT ON COLUMN notification.listing_id IS '연결된 매물 업무 건 식별자.';
COMMENT ON COLUMN notification.demand_id IS '연결된 구입장 수요 건 식별자.';
COMMENT ON COLUMN notification.schedule_event_id IS '연결된 일정 식별자.';
COMMENT ON COLUMN notification.contract_id IS '연결된 계약 식별자.';
COMMENT ON COLUMN notification.created_at IS '레코드 생성 시각.';
COMMENT ON COLUMN notification.read_at IS '읽음 처리 시각.';
COMMENT ON COLUMN notification.dismissed_at IS '알림 해제 시각.';

COMMENT ON TABLE change_history IS '주요 데이터 생성·수정·삭제·복구·병합의 감사 이벤트. source_type, batch_id, request_id로 F2/F3·일괄편집을 추적한다.';
COMMENT ON COLUMN change_history.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN change_history.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN change_history.entity_type IS '변경 대상 엔터티 종류.';
COMMENT ON COLUMN change_history.entity_id IS '변경 대상 엔터티 식별자.';
COMMENT ON COLUMN change_history.action IS '변경 작업 종류.';
COMMENT ON COLUMN change_history.changes IS '변경 전후 데이터 JSON.';
COMMENT ON COLUMN change_history.source_type IS '데이터 생성 출처를 구분하는 값.';
COMMENT ON COLUMN change_history.batch_id IS '일괄 작업 추적용 UUID.';
COMMENT ON COLUMN change_history.request_id IS '요청 중복 방지 및 추적용 UUID.';
COMMENT ON COLUMN change_history.changed_by IS '변경 수행 사용자 식별자.';
COMMENT ON COLUMN change_history.changed_at IS '변경 발생 시각.';

COMMENT ON TABLE access_audit_log IS '개인정보·민감 문서·내보내기·F3 도구 조회/쓰기를 기록한다. polymorphic 감사 대상은 삭제 이후에도 보존하기 위해 물리 FK를 두지 않는다.';
COMMENT ON COLUMN access_audit_log.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN access_audit_log.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN access_audit_log.user_id IS '접근 행위를 수행한 사용자 식별자.';
COMMENT ON COLUMN access_audit_log.actor_source IS '접근 주체 유형.';
COMMENT ON COLUMN access_audit_log.action IS '감사 대상 접근 행위.';
COMMENT ON COLUMN access_audit_log.entity_type IS '접근 대상 엔터티 종류.';
COMMENT ON COLUMN access_audit_log.entity_id IS '접근 대상 엔터티 식별자.';
COMMENT ON COLUMN access_audit_log.metadata IS '부가 메타데이터 JSON.';
COMMENT ON COLUMN access_audit_log.occurred_at IS '이벤트 또는 상담이 발생한 시각.';

COMMENT ON TABLE migration_batch IS '화면 캡처·복사 텍스트 기반 이관의 기준 건수, 적재·실패·검수 건수를 대조한다. F1-MG-01~09.';
COMMENT ON COLUMN migration_batch.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN migration_batch.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN migration_batch.ledger_type IS '이관 대상 장부 유형.';
COMMENT ON COLUMN migration_batch.status IS '현재 상태 값. 상태 전이는 서버에서 관리한다.';
COMMENT ON COLUMN migration_batch.baseline_row_count IS '이관 전 화면에서 확인한 기준 행 수.';
COMMENT ON COLUMN migration_batch.loaded_row_count IS '적재 완료 행 수.';
COMMENT ON COLUMN migration_batch.failed_row_count IS '적재 실패 행 수.';
COMMENT ON COLUMN migration_batch.reviewed_row_count IS '검수 완료 행 수.';
COMMENT ON COLUMN migration_batch.started_at IS '이관 시작 시각.';
COMMENT ON COLUMN migration_batch.completed_at IS '이관 완료 시각.';
COMMENT ON COLUMN migration_batch.created_by IS '생성 사용자 식별자.';
COMMENT ON COLUMN migration_batch.notes IS '이관 작업 비고.';
COMMENT ON COLUMN migration_batch.created_at IS '레코드 생성 시각.';
COMMENT ON COLUMN migration_batch.updated_at IS '레코드 최종 수정 시각. 서버가 갱신한다.';

COMMENT ON TABLE migration_source IS '캡처 이미지·복사 원문·OCR 결과와 당시 필터·정렬·촬영 시각 메타데이터.';
COMMENT ON COLUMN migration_source.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN migration_source.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN migration_source.migration_batch_id IS '소속 이관 배치 식별자.';
COMMENT ON COLUMN migration_source.source_type IS '캡처·복사 텍스트·OCR 등 원천 유형.';
COMMENT ON COLUMN migration_source.document_id IS '연결된 문서 메타데이터 식별자.';
COMMENT ON COLUMN migration_source.source_raw_text IS '이관 원문 텍스트.';
COMMENT ON COLUMN migration_source.capture_metadata IS '캡처 당시 필터·정렬 등 메타데이터.';
COMMENT ON COLUMN migration_source.checksum_sha256 IS '원천 파일 체크섬.';
COMMENT ON COLUMN migration_source.source_order IS '원천 자료 처리 순서.';
COMMENT ON COLUMN migration_source.created_at IS '레코드 생성 시각.';

COMMENT ON TABLE migration_row_processing_result IS '원문과 정규화 결과를 나란히 보존하고 파싱 실패 행을 재검수·재실행한다.';
COMMENT ON COLUMN migration_row_processing_result.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN migration_row_processing_result.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN migration_row_processing_result.migration_source_id IS '소속 이관 원천 식별자.';
COMMENT ON COLUMN migration_row_processing_result.source_row_key IS '원본 행을 식별하기 위한 키.';
COMMENT ON COLUMN migration_row_processing_result.source_row_data IS '원본 행 값 JSON.';
COMMENT ON COLUMN migration_row_processing_result.parsed_row_data IS '정규화·파싱 결과 JSON.';
COMMENT ON COLUMN migration_row_processing_result.status IS '현재 상태 값. 상태 전이는 서버에서 관리한다.';
COMMENT ON COLUMN migration_row_processing_result.error_code IS '파싱 또는 적재 오류 코드.';
COMMENT ON COLUMN migration_row_processing_result.error_message IS '오류 상세 메시지.';
COMMENT ON COLUMN migration_row_processing_result.unit_id IS '연결된 세대 식별자.';
COMMENT ON COLUMN migration_row_processing_result.listing_id IS '연결된 매물 업무 건 식별자.';
COMMENT ON COLUMN migration_row_processing_result.demand_id IS '연결된 구입장 수요 건 식별자.';
COMMENT ON COLUMN migration_row_processing_result.reviewed_by IS '검수 사용자 식별자.';
COMMENT ON COLUMN migration_row_processing_result.reviewed_at IS '검수 시각.';
COMMENT ON COLUMN migration_row_processing_result.created_at IS '레코드 생성 시각.';
COMMENT ON COLUMN migration_row_processing_result.updated_at IS '레코드 최종 수정 시각. 서버가 갱신한다.';

COMMENT ON TABLE migration_progress IS '단지·동 단위 이관 완료 여부와 중단·재개 지점을 관리한다.';
COMMENT ON COLUMN migration_progress.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN migration_progress.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN migration_progress.migration_batch_id IS '소속 이관 배치 식별자.';
COMMENT ON COLUMN migration_progress.complex_id IS '진행 현황 대상 단지 식별자.';
COMMENT ON COLUMN migration_progress.building_number IS '진행 현황 대상 동 번호.';
COMMENT ON COLUMN migration_progress.status IS '현재 상태 값. 상태 전이는 서버에서 관리한다.';
COMMENT ON COLUMN migration_progress.expected_count IS '예상 적재 건수.';
COMMENT ON COLUMN migration_progress.loaded_count IS '현재 적재 완료 건수.';
COMMENT ON COLUMN migration_progress.failed_count IS '현재 적재 실패 건수.';
COMMENT ON COLUMN migration_progress.updated_at IS '레코드 최종 수정 시각. 서버가 갱신한다.';

COMMENT ON TABLE consultation_transcription_job IS '음성 업로드·Whisper 전사·로컬 LLM 분석·검토·저장 상태를 추적한다. RunPod 원본은 영구 보존하지 않는다.';
COMMENT ON COLUMN consultation_transcription_job.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN consultation_transcription_job.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN consultation_transcription_job.request_id IS '요청 중복 방지 및 추적용 UUID.';
COMMENT ON COLUMN consultation_transcription_job.ledger_draft_id IS 'F2가 채우는 F1 임시 장부 초안 식별자.';
COMMENT ON COLUMN consultation_transcription_job.input_mode IS '마이크 녹음 또는 파일 업로드 입력 방식.';
COMMENT ON COLUMN consultation_transcription_job.source_audio_document_id IS '입력 음성 문서 식별자.';
COMMENT ON COLUMN consultation_transcription_job.status IS '현재 상태 값. 상태 전이는 서버에서 관리한다.';
COMMENT ON COLUMN consultation_transcription_job.transcription_model_config_id IS '사용한 STT 모델 설정 식별자.';
COMMENT ON COLUMN consultation_transcription_job.analysis_model_config_id IS '사용한 슬롯 필링 모델 설정 식별자.';
COMMENT ON COLUMN consultation_transcription_job.transcribed_text IS 'STT 변환 결과 텍스트.';
COMMENT ON COLUMN consultation_transcription_job.consultation_type IS 'AI가 분류한 상담 유형.';
COMMENT ON COLUMN consultation_transcription_job.ledger_match_result IS '상담 유형과 현재 장부의 일치 판단 값.';
COMMENT ON COLUMN consultation_transcription_job.analysis_summary IS 'F2 분석 요약 JSON.';
COMMENT ON COLUMN consultation_transcription_job.retry_count IS '재시도 횟수.';
COMMENT ON COLUMN consultation_transcription_job.failed_stage IS '실패가 발생한 처리 단계.';
COMMENT ON COLUMN consultation_transcription_job.failure_code IS '실패 분류 코드.';
COMMENT ON COLUMN consultation_transcription_job.failure_message IS '실패 상세 메시지.';
COMMENT ON COLUMN consultation_transcription_job.started_at IS 'F2 처리 시작 시각.';
COMMENT ON COLUMN consultation_transcription_job.transcribed_at IS 'STT 완료 시각.';
COMMENT ON COLUMN consultation_transcription_job.analyzed_at IS 'LLM 분석 완료 시각.';
COMMENT ON COLUMN consultation_transcription_job.approved_by IS '승인을 수행한 사용자 식별자.';
COMMENT ON COLUMN consultation_transcription_job.approved_at IS '승인 처리 시각.';
COMMENT ON COLUMN consultation_transcription_job.ledger_saved_at IS 'F1 원장 저장 완료 시각.';
COMMENT ON COLUMN consultation_transcription_job.retention_until IS '보관 예정 만료 시각.';
COMMENT ON COLUMN consultation_transcription_job.purged_at IS '민감 데이터 파기 처리 시각.';
COMMENT ON COLUMN consultation_transcription_job.created_by IS '생성 사용자 식별자.';
COMMENT ON COLUMN consultation_transcription_job.created_at IS '레코드 생성 시각.';
COMMENT ON COLUMN consultation_transcription_job.updated_at IS '레코드 최종 수정 시각. 서버가 갱신한다.';

COMMENT ON TABLE transcription_field_proposal IS '현재값·AI 제안값·사용자 최종값·근거 문장·충돌 상태를 필드 단위로 보존한다. F2-REV-01~03.';
COMMENT ON COLUMN transcription_field_proposal.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN transcription_field_proposal.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN transcription_field_proposal.transcription_job_id IS '소속 F2 STT 작업 식별자.';
COMMENT ON COLUMN transcription_field_proposal.target_entity IS '제안값 적용 대상 엔터티 유형.';
COMMENT ON COLUMN transcription_field_proposal.field_name IS '제안 대상 필드명.';
COMMENT ON COLUMN transcription_field_proposal.current_value IS '현재 장부 값 JSON.';
COMMENT ON COLUMN transcription_field_proposal.proposed_value IS 'AI 제안 값 JSON.';
COMMENT ON COLUMN transcription_field_proposal.final_value IS '사용자 최종 값 JSON.';
COMMENT ON COLUMN transcription_field_proposal.proposal_status IS '제안 처리 상태.';
COMMENT ON COLUMN transcription_field_proposal.confidence IS 'AI 제안 신뢰도.';
COMMENT ON COLUMN transcription_field_proposal.evidence_text IS '제안 근거 STT 문장.';
COMMENT ON COLUMN transcription_field_proposal.is_selected IS '사용자가 반영 대상으로 선택했는지 여부.';
COMMENT ON COLUMN transcription_field_proposal.applied_by IS '제안 반영 사용자 식별자.';
COMMENT ON COLUMN transcription_field_proposal.applied_at IS '제안 반영 시각.';
COMMENT ON COLUMN transcription_field_proposal.created_at IS '레코드 생성 시각.';
COMMENT ON COLUMN transcription_field_proposal.updated_at IS '레코드 최종 수정 시각. 서버가 갱신한다.';

COMMENT ON TABLE interaction_log_proposal IS 'F2가 생성한 상담 로그 초안. 승인된 경우 source_type=F2인 interaction과 연결한다. F2-REV-04.';
COMMENT ON COLUMN interaction_log_proposal.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN interaction_log_proposal.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN interaction_log_proposal.transcription_job_id IS '소속 F2 STT 작업 식별자.';
COMMENT ON COLUMN interaction_log_proposal.draft_interaction_content IS 'AI가 생성한 상담 로그 초안.';
COMMENT ON COLUMN interaction_log_proposal.final_interaction_content IS '사용자가 확정한 상담 로그 본문.';
COMMENT ON COLUMN interaction_log_proposal.proposal_status IS '로그 제안 처리 상태.';
COMMENT ON COLUMN interaction_log_proposal.is_selected IS '로그 반영 선택 여부.';
COMMENT ON COLUMN interaction_log_proposal.final_client_interaction_id IS '확정 후 생성된 상담 로그 식별자.';
COMMENT ON COLUMN interaction_log_proposal.approved_by IS '승인을 수행한 사용자 식별자.';
COMMENT ON COLUMN interaction_log_proposal.approved_at IS '승인 처리 시각.';
COMMENT ON COLUMN interaction_log_proposal.created_at IS '레코드 생성 시각.';
COMMENT ON COLUMN interaction_log_proposal.updated_at IS '레코드 최종 수정 시각. 서버가 갱신한다.';

COMMENT ON TABLE f3_agent_run IS 'F3 에이전트 실행의 모델, 입력 버전, 토큰, 지연시간, 마스킹된 입출력, 보관·파기 상태를 추적한다. F3-CM-04~08.';
COMMENT ON COLUMN f3_agent_run.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN f3_agent_run.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN f3_agent_run.parent_run_id IS '상위 F3 실행 식별자.';
COMMENT ON COLUMN f3_agent_run.run_type IS 'F3 실행 작업 유형.';
COMMENT ON COLUMN f3_agent_run.agent_type IS '실행한 에이전트 유형.';
COMMENT ON COLUMN f3_agent_run.status IS '현재 상태 값. 상태 전이는 서버에서 관리한다.';
COMMENT ON COLUMN f3_agent_run.trigger_type IS '실행을 요청한 사용자 행동 또는 트리거 구분.';
COMMENT ON COLUMN f3_agent_run.model_config_id IS '사용 모델 설정 식별자.';
COMMENT ON COLUMN f3_agent_run.requested_by IS '실행 요청 사용자 식별자.';
COMMENT ON COLUMN f3_agent_run.target_unit_id IS '실행 대상 세대 식별자.';
COMMENT ON COLUMN f3_agent_run.target_listing_id IS '실행 대상 매물 식별자.';
COMMENT ON COLUMN f3_agent_run.target_demand_id IS '실행 대상 수요 식별자.';
COMMENT ON COLUMN f3_agent_run.data_version IS '판정 입력 데이터 버전.';
COMMENT ON COLUMN f3_agent_run.last_log_at IS '입력 데이터의 마지막 상담 로그 시각.';
COMMENT ON COLUMN f3_agent_run.input_snapshot IS 'F3 실행 입력 스냅샷 JSON.';
COMMENT ON COLUMN f3_agent_run.output_snapshot IS 'F3 실행 출력 스냅샷 JSON.';
COMMENT ON COLUMN f3_agent_run.input_tokens IS '입력 토큰 수.';
COMMENT ON COLUMN f3_agent_run.output_tokens IS '출력 토큰 수.';
COMMENT ON COLUMN f3_agent_run.latency_ms IS '실행 지연시간 밀리초.';
COMMENT ON COLUMN f3_agent_run.failure_code IS '실패 분류 코드.';
COMMENT ON COLUMN f3_agent_run.failure_message IS '실패 상세 메시지.';
COMMENT ON COLUMN f3_agent_run.started_at IS '실행 시작 시각.';
COMMENT ON COLUMN f3_agent_run.completed_at IS '실행 종료 시각.';
COMMENT ON COLUMN f3_agent_run.retention_until IS '보관 예정 만료 시각.';
COMMENT ON COLUMN f3_agent_run.purged_at IS '민감 데이터 파기 처리 시각.';
COMMENT ON COLUMN f3_agent_run.created_at IS '레코드 생성 시각.';
COMMENT ON COLUMN f3_agent_run.updated_at IS '레코드 최종 수정 시각. 서버가 갱신한다.';

COMMENT ON TABLE f3_tool_call IS '로그 검색·매물 조회·손님 조회·접촉 이력 등 F3 도구 호출 기록. F3-TL-07.';
COMMENT ON COLUMN f3_tool_call.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN f3_tool_call.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN f3_tool_call.agent_run_id IS '소속 F3 실행 식별자.';
COMMENT ON COLUMN f3_tool_call.tool_name IS '호출한 도구 이름.';
COMMENT ON COLUMN f3_tool_call.status IS '현재 상태 값. 상태 전이는 서버에서 관리한다.';
COMMENT ON COLUMN f3_tool_call.request_payload IS '도구 요청 데이터 JSON.';
COMMENT ON COLUMN f3_tool_call.response_payload IS '도구 응답 데이터 JSON.';
COMMENT ON COLUMN f3_tool_call.started_at IS '도구 호출 시작 시각.';
COMMENT ON COLUMN f3_tool_call.completed_at IS '도구 호출 종료 시각.';
COMMENT ON COLUMN f3_tool_call.latency_ms IS '도구 호출 지연시간 밀리초.';
COMMENT ON COLUMN f3_tool_call.failure_message IS '실패 상세 메시지.';
COMMENT ON COLUMN f3_tool_call.created_at IS '레코드 생성 시각.';

COMMENT ON TABLE negotiation_position_analysis IS '매물 대리·손님 대리의 캐시 단위. 대상 ID, 마지막 로그 시각, 데이터 버전을 cache_key에 반영한다. F3-PC-01~13.';
COMMENT ON COLUMN negotiation_position_analysis.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN negotiation_position_analysis.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN negotiation_position_analysis.agent_run_id IS '카드를 생성한 F3 실행 식별자.';
COMMENT ON COLUMN negotiation_position_analysis.negotiation_side IS '매물 측 또는 손님 측 카드 구분.';
COMMENT ON COLUMN negotiation_position_analysis.unit_id IS '연결된 세대 식별자.';
COMMENT ON COLUMN negotiation_position_analysis.listing_id IS '연결된 매물 업무 건 식별자.';
COMMENT ON COLUMN negotiation_position_analysis.demand_id IS '연결된 구입장 수요 건 식별자.';
COMMENT ON COLUMN negotiation_position_analysis.target_label IS '화면 표시용 대상 라벨.';
COMMENT ON COLUMN negotiation_position_analysis.cache_key IS '서버가 생성한 포지션 카드 캐시 키.';
COMMENT ON COLUMN negotiation_position_analysis.source_log_count IS '카드 생성에 사용한 상담 로그 수.';
COMMENT ON COLUMN negotiation_position_analysis.last_log_at IS '카드 입력 데이터의 마지막 상담 로그 시각.';
COMMENT ON COLUMN negotiation_position_analysis.data_version IS '카드 입력 데이터 버전.';
COMMENT ON COLUMN negotiation_position_analysis.negotiation_intent IS '의향 판정 값.';
COMMENT ON COLUMN negotiation_position_analysis.stated_price_amount IS '장부에 표기된 가격.';
COMMENT ON COLUMN negotiation_position_analysis.estimated_price_amount IS '에이전트가 추정한 실질 가격.';
COMMENT ON COLUMN negotiation_position_analysis.price_estimation_basis IS '추정 가격 근거.';
COMMENT ON COLUMN negotiation_position_analysis.urgency IS '시급도 판정 값.';
COMMENT ON COLUMN negotiation_position_analysis.preferred_timing IS '시점·마감 조건 JSON.';
COMMENT ON COLUMN negotiation_position_analysis.flexible_conditions IS '양보 가능한 조건 목록 JSON.';
COMMENT ON COLUMN negotiation_position_analysis.inflexible_conditions IS '양보 불가 조건 목록 JSON.';
COMMENT ON COLUMN negotiation_position_analysis.contact_availability IS '접촉 가능 상태.';
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
COMMENT ON COLUMN negotiation_position_evidence.note IS '추정 근거 설명.';
COMMENT ON COLUMN negotiation_position_evidence.display_order IS '화면 표시 순서.';
COMMENT ON COLUMN negotiation_position_evidence.created_at IS '레코드 생성 시각.';

COMMENT ON TABLE negotiation_position_correction IS '중개사가 정정한 포지션과 그 정정 내용을 append한 상담 로그를 연결한다. F3-PC-08, F3-TR-02.';
COMMENT ON COLUMN negotiation_position_correction.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN negotiation_position_correction.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN negotiation_position_correction.position_analysis_id IS '정정 대상 포지션 카드 식별자.';
COMMENT ON COLUMN negotiation_position_correction.field_name IS '정정 대상 필드명.';
COMMENT ON COLUMN negotiation_position_correction.original_value IS '정정 전 값 JSON.';
COMMENT ON COLUMN negotiation_position_correction.corrected_value IS '중개사가 정정한 값 JSON.';
COMMENT ON COLUMN negotiation_position_correction.correction_reason IS '정정 사유.';
COMMENT ON COLUMN negotiation_position_correction.corrected_by IS '정정 사용자 식별자.';
COMMENT ON COLUMN negotiation_position_correction.correction_interaction_id IS '정정 내용을 append한 상담 로그 식별자.';
COMMENT ON COLUMN negotiation_position_correction.corrected_at IS '정정 시각.';

COMMENT ON TABLE match_evaluation IS '앵커 카드 1장과 후보 N장을 한 번의 중개 판정 호출로 평가한 결과의 헤더. F3-BR-01~14.';
COMMENT ON COLUMN match_evaluation.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN match_evaluation.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN match_evaluation.agent_run_id IS '중개 판정을 수행한 F3 실행 식별자.';
COMMENT ON COLUMN match_evaluation.anchor_position_analysis_id IS '판정 기준 포지션 카드 식별자.';
COMMENT ON COLUMN match_evaluation.candidate_count IS '판정 후보 수.';
COMMENT ON COLUMN match_evaluation.data_version IS '판정 입력 데이터 버전.';
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
COMMENT ON COLUMN match_candidate_evaluation.proposed_schedule IS '일정 제안 JSON.';
COMMENT ON COLUMN match_candidate_evaluation.exclusion_reason IS '기각 판정 사유.';
COMMENT ON COLUMN match_candidate_evaluation.schedule_event_id IS '승인 후 생성된 F1 일정 식별자.';
COMMENT ON COLUMN match_candidate_evaluation.message_delivery_id IS '연결된 문자 발송 건 식별자.';
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
COMMENT ON COLUMN match_candidate_evidence.note IS '추정 근거 설명.';
COMMENT ON COLUMN match_candidate_evidence.created_at IS '레코드 생성 시각.';

COMMENT ON TABLE match_pair_exclusion IS '같은 매물·손님 쌍의 반복 기각과 사용자 해제 가능한 영구 제외 후보를 관리한다. F3-TR-06.';
COMMENT ON COLUMN match_pair_exclusion.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN match_pair_exclusion.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN match_pair_exclusion.unit_id IS '연결된 세대 식별자.';
COMMENT ON COLUMN match_pair_exclusion.listing_id IS '연결된 매물 업무 건 식별자.';
COMMENT ON COLUMN match_pair_exclusion.demand_id IS '연결된 구입장 수요 건 식별자.';
COMMENT ON COLUMN match_pair_exclusion.rejection_occurrence_count IS '동일 매물·수요 쌍의 누적 기각 횟수.';
COMMENT ON COLUMN match_pair_exclusion.is_excluded IS '서버가 영구 제외 대상으로 처리한 여부.';
COMMENT ON COLUMN match_pair_exclusion.exclusion_reason IS '영구 제외 사유.';
COMMENT ON COLUMN match_pair_exclusion.excluded_by IS '제외 처리 사용자 식별자.';
COMMENT ON COLUMN match_pair_exclusion.excluded_at IS '제외 처리 시각.';
COMMENT ON COLUMN match_pair_exclusion.exclusion_released_by IS '제외 해제 사용자 식별자.';
COMMENT ON COLUMN match_pair_exclusion.exclusion_released_at IS '제외 해제 시각.';
COMMENT ON COLUMN match_pair_exclusion.row_version IS '낙관적 동시성 제어용 버전 값. 서버가 증가시킨다.';
COMMENT ON COLUMN match_pair_exclusion.created_at IS '레코드 생성 시각.';
COMMENT ON COLUMN match_pair_exclusion.updated_at IS '레코드 최종 수정 시각. 서버가 갱신한다.';

COMMENT ON TABLE f3_campaign IS '필터·그리드 선택·자연어 조건으로 대상을 선정하고 대리 배치 판정을 수행하는 캠페인 헤더. 정기 스케줄은 두지 않는다.';
COMMENT ON COLUMN f3_campaign.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN f3_campaign.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN f3_campaign.name IS '표시 이름 또는 명칭.';
COMMENT ON COLUMN f3_campaign.target_side IS '캠페인 판정 대상 측.';
COMMENT ON COLUMN f3_campaign.selection_method IS '대상 선정 방식.';
COMMENT ON COLUMN f3_campaign.natural_language_query IS '자연어 대상 선정 입력.';
COMMENT ON COLUMN f3_campaign.condition_spec IS '서버가 확정한 대상 선정 조건 JSON.';
COMMENT ON COLUMN f3_campaign.status IS '현재 상태 값. 상태 전이는 서버에서 관리한다.';
COMMENT ON COLUMN f3_campaign.max_target_count IS '캠페인 대상 상한.';
COMMENT ON COLUMN f3_campaign.selected_count IS '선정 대상 수.';
COMMENT ON COLUMN f3_campaign.analyzed_count IS '분석 완료 대상 수.';
COMMENT ON COLUMN f3_campaign.excluded_count IS '발송 제외 대상 수.';
COMMENT ON COLUMN f3_campaign.created_by IS '생성 사용자 식별자.';
COMMENT ON COLUMN f3_campaign.approved_by IS '승인을 수행한 사용자 식별자.';
COMMENT ON COLUMN f3_campaign.approved_at IS '승인 처리 시각.';
COMMENT ON COLUMN f3_campaign.executed_at IS '캠페인 실행 시각.';
COMMENT ON COLUMN f3_campaign.created_at IS '레코드 생성 시각.';
COMMENT ON COLUMN f3_campaign.updated_at IS '레코드 최종 수정 시각. 서버가 갱신한다.';

COMMENT ON TABLE f3_campaign_segment IS '매도 의향·만기 임박·최근 거절·결정권 없음·판단 불가 등 판정 세그먼트와 세그먼트별 문안.';
COMMENT ON COLUMN f3_campaign_segment.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN f3_campaign_segment.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN f3_campaign_segment.campaign_id IS '소속 캠페인 식별자.';
COMMENT ON COLUMN f3_campaign_segment.segment_code IS '캠페인 내 세그먼트 코드.';
COMMENT ON COLUMN f3_campaign_segment.name IS '표시 이름 또는 명칭.';
COMMENT ON COLUMN f3_campaign_segment.description IS '설명.';
COMMENT ON COLUMN f3_campaign_segment.is_excluded IS '세그먼트 전체 발송 제외 여부.';
COMMENT ON COLUMN f3_campaign_segment.exclusion_reason IS '세그먼트 제외 사유.';
COMMENT ON COLUMN f3_campaign_segment.target_count IS '세그먼트 대상 수.';
COMMENT ON COLUMN f3_campaign_segment.message_body IS '세그먼트별 문자 초안.';
COMMENT ON COLUMN f3_campaign_segment.message_generation_run_id IS '문안 생성 F3 실행 식별자.';
COMMENT ON COLUMN f3_campaign_segment.message_delivery_id IS 'F1 문자 발송 건 식별자.';
COMMENT ON COLUMN f3_campaign_segment.display_order IS '화면 표시 순서.';
COMMENT ON COLUMN f3_campaign_segment.created_at IS '레코드 생성 시각.';
COMMENT ON COLUMN f3_campaign_segment.updated_at IS '레코드 최종 수정 시각. 서버가 갱신한다.';

COMMENT ON TABLE f3_campaign_target IS '캠페인 대상 전원과 판정 세그먼트·발송 제외 사유를 보존한다. 임의 컷 없이 모든 대상이 결과에 남는다.';
COMMENT ON COLUMN f3_campaign_target.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN f3_campaign_target.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN f3_campaign_target.campaign_id IS '소속 캠페인 식별자.';
COMMENT ON COLUMN f3_campaign_target.unit_id IS '연결된 세대 식별자.';
COMMENT ON COLUMN f3_campaign_target.listing_id IS '연결된 매물 업무 건 식별자.';
COMMENT ON COLUMN f3_campaign_target.demand_id IS '연결된 구입장 수요 건 식별자.';
COMMENT ON COLUMN f3_campaign_target.party_id IS '연결된 인물 식별자.';
COMMENT ON COLUMN f3_campaign_target.party_contact_id IS '캠페인에 사용할 연락처 식별자.';
COMMENT ON COLUMN f3_campaign_target.agent_run_id IS '대상 판정 F3 실행 식별자.';
COMMENT ON COLUMN f3_campaign_target.position_analysis_id IS '대상 포지션 카드 식별자.';
COMMENT ON COLUMN f3_campaign_target.segment_id IS '배정된 캠페인 세그먼트 식별자.';
COMMENT ON COLUMN f3_campaign_target.status IS '현재 상태 값. 상태 전이는 서버에서 관리한다.';
COMMENT ON COLUMN f3_campaign_target.preliminary_evaluation IS '배치용 얕은 판정 결과 JSON.';
COMMENT ON COLUMN f3_campaign_target.exclusion_reason IS '발송 제외 사유.';
COMMENT ON COLUMN f3_campaign_target.last_contact_at_snapshot IS '대상 선정 당시 최종 접촉 시각.';
COMMENT ON COLUMN f3_campaign_target.created_at IS '레코드 생성 시각.';
COMMENT ON COLUMN f3_campaign_target.updated_at IS '레코드 최종 수정 시각. 서버가 갱신한다.';

COMMENT ON TABLE f3_campaign_target_evidence IS '최근 거절·결정권 없음 등 캠페인 대상 판정의 상담 로그 근거.';
COMMENT ON COLUMN f3_campaign_target_evidence.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN f3_campaign_target_evidence.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN f3_campaign_target_evidence.campaign_target_id IS '소속 캠페인 대상 식별자.';
COMMENT ON COLUMN f3_campaign_target_evidence.evidence_type IS '원문 인용 또는 추정 근거 유형.';
COMMENT ON COLUMN f3_campaign_target_evidence.interaction_id IS '연결된 상담 로그 식별자.';
COMMENT ON COLUMN f3_campaign_target_evidence.quote_text IS '상담 로그 인용문.';
COMMENT ON COLUMN f3_campaign_target_evidence.note IS '추정 근거 설명.';
COMMENT ON COLUMN f3_campaign_target_evidence.created_at IS '레코드 생성 시각.';

COMMENT ON TABLE f3_feedback IS '관심없음 사유와 판정 오류 피드백을 카드·후보·캠페인 대상별로 집계한다. F3-TR-03, F3-TR-07.';
COMMENT ON COLUMN f3_feedback.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN f3_feedback.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN f3_feedback.position_analysis_id IS '피드백 대상 포지션 카드 식별자.';
COMMENT ON COLUMN f3_feedback.match_candidate_evaluation_id IS '피드백 대상 중개 판정 후보 식별자.';
COMMENT ON COLUMN f3_feedback.campaign_target_id IS '피드백 대상 캠페인 대상 식별자.';
COMMENT ON COLUMN f3_feedback.reason IS '피드백 사유 코드.';
COMMENT ON COLUMN f3_feedback.detail IS '피드백 상세 설명.';
COMMENT ON COLUMN f3_feedback.created_by IS '생성 사용자 식별자.';
COMMENT ON COLUMN f3_feedback.created_at IS '레코드 생성 시각.';


-- ============================================================================
-- OPTIONAL: PGVECTOR SEMANTIC INDEX
-- ----------------------------------------------------------------------------
-- 기본 baseline은 vector 확장에 의존하지 않는다.
-- 의미 검색을 PostgreSQL + pgvector로 운영할 때 아래 별도 migration에서 적용한다.
--
-- CREATE EXTENSION IF NOT EXISTS vector;
--
-- CREATE TABLE interaction_embedding (
--     id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
--     brokerage_id BIGINT NOT NULL,
--     interaction_id BIGINT NOT NULL,
--     model_config_id BIGINT NOT NULL,
--     chunk_no INTEGER NOT NULL,
--     chunk_text TEXT NOT NULL,
--     embedding_dimension INTEGER NOT NULL,
--     embedding vector NOT NULL,
--     content_hash VARCHAR(64) NOT NULL,
--     metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
--     created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
--     updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
--     CONSTRAINT fk_interaction_embedding_interaction
--         FOREIGN KEY (brokerage_id, interaction_id)
--         REFERENCES client_interaction (brokerage_id, id),
--     CONSTRAINT fk_interaction_embedding_model
--         FOREIGN KEY (brokerage_id, model_config_id)
--         REFERENCES ai_model_config (brokerage_id, id),
--     CONSTRAINT uq_interaction_embedding
--         UNIQUE (brokerage_id, interaction_id, model_config_id, chunk_no),
--     CONSTRAINT uq_interaction_embedding_tenant_id
--         UNIQUE (brokerage_id, id)
-- );
--
-- 모델 차원이 확정되면 별도 migration으로 HNSW/IVFFlat 인덱스를 추가한다.


-- ============================================================================
-- SERVER RESPONSIBILITY NOTE
-- ----------------------------------------------------------------------------
-- 다음 항목은 DB 제약이나 DB 프로시저가 아니라 애플리케이션 서버에서 처리한다.
-- 상태 전이, 승인 여부, 개인정보 동의 유효성, 복수 관계 간 업무상 일치 여부, 소프트 삭제 시각, updated_at/row_version,
-- 상담 로그 append-only 정책, F2/F3 역할·모델 검증, 캐시 무효화, 최근 접촉일 갱신,
-- 알림 생성, 발송 집계, 감사 이벤트 생성, 개인정보 보유·파기 정책.
-- ============================================================================

COMMIT;
