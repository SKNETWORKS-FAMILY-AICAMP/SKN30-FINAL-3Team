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


COMMENT ON TABLE property_complex IS '아파트 단지 또는 오피스텔·빌라·상가 등 관리 대상 건물 묶음.';
COMMENT ON COLUMN property_complex.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN property_complex.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN property_complex.property_type IS '부동산 유형.';
COMMENT ON COLUMN property_complex.name IS '단지 또는 관리 대상 건물의 표시명.';
COMMENT ON COLUMN property_complex.road_address IS '도로명 주소.';
COMMENT ON COLUMN property_complex.memo IS '업무 메모.';
COMMENT ON COLUMN property_complex.extra_info IS '단지 부가 정보 JSON.';
COMMENT ON COLUMN property_complex.row_version IS '낙관적 동시성 제어용 버전 값. 서버가 증가시킨다.';
COMMENT ON COLUMN property_complex.is_deleted IS '소프트 삭제 여부.';
COMMENT ON COLUMN property_complex.deleted_at IS '소프트 삭제 처리 시각.';
COMMENT ON COLUMN property_complex.created_at IS '레코드 생성 시각.';
COMMENT ON COLUMN property_complex.updated_at IS '레코드 최종 수정 시각. 서버가 갱신한다.';

COMMENT ON TABLE property_unit IS '매물 여부와 무관한 세대 전수 대장의 기준 행. lifecycle_status는 현 임대차 상태와 별개의 업무 상태다.';
COMMENT ON COLUMN property_unit.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN property_unit.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN property_unit.complex_id IS '소속 단지 식별자.';
COMMENT ON COLUMN property_unit.building_number IS '동 번호.';
COMMENT ON COLUMN property_unit.unit_number IS '호 번호.';
COMMENT ON COLUMN property_unit.floor_number IS '층 표기.';
COMMENT ON COLUMN property_unit.orientation IS '세대 방향.';
COMMENT ON COLUMN property_unit.pyeong IS '세대의 평형 표기 값.';
COMMENT ON COLUMN property_unit.exclusive_area_sqm IS '세대 전용면적의 제곱미터 값.';
COMMENT ON COLUMN property_unit.supply_area_sqm IS '세대 공급면적의 제곱미터 값.';
COMMENT ON COLUMN property_unit.tenancy_status IS '현재 임대차 상태 값.';
COMMENT ON COLUMN property_unit.current_deposit_amount IS '현재 임대차 보증금.';
COMMENT ON COLUMN property_unit.current_monthly_rent_amount IS '현재 월 차임.';
COMMENT ON COLUMN property_unit.loan_amount IS '현재 융자 금액.';
COMMENT ON COLUMN property_unit.tenancy_expiry_date IS '현재 임대차 만기일.';
COMMENT ON COLUMN property_unit.tenancy_raw_text IS '현 임대차 원문 표기.';
COMMENT ON COLUMN property_unit.assigned_user_id IS '업무 담당 사용자 식별자.';
COMMENT ON COLUMN property_unit.memo IS '업무 메모.';
COMMENT ON COLUMN property_unit.custom_fields IS '사무소별 확장 필드 JSON.';
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
COMMENT ON COLUMN party.name IS '인물 또는 공동중개 업소의 표시명.';
COMMENT ON COLUMN party.alternate_name IS '업무용 별칭.';
COMMENT ON COLUMN party.memo IS '업무 메모.';
COMMENT ON COLUMN party.row_version IS '낙관적 동시성 제어용 버전 값. 서버가 증가시킨다.';
COMMENT ON COLUMN party.is_deleted IS '소프트 삭제 여부.';
COMMENT ON COLUMN party.deleted_at IS '소프트 삭제 처리 시각.';
COMMENT ON COLUMN party.created_at IS '레코드 생성 시각.';
COMMENT ON COLUMN party.updated_at IS '레코드 최종 수정 시각. 서버가 갱신한다.';

COMMENT ON TABLE party_contact IS '인물별 복수 연락처와 연락 가능 상태를 연락처 단위로 관리한다.';
COMMENT ON COLUMN party_contact.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN party_contact.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN party_contact.party_id IS '연결된 인물 식별자.';
COMMENT ON COLUMN party_contact.contact_method IS '연락처 종류.';
COMMENT ON COLUMN party_contact.contact_value IS '사용자가 입력한 연락처 원문.';
COMMENT ON COLUMN party_contact.normalized_contact_value IS '검색·중복 확인용 정규화 연락처 값. 서버가 생성해 저장한다.';
COMMENT ON COLUMN party_contact.contact_label IS '연락처 표시 라벨.';
COMMENT ON COLUMN party_contact.is_primary IS '주 연락처 여부.';
COMMENT ON COLUMN party_contact.contactability_status IS '해당 연락처의 연락 가능 상태.';
COMMENT ON COLUMN party_contact.restriction_reason IS '연락 제한 또는 수신 거부 사유.';
COMMENT ON COLUMN party_contact.row_version IS '낙관적 동시성 제어용 버전 값. 서버가 증가시킨다.';
COMMENT ON COLUMN party_contact.is_deleted IS '소프트 삭제 여부.';
COMMENT ON COLUMN party_contact.deleted_at IS '소프트 삭제 처리 시각.';
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

COMMENT ON TABLE property_listing IS '특정 세대가 시간에 따라 반복해서 매물화되는 개별 업무 건. 세대 원장과 분리한다.';
COMMENT ON COLUMN property_listing.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN property_listing.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN property_listing.unit_id IS '연결된 세대 식별자.';
COMMENT ON COLUMN property_listing.client_party_id IS '매물 의뢰인 식별자.';
COMMENT ON COLUMN property_listing.received_at IS '매물 접수일.';
COMMENT ON COLUMN property_listing.status IS '현재 상태 값. 상태 전이는 서버에서 관리한다.';
COMMENT ON COLUMN property_listing.is_sale_available IS '매매 조건 사용 여부.';
COMMENT ON COLUMN property_listing.sale_price IS '매매 희망 가격.';
COMMENT ON COLUMN property_listing.is_jeonse_available IS '전세 조건 사용 여부.';
COMMENT ON COLUMN property_listing.jeonse_deposit_amount IS '전세 보증금.';
COMMENT ON COLUMN property_listing.is_monthly_rent_available IS '월세 조건 사용 여부.';
COMMENT ON COLUMN property_listing.monthly_rent_deposit_amount IS '월세 보증금.';
COMMENT ON COLUMN property_listing.monthly_rent_amount IS '월 차임.';
COMMENT ON COLUMN property_listing.price_raw_text IS '가격 조건 원문.';
COMMENT ON COLUMN property_listing.handover_condition IS '명도 조건.';
COMMENT ON COLUMN property_listing.assigned_user_id IS '업무 담당 사용자 식별자.';
COMMENT ON COLUMN property_listing.memo IS '업무 메모.';
COMMENT ON COLUMN property_listing.custom_fields IS '사무소별 확장 필드 JSON.';
COMMENT ON COLUMN property_listing.row_version IS '낙관적 동시성 제어용 버전 값. 서버가 증가시킨다.';
COMMENT ON COLUMN property_listing.is_deleted IS '소프트 삭제 여부.';
COMMENT ON COLUMN property_listing.deleted_at IS '소프트 삭제 처리 시각.';
COMMENT ON COLUMN property_listing.created_at IS '레코드 생성 시각.';
COMMENT ON COLUMN property_listing.updated_at IS '레코드 최종 수정 시각. 서버가 갱신한다.';

COMMENT ON TABLE property_requirement IS '구입자별 희망 조건, 진행 상태, 공동중개 상대 업소와 현 거주지 임대차 정보를 관리하는 구입장 수요 건.';
COMMENT ON COLUMN property_requirement.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN property_requirement.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN property_requirement.party_id IS '연결된 인물 식별자.';
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
COMMENT ON COLUMN property_requirement.request_expiry_date IS '구입장 수요 의뢰의 업무 유효 종료일.';
COMMENT ON COLUMN property_requirement.status IS '현재 상태 값. 상태 전이는 서버에서 관리한다.';
COMMENT ON COLUMN property_requirement.assigned_user_id IS '업무 담당 사용자 식별자.';
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
COMMENT ON COLUMN property_requirement_complex.requirement_id IS '희망 단지를 등록한 구입장 수요 식별자.';
COMMENT ON COLUMN property_requirement_complex.complex_id IS '구입장 수요에 연결된 희망 단지 식별자.';
COMMENT ON COLUMN property_requirement_complex.preference_order IS '희망 단지 우선순위.';
COMMENT ON COLUMN property_requirement_complex.created_at IS '레코드 생성 시각.';

COMMENT ON TABLE client_interaction IS '상담 로그의 단일 원장. 로그는 append-only이며 삭제 대신 무효 처리하고 AI 제안 로그는 승인된 결과만 확정한다.';
COMMENT ON COLUMN client_interaction.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN client_interaction.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN client_interaction.interaction_at IS '이벤트 또는 상담이 발생한 시각.';
COMMENT ON COLUMN client_interaction.interaction_channel IS '상담 채널.';
COMMENT ON COLUMN client_interaction.communication_direction IS '연락 방향.';
COMMENT ON COLUMN client_interaction.interaction_result IS '상담 또는 연락 결과.';
COMMENT ON COLUMN client_interaction.counterparty_role IS '상대방의 세대 관계 역할.';
COMMENT ON COLUMN client_interaction.counterparty_index IS '같은 역할 상대방의 업무상 순번.';
COMMENT ON COLUMN client_interaction.interaction_content IS '본문 내용.';
COMMENT ON COLUMN client_interaction.party_id IS '연결된 인물 식별자.';
COMMENT ON COLUMN client_interaction.unit_id IS '연결된 세대 식별자.';
COMMENT ON COLUMN client_interaction.listing_id IS '연결된 매물 업무 건 식별자.';
COMMENT ON COLUMN client_interaction.requirement_id IS '상담 로그와 연결된 구입장 수요 식별자.';
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
