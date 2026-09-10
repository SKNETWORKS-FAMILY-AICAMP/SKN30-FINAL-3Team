-- PostgreSQL 15+
-- 일정·할 일 조회가 쓰는 장부 날짜 컬럼의 부분 인덱스
-- depends: 016_ALTER_AGENT_EXECUTION_JUDGMENT_CLAIM_INDEX


-- 일정 목록은 사무소 단위로 여러 날짜 컬럼에 범위 조건을 건다. 세대 임대차 만기(002)와 손님
-- 현 거주지 만기(009)는 이미 부분 인덱스가 있고, 나머지 다섯 갈래는 없어 전체 스캔이 된다.
--
-- 각 인덱스의 WHERE 는 조회 조건과 같은 모양으로 둔다. 조건이 어긋나면 인덱스를 두고도 쓰이지
-- 않는다. 조회는 기한을 컬럼에서 계산하지 않고 상수 쪽으로 옮겨 원본 컬럼의 범위로 비교하므로
-- 아래 인덱스가 그대로 쓰인다.

CREATE INDEX idx_property_requirement_request_expiry
    ON property_requirement (brokerage_id, request_expiry_date)
    WHERE request_expiry_date IS NOT NULL
      AND is_deleted = FALSE;

CREATE INDEX idx_property_requirement_desired_move_in
    ON property_requirement (brokerage_id, desired_move_in_date)
    WHERE desired_move_in_date IS NOT NULL
      AND is_deleted = FALSE;

-- 재연락 대상은 마지막 접촉 시각의 범위로 찾는다.
CREATE INDEX idx_property_requirement_last_contact
    ON property_requirement (brokerage_id, last_contact_at)
    WHERE last_contact_at IS NOT NULL
      AND is_deleted = FALSE;

CREATE INDEX idx_property_unit_last_contact
    ON property_unit (brokerage_id, last_contact_at)
    WHERE last_contact_at IS NOT NULL
      AND is_deleted = FALSE;

-- 매물 조건 재확인 대상은 접수일의 범위로 찾는다. received_at 은 NOT NULL 이라 조건에 넣지 않는다.
CREATE INDEX idx_property_listing_received_at
    ON property_listing (brokerage_id, received_at)
    WHERE is_deleted = FALSE;
