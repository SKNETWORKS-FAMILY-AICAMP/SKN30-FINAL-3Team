-- PostgreSQL 15+
-- 최소 원장: 목록, 행 추가, 상담 자동화 저장 대상, 중개 판단 조회 원천
-- depends: 001_CREATE_BROKERAGE_PLATFORM


CREATE TABLE property_complex (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id        BIGINT NOT NULL,
    property_type       VARCHAR(30) NOT NULL DEFAULT 'APARTMENT',
    name                VARCHAR(150) NOT NULL,
    road_address        TEXT,
    memo                TEXT,
    extra_info          JSONB NOT NULL DEFAULT '{}'::jsonb,
    row_version         BIGINT NOT NULL DEFAULT 1,
    is_deleted          BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at          TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_property_complex_brokerage
        FOREIGN KEY (brokerage_id)
        REFERENCES brokerage (id),
    CONSTRAINT uq_property_complex_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE INDEX idx_property_complex_name
    ON property_complex (brokerage_id, name)
    WHERE is_deleted = FALSE;

CREATE TABLE property_unit (
    id                          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id                BIGINT NOT NULL,
    complex_id                  BIGINT NOT NULL,
    building_number             VARCHAR(50),
    unit_number                 VARCHAR(50) NOT NULL,
    floor_number                VARCHAR(20),
    orientation                 VARCHAR(30),
    pyeong                      NUMERIC(6,2),
    exclusive_area_sqm          NUMERIC(10,2),
    supply_area_sqm             NUMERIC(10,2),
    tenancy_status              VARCHAR(30),
    current_deposit_amount      BIGINT,
    current_monthly_rent_amount BIGINT,
    loan_amount                 BIGINT,
    tenancy_expiry_date         DATE,
    tenancy_raw_text            TEXT,
    assigned_user_id            BIGINT,
    memo                        TEXT,
    custom_fields               JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_contact_at             TIMESTAMPTZ,
    lifecycle_status            VARCHAR(30) NOT NULL DEFAULT 'NORMAL',
    row_version                 BIGINT NOT NULL DEFAULT 1,
    is_deleted                  BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at                  TIMESTAMPTZ,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_property_unit_complex
        FOREIGN KEY (brokerage_id, complex_id)
        REFERENCES property_complex (brokerage_id, id),
    CONSTRAINT fk_property_unit_assigned_user
        FOREIGN KEY (brokerage_id, assigned_user_id)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_property_unit_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE UNIQUE INDEX uq_property_unit_location
    ON property_unit (
        brokerage_id,
        complex_id,
        COALESCE(building_number, ''),
        unit_number
    )
    WHERE is_deleted = FALSE;

CREATE INDEX idx_property_unit_candidate_lookup
    ON property_unit (
        brokerage_id,
        complex_id,
        pyeong,
        exclusive_area_sqm
    )
    WHERE is_deleted = FALSE;

CREATE INDEX idx_property_unit_tenancy_expiry
    ON property_unit (brokerage_id, tenancy_expiry_date)
    WHERE tenancy_expiry_date IS NOT NULL
      AND is_deleted = FALSE;

CREATE TABLE party (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id        BIGINT NOT NULL,
    party_type          VARCHAR(20) NOT NULL,
    name                VARCHAR(150) NOT NULL,
    alternate_name      VARCHAR(150),
    memo                TEXT,
    row_version         BIGINT NOT NULL DEFAULT 1,
    is_deleted          BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at          TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_party_brokerage
        FOREIGN KEY (brokerage_id)
        REFERENCES brokerage (id),
    CONSTRAINT uq_party_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE INDEX idx_party_name
    ON party (brokerage_id, name)
    WHERE is_deleted = FALSE;

CREATE TABLE party_contact (
    id                          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id                BIGINT NOT NULL,
    party_id                    BIGINT NOT NULL,
    contact_method              VARCHAR(20) NOT NULL DEFAULT 'PHONE',
    contact_value               VARCHAR(320) NOT NULL,
    normalized_contact_value    VARCHAR(320) NOT NULL,
    contact_label               VARCHAR(50),
    is_primary                  BOOLEAN NOT NULL DEFAULT FALSE,
    contactability_status       VARCHAR(20) NOT NULL DEFAULT 'UNKNOWN',
    restriction_reason          TEXT,
    row_version                 BIGINT NOT NULL DEFAULT 1,
    is_deleted                  BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at                  TIMESTAMPTZ,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_party_contact_party
        FOREIGN KEY (brokerage_id, party_id)
        REFERENCES party (brokerage_id, id),
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

CREATE UNIQUE INDEX uq_unit_party_relation_current_role
    ON property_unit_party_relation (
        brokerage_id,
        unit_id,
        role,
        role_index
    )
    WHERE valid_to IS NULL;

CREATE INDEX idx_unit_party_relation_party
    ON property_unit_party_relation (brokerage_id, party_id, role);

CREATE TABLE property_listing (
    id                              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id                    BIGINT NOT NULL,
    unit_id                         BIGINT NOT NULL,
    client_party_id                 BIGINT,
    received_at                     DATE NOT NULL DEFAULT CURRENT_DATE,
    status                          VARCHAR(30) NOT NULL DEFAULT 'RECEIVED',
    is_sale_available               BOOLEAN NOT NULL DEFAULT FALSE,
    sale_price                      BIGINT,
    is_jeonse_available             BOOLEAN NOT NULL DEFAULT FALSE,
    jeonse_deposit_amount           BIGINT,
    is_monthly_rent_available       BOOLEAN NOT NULL DEFAULT FALSE,
    monthly_rent_deposit_amount     BIGINT,
    monthly_rent_amount             BIGINT,
    price_raw_text                  TEXT,
    handover_condition              VARCHAR(100),
    assigned_user_id                BIGINT,
    memo                            TEXT,
    custom_fields                   JSONB NOT NULL DEFAULT '{}'::jsonb,
    row_version                     BIGINT NOT NULL DEFAULT 1,
    is_deleted                      BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at                      TIMESTAMPTZ,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_property_listing_unit
        FOREIGN KEY (brokerage_id, unit_id)
        REFERENCES property_unit (brokerage_id, id),
    CONSTRAINT fk_property_listing_client_party
        FOREIGN KEY (brokerage_id, client_party_id)
        REFERENCES party (brokerage_id, id),
    CONSTRAINT fk_property_listing_assigned_user
        FOREIGN KEY (brokerage_id, assigned_user_id)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_property_listing_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE INDEX idx_property_listing_candidate_lookup
    ON property_listing (
        brokerage_id,
        status,
        sale_price,
        jeonse_deposit_amount,
        monthly_rent_amount
    )
    WHERE is_deleted = FALSE;

CREATE TABLE property_requirement (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id            BIGINT NOT NULL,
    party_id                BIGINT NOT NULL,
    received_at             DATE NOT NULL DEFAULT CURRENT_DATE,
    demand_type             VARCHAR(20) NOT NULL,
    desired_pyeongs         NUMERIC(6,2)[],
    min_area_sqm            NUMERIC(10,2),
    max_area_sqm            NUMERIC(10,2),
    area_requirement_raw_text TEXT,
    min_budget_amount       BIGINT,
    max_budget_amount       BIGINT,
    budget_raw_text         TEXT,
    desired_move_in_date    DATE,
    move_in_date_raw_text   TEXT,
    request_expiry_date     DATE,
    status                  VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    assigned_user_id        BIGINT,
    memo                    TEXT,
    custom_fields           JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_contact_at         TIMESTAMPTZ,
    row_version             BIGINT NOT NULL DEFAULT 1,
    is_deleted              BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at              TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_property_requirement_party
        FOREIGN KEY (brokerage_id, party_id)
        REFERENCES party (brokerage_id, id),
    CONSTRAINT fk_property_requirement_assigned_user
        FOREIGN KEY (brokerage_id, assigned_user_id)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_property_requirement_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE INDEX idx_property_requirement_candidate_lookup
    ON property_requirement (
        brokerage_id,
        demand_type,
        status,
        min_budget_amount,
        max_budget_amount
    )
    WHERE is_deleted = FALSE;

CREATE TABLE property_requirement_complex (
    brokerage_id        BIGINT NOT NULL,
    requirement_id      BIGINT NOT NULL,
    complex_id          BIGINT NOT NULL,
    preference_order    SMALLINT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_property_requirement_complex
        PRIMARY KEY (brokerage_id, requirement_id, complex_id),
    CONSTRAINT fk_requirement_complex_requirement
        FOREIGN KEY (brokerage_id, requirement_id)
        REFERENCES property_requirement (brokerage_id, id),
    CONSTRAINT fk_requirement_complex_complex
        FOREIGN KEY (brokerage_id, complex_id)
        REFERENCES property_complex (brokerage_id, id)
);

CREATE INDEX idx_requirement_complex_lookup
    ON property_requirement_complex (
        brokerage_id,
        complex_id,
        requirement_id
    );

CREATE TABLE client_interaction (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id            BIGINT NOT NULL,
    interaction_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    interaction_channel     VARCHAR(20) NOT NULL DEFAULT 'CALL',
    communication_direction VARCHAR(20),
    interaction_result      VARCHAR(20),
    counterparty_role       VARCHAR(20),
    counterparty_index      SMALLINT,
    interaction_content     TEXT NOT NULL,
    party_id                BIGINT,
    unit_id                 BIGINT,
    listing_id              BIGINT,
    requirement_id          BIGINT,
    related_context         JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_type             VARCHAR(20) NOT NULL DEFAULT 'HUMAN',
    approval_status         VARCHAR(20) NOT NULL DEFAULT 'NOT_REQUIRED',
    approved_by             BIGINT,
    approved_at             TIMESTAMPTZ,
    source_metadata         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by              BIGINT,
    is_voided               BOOLEAN NOT NULL DEFAULT FALSE,
    void_reason             TEXT,
    voided_by               BIGINT,
    voided_at               TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_client_interaction_brokerage
        FOREIGN KEY (brokerage_id)
        REFERENCES brokerage (id),
    CONSTRAINT fk_client_interaction_party
        FOREIGN KEY (brokerage_id, party_id)
        REFERENCES party (brokerage_id, id),
    CONSTRAINT fk_client_interaction_unit
        FOREIGN KEY (brokerage_id, unit_id)
        REFERENCES property_unit (brokerage_id, id),
    CONSTRAINT fk_client_interaction_listing
        FOREIGN KEY (brokerage_id, listing_id)
        REFERENCES property_listing (brokerage_id, id),
    CONSTRAINT fk_client_interaction_requirement
        FOREIGN KEY (brokerage_id, requirement_id)
        REFERENCES property_requirement (brokerage_id, id),
    CONSTRAINT fk_client_interaction_approved_by
        FOREIGN KEY (brokerage_id, approved_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT fk_client_interaction_created_by
        FOREIGN KEY (brokerage_id, created_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT fk_client_interaction_voided_by
        FOREIGN KEY (brokerage_id, voided_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_client_interaction_tenant_id
        UNIQUE (brokerage_id, id),
    CONSTRAINT ck_client_interaction_has_target
        CHECK (
            num_nonnulls(
                party_id,
                unit_id,
                listing_id,
                requirement_id
            ) >= 1
        )
);

CREATE INDEX idx_client_interaction_unit
    ON client_interaction (brokerage_id, unit_id, interaction_at DESC)
    WHERE unit_id IS NOT NULL
      AND is_voided = FALSE;

CREATE INDEX idx_client_interaction_requirement
    ON client_interaction (brokerage_id, requirement_id, interaction_at DESC)
    WHERE requirement_id IS NOT NULL
      AND is_voided = FALSE;

CREATE INDEX idx_client_interaction_party
    ON client_interaction (brokerage_id, party_id, interaction_at DESC)
    WHERE party_id IS NOT NULL
      AND is_voided = FALSE;
