-- PostgreSQL 15+
-- 매물장 세대 스펙과 구입장 공동중개·현 거주 임대차·업무 분류 필드 확장
-- depends: 008_CREATE_AUTHENTICATION


ALTER TABLE property_unit
    ADD COLUMN unit_type VARCHAR(30),
    ADD COLUMN is_expanded BOOLEAN,
    ADD COLUMN built_in_features TEXT,
    ADD COLUMN facility_condition TEXT;

ALTER TABLE property_requirement
    ADD COLUMN co_broker_party_id BIGINT,
    ADD COLUMN current_tenancy_expiry_date DATE,
    ADD COLUMN classification VARCHAR(100),
    ADD COLUMN workflow_stage VARCHAR(100),
    ADD CONSTRAINT fk_property_requirement_co_broker_party
        FOREIGN KEY (brokerage_id, co_broker_party_id)
        REFERENCES party (brokerage_id, id);

CREATE INDEX idx_property_requirement_current_tenancy_expiry
    ON property_requirement (
        brokerage_id,
        current_tenancy_expiry_date
    )
    WHERE current_tenancy_expiry_date IS NOT NULL
      AND is_deleted = FALSE;


COMMENT ON COLUMN property_unit.unit_type IS '세대 타입 원문 표기. 예: J1, J2.';
COMMENT ON COLUMN property_unit.is_expanded IS '세대 확장 여부.';
COMMENT ON COLUMN property_unit.built_in_features IS '붙박이·고정 옵션의 원문 내용.';
COMMENT ON COLUMN property_unit.facility_condition IS '세대 시설 상태의 원문 내용.';
COMMENT ON COLUMN property_requirement.co_broker_party_id IS '구입장 수요와 관련된 공동중개 상대 업소 party 식별자. party 유형은 Backend가 검증한다.';
COMMENT ON COLUMN property_requirement.current_tenancy_expiry_date IS '구입자의 현 거주지 임대차 만기일.';
COMMENT ON COLUMN property_requirement.classification IS '중개사무소가 정의하는 구입장 업무 분류 값.';
COMMENT ON COLUMN property_requirement.workflow_stage IS '완료 여부와 별도로 관리하는 자유 입력 진행단계.';
