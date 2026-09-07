-- PostgreSQL 15+
-- F3 파이프라인 검증용 합성 장부. migration 이 아니며 prod 에 적용하지 않는다.
--
-- ## 이 파일이 만드는 것
--
-- 합성 사무소 1곳, 개발 사용자 1명, 단지 5개, 세대 36개, 인물 87명, 매물 36건,
-- 구입장 48건, 상담 로그 169건. AI 모델 설정은 이 파일 다음에 선택한
-- model-profiles/*.sql 한 개가 만든다.
--
-- ## 이 파일이 만들지 않는 것
--
-- agent_run, negotiation_position_analysis, match_evaluation 은 넣지 않는다. 그 행들은
-- Worker 가 직접 만들어야 파이프라인 전체가 검증된다. 결과를 미리 넣으면 무엇이 동작하고
-- 무엇이 안 하는지 구분할 수 없다.
--
-- API Key, 토큰, 비밀번호도 넣지 않는다. app_user.password_hash 는 개발 로그인을 막는
-- 고정 표식이며 해시가 아니다.
--
-- ## 데이터 원칙
--
-- 모든 이름은 완전한 가상이며 사무소명과 사용자명에 F3_SYNTHETIC 표식을 붙인다. 연락처는
-- 프로젝트가 합성 fixture에 사용하는 010-0000-XXXX 테스트 형식만 쓴다. 실제 상담 원문을
-- 변형해 쓰지 않는다.
--
-- 모든 날짜는 CURRENT_DATE 와 now() 기준 상대값이다. 언제 실행해도 입주일·만기일이 이미
-- 지나 있지 않고, 접수일은 과거에 있다.
--
-- 각 행은 custom_fields->>'seed_key'(단지는 extra_info, 인물은 memo)로 자기 케이스 키를
-- 갖는다. 검증 쿼리와 테스트 절차가 로컬마다 다른 자동 증가 ID 대신 이 키로 행을 찾는다.
--
-- ## 재실행
--
-- 001_F3_SYNTHETIC_RESET.sql 을 먼저 돌리고 이 파일과 허용된 model profile 한 개를 적용한다.
-- 순서대로 몇 번을 반복해도 같은 상태가 된다. seed 는 migration 실행기가 관리하지 않으므로
-- transaction 을 이 파일이 직접 연다.
--
-- ## 케이스 설계 (기대 결과)
--
-- | 케이스 | 앵커 | 앵커 seed_key | 기대 후보 수 | 확인 대상 |
-- |---|---|---|---:|---|
-- | A | LISTING | L1 (매매 28.8억) | 3 | 강한·약한·기각 후보가 한 실행에 함께 나온다 |
-- | B | REQUIREMENT | R1 (매수 29억) | 2 | 반대 방향 앵커도 같은 파이프라인을 탄다 |
-- | C | LISTING | L5 (월세) | 0 | 해당 단지를 희망하는 월세 구입장이 없다 |
-- | D | REQUIREMENT | R8 (매도) | 0 | 대응하는 매물 거래 유형이 없는 구분이다 |
-- | E | LISTING | L4 (전세 21.5억) | 1 | SQL 은 통과하지만 시점이 결정적으로 어긋난다 |
-- | F | LISTING | BL01 (대량 매매) | 19 | 전체 후보와 카드화 상위 5건을 나눠 저장한다 |
-- | G | REQUIREMENT | BR01 (대량 매수) | 12 | 대량 장부에서도 반대 방향 후보를 찾는다 |
-- | H | LISTING | BL13 (대량 전세) | 12 | 전세 가격 축으로 다수 후보를 찾는다 |
-- | I | LISTING | BL23 (대량 월세) | 10 | 월세 보증금·월 차임 축을 보존한다 |
--
-- 기대 후보 수는 결정적 SQL 추출의 결과이므로 고정값으로 검증한다. 등급과 문장은 모델이
-- 정하므로 고정하지 않는다. 003_F3_SYNTHETIC_VERIFY.sql 을 참고한다.

\set ON_ERROR_STOP on

BEGIN;


-- ── 사무소와 사용자 ───────────────────────────────────────────────────────────
--
-- 이 두 행만 "없을 때만 만든다". 001 이 두 행을 남기므로 재실행해도 brokerage_id 가
-- 바뀌지 않는다. ID 가 고정돼야 backend/.env 의 AUTH_DEVELOPMENT_BROKERAGE_ID 를 처음
-- 한 번만 적으면 된다.

INSERT INTO brokerage (name, business_registration_number, settings, status)
SELECT
    'F3_SYNTHETIC 합성중개사무소',
    NULL,
    jsonb_build_object('seed_key', 'B1', 'purpose', 'F3 pipeline synthetic test'),
    'ACTIVE'
WHERE NOT EXISTS (
    SELECT 1 FROM brokerage WHERE name = 'F3_SYNTHETIC 합성중개사무소'
);

-- password_hash 는 해시가 아니라 개발 로그인을 막는 고정 표식이다. 이 계정은
-- AUTH_DEVELOPMENT_* 개발 세션으로만 사용하고 비밀번호 로그인은 성립하지 않는다.
INSERT INTO app_user (brokerage_id, login_id, password_hash, display_name, role, is_active)
SELECT b.id, 'f3_synthetic_dev', '!development-login-disabled!', 'F3_SYNTHETIC 개발자', 'OWNER', TRUE
FROM brokerage b
WHERE b.name = 'F3_SYNTHETIC 합성중개사무소'
  AND NOT EXISTS (
      SELECT 1 FROM app_user u
      WHERE u.brokerage_id = b.id AND u.login_id = 'f3_synthetic_dev'
  );


-- ── 단지 ─────────────────────────────────────────────────────────────────────

INSERT INTO property_complex (brokerage_id, property_type, name, road_address, memo, extra_info)
SELECT
    t.brokerage_id, s.property_type, s.name, s.road_address, s.memo,
    jsonb_build_object('seed_key', s.seed_key)
FROM (
    SELECT id AS brokerage_id FROM brokerage WHERE name = 'F3_SYNTHETIC 합성중개사무소'
) t
CROSS JOIN (
    VALUES
        ('C1', 'APARTMENT', 'F3_SYNTHETIC 가온마을', '가상특별시 합성구 예시로 100', '합성 테스트 단지. 매매·전세 케이스의 기준 단지다.'),
        ('C2', 'OFFICETEL', 'F3_SYNTHETIC 나루오피스텔', '가상특별시 합성구 예시로 200', '합성 테스트 단지. 월세 케이스 전용이다.')
) AS s(seed_key, property_type, name, road_address, memo);


-- ── 세대 ─────────────────────────────────────────────────────────────────────
--
-- 매물이 달리지 않은 세대(U6)를 일부러 남겨 둔다. 세대 전수 대장에서 매물이 아닌 세대가
-- 다수인 것이 정상이다.

INSERT INTO property_unit (
    brokerage_id, complex_id, building_number, unit_number, floor_number, orientation, unit_type,
    pyeong, exclusive_area_sqm, supply_area_sqm, tenancy_status,
    current_deposit_amount, current_monthly_rent_amount, tenancy_expiry_date, tenancy_raw_text,
    is_expanded, built_in_features, facility_condition,
    assigned_user_id, memo, custom_fields, lifecycle_status
)
SELECT
    t.brokerage_id, c.id, s.building_number, s.unit_number, s.floor_number, s.orientation, s.unit_type,
    s.pyeong, s.exclusive_area_sqm, s.supply_area_sqm, s.tenancy_status,
    s.current_deposit_amount, s.current_monthly_rent_amount,
    -- 만기일은 항상 미래다. 테스트 시점에 이미 지나 있으면 시점 판정이 성립하지 않는다.
    CASE WHEN s.tenancy_expiry_offset_days IS NULL
         THEN NULL
         ELSE CURRENT_DATE + s.tenancy_expiry_offset_days
    END,
    s.tenancy_raw_text, s.is_expanded, s.built_in_features, s.facility_condition,
    t.user_id, s.memo, jsonb_build_object('seed_key', s.seed_key), 'NORMAL'
FROM (
    SELECT b.id AS brokerage_id, u.id AS user_id
    FROM brokerage b
    JOIN app_user u ON u.brokerage_id = b.id AND u.login_id = 'f3_synthetic_dev'
    WHERE b.name = 'F3_SYNTHETIC 합성중개사무소'
) t
CROSS JOIN (
    VALUES
        ('U1', 'C1', '101', '1201', '12', '남',    'J1', 33.45::numeric, 110.58::numeric, 141.20::numeric,
         '입주', NULL::bigint, NULL::bigint, NULL::integer, NULL::text,
         TRUE, '붙박이장, 에어컨 5', '전체 수리 완료',
         '케이스 A 앵커 세대. 공동명의 소유자 2인이 거주 중이다.'),
        ('U2', 'C1', '101', '902',  '9',  '남남동', 'J2', 25.70, 84.95, 109.60,
         '명도', NULL, NULL, 30, '만기후 명도 완료',
         FALSE, '붙박이장', '도배 완료',
         '케이스 E 앵커 세대. 임차인 명도가 끝나 즉시 입주가 가능하다.'),
        ('U3', 'C1', '102', '501',  '5',  '남',    'J1', 33.45, 110.58, 141.20,
         '입주', NULL, NULL, NULL, NULL,
         TRUE, '붙박이장', '부분 수리',
         '케이스 B 후보 세대.'),
        ('U4', 'C1', '102', '1802', '18', '남서',  'J3', 44.20, 145.30, 184.70,
         '입주', NULL, NULL, NULL, NULL,
         TRUE, '붙박이장, 시스템에어컨', '전체 수리 완료',
         '케이스 B 예산 상한 초과 확인용 세대.'),
        ('U5', 'C2', NULL,  '203',  '2',  '동',    NULL, 18.10, 59.80, 78.40,
         '월환', 50000000, 3800000, 60, '5000/380',
         FALSE, '풀옵션', '입주 청소 완료',
         '케이스 C 앵커 세대. 월세 전용이다.'),
        ('U6', 'C1', '103', '704',  '7',  '남동',  'J1', 33.45, 110.58, 141.20,
         '자가', NULL, NULL, NULL, NULL,
         FALSE, NULL, NULL,
         '매물로 접수되지 않은 세대. 전수 대장에 매물 아닌 세대가 남아 있는 것이 정상이다.')
) AS s(
    seed_key, complex_key, building_number, unit_number, floor_number, orientation, unit_type,
    pyeong, exclusive_area_sqm, supply_area_sqm, tenancy_status,
    current_deposit_amount, current_monthly_rent_amount, tenancy_expiry_offset_days, tenancy_raw_text,
    is_expanded, built_in_features, facility_condition, memo
)
JOIN property_complex c
  ON c.brokerage_id = t.brokerage_id
 AND c.extra_info->>'seed_key' = s.complex_key;


-- ── 인물 ─────────────────────────────────────────────────────────────────────
--
-- 수요 측 인물에게만 개인정보 활용 동의 시각을 넣는다. 동의가 없으면 구입장 저장이
-- 거절되므로 구입장을 가진 인물은 모두 동의 상태여야 한다.

INSERT INTO party (brokerage_id, party_type, name, alternate_name, memo, privacy_consent_at, privacy_consent_by)
SELECT
    t.brokerage_id, s.party_type, s.name, s.alternate_name,
    'seed_key=' || s.seed_key,
    CASE WHEN s.has_consent THEN now() ELSE NULL END,
    CASE WHEN s.has_consent THEN t.user_id ELSE NULL END
FROM (
    SELECT b.id AS brokerage_id, u.id AS user_id
    FROM brokerage b
    JOIN app_user u ON u.brokerage_id = b.id AND u.login_id = 'f3_synthetic_dev'
    WHERE b.name = 'F3_SYNTHETIC 합성중개사무소'
) t
CROSS JOIN (
    VALUES
        ('P_OWNER1', 'PERSON',       'F3_SYNTHETIC 소유자일', '1201 공동명의 남편'::text, FALSE),
        ('P_OWNER2', 'PERSON',       'F3_SYNTHETIC 소유자이', '1201 공동명의 배우자',     FALSE),
        ('P_OWNER3', 'PERSON',       'F3_SYNTHETIC 소유자삼', '902 전세 물건',            FALSE),
        ('P_OWNER4', 'PERSON',       'F3_SYNTHETIC 소유자사', '501 갈아타기',             FALSE),
        ('P_OWNER5', 'PERSON',       'F3_SYNTHETIC 소유자오', '1802 대형',                FALSE),
        ('P_OWNER6', 'PERSON',       'F3_SYNTHETIC 소유자육', '203 월세',                 FALSE),
        ('P_TENANT1','PERSON',       'F3_SYNTHETIC 임차인일', '902 퇴거 완료',            FALSE),
        ('P_D1',     'PERSON',       'F3_SYNTHETIC 매수손님일', '29억 현금 준비',         TRUE),
        ('P_D2',     'PERSON',       'F3_SYNTHETIC 매수손님이', '26억대 대출 대기',       TRUE),
        ('P_D3',     'PERSON',       'F3_SYNTHETIC 매수손님삼', '44평 이상만',            TRUE),
        ('P_D4',     'PERSON',       'F3_SYNTHETIC 전세손님일', '만기 맞춰서만',          TRUE),
        ('P_D5',     'PERSON',       'F3_SYNTHETIC 매수손님사', '20억 이하',              TRUE),
        ('P_D6',     'PERSON',       'F3_SYNTHETIC 매수손님오', '나루오피스텔만',         TRUE),
        ('P_D7',     'PERSON',       'F3_SYNTHETIC 매수손님육', '타사 계약 완료',         TRUE),
        ('P_D8',     'PERSON',       'F3_SYNTHETIC 매도손님일', '시세 확인 중',           TRUE),
        ('P_CO_BROKER', 'ORGANIZATION', 'F3_SYNTHETIC 공동중개업소', NULL,                FALSE),
        ('P_TENANT2','PERSON',       'F3_SYNTHETIC 임차인이', '203 현 거주',              FALSE)
) AS s(seed_key, party_type, name, alternate_name, has_consent);

-- 연락처는 프로젝트의 합성 fixture와 같은 010-0000-XXXX 테스트 형식만 사용한다.
INSERT INTO party_contact (
    brokerage_id, party_id, contact_method, contact_value, normalized_contact_value,
    contact_label, is_primary, contactability_status
)
SELECT
    p.brokerage_id,
    p.id,
    'PHONE',
    '010-0000-' || lpad(row_number() OVER (ORDER BY p.id)::text, 4, '0'),
    '01000000' || lpad(row_number() OVER (ORDER BY p.id)::text, 4, '0'),
    '대표',
    TRUE,
    'UNKNOWN'
FROM party p
JOIN brokerage b ON b.id = p.brokerage_id
WHERE b.name = 'F3_SYNTHETIC 합성중개사무소';


-- ── 세대와 인물의 관계 ────────────────────────────────────────────────────────
--
-- U1 은 공동명의 2인이다. 매물 대리 카드가 "단독 결정 불가"를 양보 불가 조건으로 잡는
-- 근거가 여기와 상담 로그 양쪽에 있어야 한다.

INSERT INTO property_unit_party_relation (
    brokerage_id, unit_id, party_id, role, role_index, is_primary, is_co_owner, valid_from, memo
)
SELECT
    t.brokerage_id, u.id, p.id, s.role, s.role_index, s.is_primary, s.is_co_owner,
    CURRENT_DATE - 400, s.memo
FROM (
    SELECT id AS brokerage_id FROM brokerage WHERE name = 'F3_SYNTHETIC 합성중개사무소'
) t
CROSS JOIN (
    VALUES
        ('U1', 'P_OWNER1',  'LANDLORD', 1::smallint, TRUE,  TRUE,  '공동명의 1'::text),
        ('U1', 'P_OWNER2',  'LANDLORD', 2,           FALSE, TRUE,  '공동명의 2'),
        ('U2', 'P_OWNER3',  'LANDLORD', 1,           TRUE,  FALSE, NULL),
        ('U2', 'P_TENANT1', 'TENANT',   1,           TRUE,  FALSE, '명도 완료'),
        ('U3', 'P_OWNER4',  'LANDLORD', 1,           TRUE,  FALSE, NULL),
        ('U4', 'P_OWNER5',  'LANDLORD', 1,           TRUE,  FALSE, NULL),
        ('U5', 'P_OWNER6',  'LANDLORD', 1,           TRUE,  FALSE, NULL),
        ('U5', 'P_TENANT2', 'TENANT',   1,           TRUE,  FALSE, '현 월세 거주'),
        ('U6', 'P_OWNER1',  'LANDLORD', 1,           TRUE,  FALSE, NULL)
) AS s(unit_key, party_key, role, role_index, is_primary, is_co_owner, memo)
JOIN property_unit u
  ON u.brokerage_id = t.brokerage_id AND u.custom_fields->>'seed_key' = s.unit_key
JOIN party p
  ON p.brokerage_id = t.brokerage_id AND p.memo = 'seed_key=' || s.party_key;


-- ── 매물 ─────────────────────────────────────────────────────────────────────
--
-- 매물 1건은 거래 가능 플래그를 **하나만** 켠다. 앵커 카드의 첫 번째 거래 유형이 후보
-- 조회의 가격 축이 되므로, 유형이 둘 이상이면 어느 축으로 조회했는지가 모델 출력 순서에
-- 좌우된다. 테스트 데이터에서는 그 흔들림을 없앤다.
--
-- L6 은 종료된 매물이다. 활성 상태 조건이 실제로 걸리는지 확인하는 행이며 후보로 올라오면
-- 안 된다.

INSERT INTO property_listing (
    brokerage_id, unit_id, client_party_id, received_at, status,
    is_sale_available, sale_price,
    is_jeonse_available, jeonse_deposit_amount,
    is_monthly_rent_available, monthly_rent_deposit_amount, monthly_rent_amount,
    price_raw_text, handover_condition, assigned_user_id, memo, custom_fields
)
SELECT
    t.brokerage_id, u.id, p.id,
    -- 접수일은 항상 과거다. 최신성 점수가 미래 접수로 부풀지 않는다.
    CURRENT_DATE - s.received_offset_days,
    s.status,
    s.is_sale_available, s.sale_price,
    s.is_jeonse_available, s.jeonse_deposit_amount,
    s.is_monthly_rent_available, s.monthly_rent_deposit_amount, s.monthly_rent_amount,
    s.price_raw_text, s.handover_condition, t.user_id, s.memo,
    jsonb_build_object('seed_key', s.seed_key)
FROM (
    SELECT b.id AS brokerage_id, u2.id AS user_id
    FROM brokerage b
    JOIN app_user u2 ON u2.brokerage_id = b.id AND u2.login_id = 'f3_synthetic_dev'
    WHERE b.name = 'F3_SYNTHETIC 합성중개사무소'
) t
CROSS JOIN (
    VALUES
        ('L1', 'U1', 'P_OWNER1', 7::integer, 'RECEIVED',
         TRUE,  2880000000::bigint, FALSE, NULL::bigint, FALSE, NULL::bigint, NULL::bigint,
         '28,8', '협의', '케이스 A 앵커. 매매 28.8억.'::text),
        ('L2', 'U3', 'P_OWNER4', 14, 'RECEIVED',
         TRUE,  3050000000, FALSE, NULL, FALSE, NULL, NULL,
         '30,5', '2월중', '케이스 B 후보. 예산 상한 안쪽이지만 가격 차가 있다.'),
        ('L3', 'U4', 'P_OWNER5', 21, 'RECEIVED',
         TRUE,  3900000000, FALSE, NULL, FALSE, NULL, NULL,
         '39억', '협의', '케이스 B 제외 확인용. 예산 상한을 넘는다.'),
        ('L4', 'U2', 'P_OWNER3', 5,  'RECEIVED',
         FALSE, NULL, TRUE, 2150000000, FALSE, NULL, NULL,
         '21,5', '즉시', '케이스 E 앵커. 전세 21.5억, 즉시 입주만 받는다.'),
        ('L5', 'U5', 'P_OWNER6', 3,  'RECEIVED',
         FALSE, NULL, FALSE, NULL, TRUE, 50000000, 3800000,
         '5000/380', '만기후', '케이스 C 앵커. 해당 단지를 희망하는 월세 구입장이 없다.'),
        ('L6', 'U1', 'P_OWNER1', 400, 'CLOSED',
         TRUE,  2700000000, FALSE, NULL, FALSE, NULL, NULL,
         '27억', '협의', '종료된 과거 매물. 활성 상태 조건 확인용이며 후보로 올라오면 안 된다.')
) AS s(
    seed_key, unit_key, client_party_key, received_offset_days, status,
    is_sale_available, sale_price, is_jeonse_available, jeonse_deposit_amount,
    is_monthly_rent_available, monthly_rent_deposit_amount, monthly_rent_amount,
    price_raw_text, handover_condition, memo
)
JOIN property_unit u
  ON u.brokerage_id = t.brokerage_id AND u.custom_fields->>'seed_key' = s.unit_key
JOIN party p
  ON p.brokerage_id = t.brokerage_id AND p.memo = 'seed_key=' || s.client_party_key;


-- ── 구입장 ───────────────────────────────────────────────────────────────────
--
-- 케이스 A 앵커(L1, 매매 28.8억)의 예산 하한은 28.8억의 90% 인 25.92억이다. R1·R2·R3 만
-- 이 하한과 구분·활성 상태·희망 단지 조건을 모두 통과한다.
--
-- R5 는 예산 하한 미달, R6 은 다른 단지만 희망, R7 은 종료 상태, R4 는 다른 구분,
-- R8 은 매물의 반대편이 아닌 구분이라 각각 다른 이유로 걸러진다.

INSERT INTO property_requirement (
    brokerage_id, party_id, received_at, demand_type,
    desired_pyeongs, min_area_sqm, max_area_sqm, area_requirement_raw_text,
    min_budget_amount, max_budget_amount, budget_raw_text,
    desired_move_in_date, move_in_date_raw_text, request_expiry_date,
    current_tenancy_expiry_date, co_broker_party_id,
    classification, workflow_stage, status, assigned_user_id, memo, custom_fields
)
SELECT
    t.brokerage_id, p.id,
    CURRENT_DATE - s.received_offset_days,
    s.demand_type,
    s.desired_pyeongs, s.min_area_sqm, s.max_area_sqm, s.area_requirement_raw_text,
    s.min_budget_amount, s.max_budget_amount, s.budget_raw_text,
    -- 희망 입주일·의뢰 만료일·현 거주지 만기는 모두 미래다.
    CURRENT_DATE + s.move_in_offset_days,
    s.move_in_date_raw_text,
    CURRENT_DATE + s.expiry_offset_days,
    CASE WHEN s.tenancy_expiry_offset_days IS NULL
         THEN NULL
         ELSE CURRENT_DATE + s.tenancy_expiry_offset_days
    END,
    cb.id,
    s.classification, s.workflow_stage, s.status, t.user_id, s.memo,
    jsonb_build_object('seed_key', s.seed_key)
FROM (
    SELECT b.id AS brokerage_id, u.id AS user_id
    FROM brokerage b
    JOIN app_user u ON u.brokerage_id = b.id AND u.login_id = 'f3_synthetic_dev'
    WHERE b.name = 'F3_SYNTHETIC 합성중개사무소'
) t
CROSS JOIN (
    VALUES
        ('R1', 'P_D1', 3::integer, '매수',
         '{33}'::numeric(6,2)[], 105.00::numeric, 120.00::numeric, '33평대'::text,
         2600000000::bigint, 2900000000::bigint, '29억까지',
         75::integer, '3개월 내'::text, 120::integer, NULL::integer,
         FALSE, '일반'::text, '방문예정'::text, 'ACTIVE',
         '케이스 A 강한 후보이자 케이스 B 앵커. 예산·평형·단지·시점이 모두 맞는다.'::text),
        ('R2', 'P_D2', 20, '매수',
         '{33}', 105.00, 120.00, '33평대',
         2400000000, 2650000000, '26.5억 상한',
         200, '내년 3월 이후', 240, 195,
         FALSE, '일반', '상담중', 'ACTIVE',
         '케이스 A 약한 후보. 예산 하한은 통과하지만 가격 차와 시점 차가 남는다.'),
        ('R3', 'P_D3', 40, '매수',
         '{44}', 140.00, 160.00, '44평 이상',
         3000000000, 3200000000, '32억까지',
         700, '2년 뒤', 730, NULL,
         FALSE, '일반', '시세문의', 'ACTIVE',
         '케이스 A 기각 후보. 예산은 넉넉하지만 평형과 시점이 결정적으로 어긋난다.'),
        ('R4', 'P_D4', 10, '전세',
         '{25}', 80.00, 95.00, '25평대',
         2000000000, 2200000000, '22억까지',
         420, '현 전세 만기 맞춰서', 450, 400,
         TRUE, '일반', '상담중', 'ACTIVE',
         '케이스 E 후보. SQL 조건은 통과하지만 즉시 입주 매물과 시점이 맞지 않는다.'),
        ('R5', 'P_D5', 6, '매수',
         '{25}', 80.00, 95.00, '25평대',
         1800000000, 2000000000, '20억 이하',
         90, '3개월 내', 180, NULL,
         FALSE, '일반', '상담중', 'ACTIVE',
         '케이스 A 제외 확인용. 예산 하한 25.92억에 못 미친다.'),
        ('R6', 'P_D6', 8, '매수',
         '{33}', 105.00, 120.00, '33평대',
         2700000000, 3000000000, '30억까지',
         90, '3개월 내', 180, NULL,
         FALSE, '일반', '상담중', 'ACTIVE',
         '케이스 A 제외 확인용. 나루오피스텔만 희망해 가온마을 매물의 후보가 아니다.'),
        ('R7', 'P_D7', 60, '매수',
         '{33}', 105.00, 120.00, '33평대',
         2800000000, 3100000000, '31억까지',
         30, '즉시', 60, NULL,
         FALSE, '일반', '종료', 'CLOSED',
         '케이스 A 제외 확인용. 타사에서 계약이 끝나 종료 상태다.'),
        ('R8', 'P_D8', 12, '매도',
         '{33}', 105.00, 120.00, '33평대',
         2500000000, 2900000000, '28억선',
         150, '연내', 210, NULL,
         FALSE, '일반', '시세문의', 'ACTIVE',
         '케이스 D 앵커. 매도 구분은 대응하는 매물 거래 유형이 없어 후보가 0건이다.')
) AS s(
    seed_key, party_key, received_offset_days, demand_type,
    desired_pyeongs, min_area_sqm, max_area_sqm, area_requirement_raw_text,
    min_budget_amount, max_budget_amount, budget_raw_text,
    move_in_offset_days, move_in_date_raw_text, expiry_offset_days, tenancy_expiry_offset_days,
    has_co_broker, classification, workflow_stage, status, memo
)
JOIN party p
  ON p.brokerage_id = t.brokerage_id AND p.memo = 'seed_key=' || s.party_key
LEFT JOIN party cb
  ON s.has_co_broker
 AND cb.brokerage_id = t.brokerage_id
 AND cb.memo = 'seed_key=P_CO_BROKER';

-- 희망 단지. 지정하지 않은 구입장(R3)은 단지를 가리지 않는 손님이라 어느 단지 매물에도
-- 후보로 올라온다. 이것도 의도한 케이스다.
INSERT INTO property_requirement_complex (brokerage_id, requirement_id, complex_id, preference_order)
SELECT t.brokerage_id, r.id, c.id, s.preference_order
FROM (
    SELECT id AS brokerage_id FROM brokerage WHERE name = 'F3_SYNTHETIC 합성중개사무소'
) t
CROSS JOIN (
    VALUES
        ('R1', 'C1', 1::smallint),
        ('R2', 'C1', 1),
        ('R4', 'C1', 1),
        ('R5', 'C1', 1),
        ('R6', 'C2', 1),
        ('R7', 'C1', 1),
        ('R8', 'C1', 1)
) AS s(requirement_key, complex_key, preference_order)
JOIN property_requirement r
  ON r.brokerage_id = t.brokerage_id AND r.custom_fields->>'seed_key' = s.requirement_key
JOIN property_complex c
  ON c.brokerage_id = t.brokerage_id AND c.extra_info->>'seed_key' = s.complex_key;


-- ── 대량 장부 확장 ────────────────────────────────────────────────────────────
--
-- 기존 A~E는 작은 회귀 케이스로 유지한다. 아래 F~I는 별도 합성 단지에 매물 30건과
-- 구입장 40건을 더해 목록 밀도, 양방향 후보 검색과 상위 5건 카드화 제한을 검증한다.
-- generate_series의 번호와 seed_key는 고정이므로 reset 후 다시 넣어도 같은 분포가 된다.

INSERT INTO property_complex (brokerage_id, property_type, name, road_address, memo, extra_info)
SELECT
    t.brokerage_id, s.property_type, s.name, s.road_address, s.memo,
    jsonb_build_object('seed_key', s.seed_key, 'dataset', 'BULK')
FROM (
    SELECT id AS brokerage_id FROM brokerage WHERE name = 'F3_SYNTHETIC 합성중개사무소'
) t
CROSS JOIN (
    VALUES
        ('C3', 'APARTMENT', 'F3_SYNTHETIC 다온마을', '가상특별시 합성구 예시로 300', '대량 매매 케이스 전용 합성 단지.'),
        ('C4', 'APARTMENT', 'F3_SYNTHETIC 라온마을', '가상특별시 합성구 예시로 400', '대량 전세 케이스 전용 합성 단지.'),
        ('C5', 'OFFICETEL', 'F3_SYNTHETIC 마루오피스텔', '가상특별시 합성구 예시로 500', '대량 월세 케이스 전용 합성 단지.')
) AS s(seed_key, property_type, name, road_address, memo);

INSERT INTO property_unit (
    brokerage_id, complex_id, building_number, unit_number, floor_number, orientation, unit_type,
    pyeong, exclusive_area_sqm, supply_area_sqm, tenancy_status,
    current_deposit_amount, current_monthly_rent_amount, tenancy_expiry_date, tenancy_raw_text,
    is_expanded, built_in_features, facility_condition,
    assigned_user_id, memo, custom_fields, lifecycle_status
)
SELECT
    t.brokerage_id,
    c.id,
    CASE WHEN g.n <= 22 THEN (200 + ((g.n - 1) / 10) + 1)::text ELSE NULL END,
    lpad((100 + g.n)::text, 4, '0'),
    ((g.n - 1) % 20 + 1)::text,
    (ARRAY['남', '남동', '남서', '동'])[((g.n - 1) % 4) + 1],
    CASE WHEN g.n <= 12 THEN 'J1' WHEN g.n <= 22 THEN 'J2' ELSE NULL END,
    CASE WHEN g.n <= 12 THEN 33.00::numeric WHEN g.n <= 22 THEN 25.00 ELSE 18.00 END,
    CASE WHEN g.n <= 12 THEN 109.00::numeric WHEN g.n <= 22 THEN 84.00 ELSE 59.00 END,
    CASE WHEN g.n <= 12 THEN 140.00::numeric WHEN g.n <= 22 THEN 109.00 ELSE 78.00 END,
    CASE WHEN g.n <= 12 THEN '자가' WHEN g.n <= 22 THEN '입주' ELSE '월환' END,
    CASE WHEN g.n > 22 THEN 50000000::bigint + (g.n - 23) * 5000000 ELSE NULL END,
    CASE WHEN g.n > 22 THEN 1500000::bigint + (g.n - 23) * 100000 ELSE NULL END,
    CASE WHEN g.n > 12 THEN CURRENT_DATE + 90 + (g.n % 6) * 30 ELSE NULL END,
    CASE WHEN g.n > 22 THEN '합성 월세 계약 만기 후 입주' WHEN g.n > 12 THEN '합성 전세 입주 협의' ELSE NULL END,
    (g.n % 2 = 0),
    CASE WHEN g.n > 22 THEN '합성 풀옵션' ELSE '합성 붙박이장' END,
    (ARRAY['양호', '부분 수리', '입주 청소 예정'])[((g.n - 1) % 3) + 1],
    t.user_id,
    format('대량 합성 장부 세대 %s. 실제 주소나 인물을 나타내지 않는다.', lpad(g.n::text, 2, '0')),
    jsonb_build_object('seed_key', 'BU' || lpad(g.n::text, 2, '0'), 'dataset', 'BULK'),
    'NORMAL'
FROM (
    SELECT b.id AS brokerage_id, u.id AS user_id
    FROM brokerage b
    JOIN app_user u ON u.brokerage_id = b.id AND u.login_id = 'f3_synthetic_dev'
    WHERE b.name = 'F3_SYNTHETIC 합성중개사무소'
) t
CROSS JOIN generate_series(1, 30) AS g(n)
JOIN property_complex c
  ON c.brokerage_id = t.brokerage_id
 AND c.extra_info->>'seed_key' = CASE WHEN g.n <= 12 THEN 'C3' WHEN g.n <= 22 THEN 'C4' ELSE 'C5' END;

INSERT INTO party (
    brokerage_id, party_type, name, alternate_name, memo, privacy_consent_at, privacy_consent_by
)
SELECT
    t.brokerage_id,
    'PERSON',
    'F3_SYNTHETIC ' || s.display_role || ' ' || lpad(s.n::text, 2, '0'),
    '대량 합성 장부 ' || s.display_role,
    'seed_key=' || s.seed_prefix || lpad(s.n::text, 2, '0'),
    CASE WHEN s.has_consent THEN now() ELSE NULL END,
    CASE WHEN s.has_consent THEN t.user_id ELSE NULL END
FROM (
    SELECT b.id AS brokerage_id, u.id AS user_id
    FROM brokerage b
    JOIN app_user u ON u.brokerage_id = b.id AND u.login_id = 'f3_synthetic_dev'
    WHERE b.name = 'F3_SYNTHETIC 합성중개사무소'
) t
CROSS JOIN (
    SELECT n, '대량매도인'::text AS display_role, 'BP_L'::text AS seed_prefix, FALSE AS has_consent
    FROM generate_series(1, 30) AS g(n)
    UNION ALL
    SELECT n, '대량수요자', 'BP_R', TRUE
    FROM generate_series(1, 40) AS g(n)
) s;

INSERT INTO party_contact (
    brokerage_id, party_id, contact_method, contact_value, normalized_contact_value,
    contact_label, is_primary, contactability_status
)
SELECT
    p.brokerage_id,
    p.id,
    'PHONE',
    '010-0000-' || lpad((1000 + row_number() OVER (ORDER BY p.id))::text, 4, '0'),
    '01000000' || lpad((1000 + row_number() OVER (ORDER BY p.id))::text, 4, '0'),
    '합성 대표',
    TRUE,
    'UNKNOWN'
FROM party p
JOIN brokerage b ON b.id = p.brokerage_id
WHERE b.name = 'F3_SYNTHETIC 합성중개사무소'
  AND p.memo ~ '^seed_key=BP_[LR][0-9]{2}$';

INSERT INTO property_unit_party_relation (
    brokerage_id, unit_id, party_id, role, role_index, is_primary, is_co_owner, valid_from, memo
)
SELECT
    t.brokerage_id, u.id, p.id, 'LANDLORD', 1::smallint, TRUE, FALSE,
    CURRENT_DATE - 365, '대량 합성 장부 소유 관계'
FROM (
    SELECT id AS brokerage_id FROM brokerage WHERE name = 'F3_SYNTHETIC 합성중개사무소'
) t
CROSS JOIN generate_series(1, 30) AS g(n)
JOIN property_unit u
  ON u.brokerage_id = t.brokerage_id
 AND u.custom_fields->>'seed_key' = 'BU' || lpad(g.n::text, 2, '0')
JOIN party p
  ON p.brokerage_id = t.brokerage_id
 AND p.memo = 'seed_key=BP_L' || lpad(g.n::text, 2, '0');

INSERT INTO property_listing (
    brokerage_id, unit_id, client_party_id, received_at, status,
    is_sale_available, sale_price,
    is_jeonse_available, jeonse_deposit_amount,
    is_monthly_rent_available, monthly_rent_deposit_amount, monthly_rent_amount,
    price_raw_text, handover_condition, assigned_user_id, memo, custom_fields
)
SELECT
    t.brokerage_id,
    u.id,
    p.id,
    CURRENT_DATE - (1 + g.n % 28),
    'RECEIVED',
    (g.n <= 12),
    CASE WHEN g.n <= 12 THEN 2050000000::bigint + (g.n - 1) * 50000000 ELSE NULL END,
    (g.n BETWEEN 13 AND 22),
    CASE WHEN g.n BETWEEN 13 AND 22 THEN 800000000::bigint + (g.n - 13) * 40000000 ELSE NULL END,
    (g.n >= 23),
    CASE WHEN g.n >= 23 THEN 50000000::bigint + (g.n - 23) * 5000000 ELSE NULL END,
    CASE WHEN g.n >= 23 THEN 1500000::bigint + (g.n - 23) * 100000 ELSE NULL END,
    CASE
        WHEN g.n <= 12 THEN format('합성 매매 %s억원', 20.5 + (g.n - 1) * 0.5)
        WHEN g.n <= 22 THEN format('합성 전세 %s억원', 8.0 + (g.n - 13) * 0.4)
        ELSE format('합성 월세 보증 %s만원 / %s만원', 5000 + (g.n - 23) * 500, 150 + (g.n - 23) * 10)
    END,
    (ARRAY['즉시', '한 달 내', '잔금일 협의'])[((g.n - 1) % 3) + 1],
    t.user_id,
    format('대량 합성 매물 BL%s. 가격·시점 조건의 분포를 만든다.', lpad(g.n::text, 2, '0')),
    jsonb_build_object('seed_key', 'BL' || lpad(g.n::text, 2, '0'), 'dataset', 'BULK')
FROM (
    SELECT b.id AS brokerage_id, u2.id AS user_id
    FROM brokerage b
    JOIN app_user u2 ON u2.brokerage_id = b.id AND u2.login_id = 'f3_synthetic_dev'
    WHERE b.name = 'F3_SYNTHETIC 합성중개사무소'
) t
CROSS JOIN generate_series(1, 30) AS g(n)
JOIN property_unit u
  ON u.brokerage_id = t.brokerage_id
 AND u.custom_fields->>'seed_key' = 'BU' || lpad(g.n::text, 2, '0')
JOIN party p
  ON p.brokerage_id = t.brokerage_id
 AND p.memo = 'seed_key=BP_L' || lpad(g.n::text, 2, '0');

INSERT INTO property_requirement (
    brokerage_id, party_id, received_at, demand_type,
    desired_pyeongs, min_area_sqm, max_area_sqm, area_requirement_raw_text,
    min_budget_amount, max_budget_amount, budget_raw_text,
    desired_move_in_date, move_in_date_raw_text, request_expiry_date,
    current_tenancy_expiry_date, co_broker_party_id,
    classification, workflow_stage, status, assigned_user_id, memo, custom_fields
)
SELECT
    t.brokerage_id,
    p.id,
    CURRENT_DATE - (1 + g.n % 35),
    CASE WHEN g.n <= 18 THEN '매수' WHEN g.n <= 30 THEN '전세' ELSE '월세' END,
    CASE WHEN g.n <= 18 THEN ARRAY[33.00::numeric] WHEN g.n <= 30 THEN ARRAY[25.00::numeric] ELSE ARRAY[18.00::numeric] END,
    CASE WHEN g.n <= 18 THEN 100.00::numeric WHEN g.n <= 30 THEN 80.00 ELSE 55.00 END,
    CASE WHEN g.n <= 18 THEN 120.00::numeric WHEN g.n <= 30 THEN 95.00 ELSE 70.00 END,
    CASE WHEN g.n <= 18 THEN '합성 33평대' WHEN g.n <= 30 THEN '합성 25평대' ELSE '합성 18평대' END,
    CASE
        WHEN g.n <= 18 THEN 2300000000::bigint
        WHEN g.n <= 30 THEN 800000000::bigint
        ELSE 50000000::bigint
    END,
    CASE
        WHEN g.n <= 18 THEN 2700000000::bigint + ((g.n - 1) % 6) * 100000000
        WHEN g.n <= 30 THEN 1200000000::bigint + ((g.n - 19) % 4) * 100000000
        ELSE 80000000::bigint + ((g.n - 31) % 5) * 10000000
    END,
    CASE
        WHEN g.n <= 18 THEN '합성 매수 예산 27억 이상'
        WHEN g.n <= 30 THEN '합성 전세 예산 12억 이상'
        ELSE '합성 월세 보증금 8천만원 이상'
    END,
    CURRENT_DATE + 30 + (g.n % 8) * 30,
    format('합성 희망 입주 %s일 이후', 30 + (g.n % 8) * 30),
    CURRENT_DATE + 365 + (g.n % 6) * 30,
    CASE WHEN g.n % 3 = 0 THEN CURRENT_DATE + 60 + (g.n % 5) * 30 ELSE NULL END,
    NULL,
    '일반',
    (ARRAY['신규', '상담중', '방문예정'])[((g.n - 1) % 3) + 1],
    'ACTIVE',
    t.user_id,
    format('대량 합성 구입장 BR%s. 예산·시점·연락 상태의 분포를 만든다.', lpad(g.n::text, 2, '0')),
    jsonb_build_object('seed_key', 'BR' || lpad(g.n::text, 2, '0'), 'dataset', 'BULK')
FROM (
    SELECT b.id AS brokerage_id, u.id AS user_id
    FROM brokerage b
    JOIN app_user u ON u.brokerage_id = b.id AND u.login_id = 'f3_synthetic_dev'
    WHERE b.name = 'F3_SYNTHETIC 합성중개사무소'
) t
CROSS JOIN generate_series(1, 40) AS g(n)
JOIN party p
  ON p.brokerage_id = t.brokerage_id
 AND p.memo = 'seed_key=BP_R' || lpad(g.n::text, 2, '0');

INSERT INTO property_requirement_complex (brokerage_id, requirement_id, complex_id, preference_order)
SELECT t.brokerage_id, r.id, c.id, 1::smallint
FROM (
    SELECT id AS brokerage_id FROM brokerage WHERE name = 'F3_SYNTHETIC 합성중개사무소'
) t
CROSS JOIN generate_series(1, 40) AS g(n)
JOIN property_requirement r
  ON r.brokerage_id = t.brokerage_id
 AND r.custom_fields->>'seed_key' = 'BR' || lpad(g.n::text, 2, '0')
JOIN property_complex c
  ON c.brokerage_id = t.brokerage_id
 AND c.extra_info->>'seed_key' = CASE WHEN g.n <= 18 THEN 'C3' WHEN g.n <= 30 THEN 'C4' ELSE 'C5' END;


-- ── 매물 측 상담 로그 ─────────────────────────────────────────────────────────
--
-- 매물 대리 카드는 이 로그만 읽는다. 가격 조정 여지, 명도·입주 시점, 결정권 제약처럼
-- 판정 이유가 될 문장을 원문에 그대로 담는다. 모델이 인용할 문장이 없으면 카드의 근거가
-- UNKNOWN 으로만 남아 판정이 성립하지 않는다.
--
-- 최신 진술이 과거 진술을 이기는 규칙을 확인할 수 있도록 L1 은 접수가와 조정가를 다른
-- 시점에 나눠 적는다.

INSERT INTO client_interaction (
    brokerage_id, interaction_at, interaction_channel, communication_direction,
    interaction_result, counterparty_role, counterparty_index, interaction_content,
    party_id, unit_id, listing_id, source_type, approval_status, created_by
)
SELECT
    t.brokerage_id,
    now() - (s.offset_days || ' days')::interval,
    s.channel, s.direction, s.result, s.counterparty_role, s.counterparty_index, s.content,
    p.id, l.unit_id, l.id, 'HUMAN', 'NOT_REQUIRED', t.user_id
FROM (
    SELECT b.id AS brokerage_id, u.id AS user_id
    FROM brokerage b
    JOIN app_user u ON u.brokerage_id = b.id AND u.login_id = 'f3_synthetic_dev'
    WHERE b.name = 'F3_SYNTHETIC 합성중개사무소'
) t
CROSS JOIN (
    VALUES
        -- 케이스 A 앵커 L1
        ('L1', 'P_OWNER1', 30::integer, 'CALL', 'OUTBOUND', 'CONNECTED', 'LANDLORD', 1::smallint,
         '매도 접수. 28.8억에 내놓음. 공동명의라 배우자 동의 없이는 최종 결정 못 한다고 하심.'::text),
        ('L1', 'P_OWNER1', 12, 'CALL', 'INBOUND', 'CONNECTED', 'LANDLORD', 1,
         '28.3억까지는 조정해 줄 수 있다. 그 아래로는 안 한다고 못 박음.'),
        -- 부재중 로그를 가장 최신에 두지 않는다. 프롬프트는 최신 진술을 우선하므로 마지막
        -- 로그가 불통 기록이면 모델이 의향 자체를 철회로 읽을 수 있다. 불통은 중간에 두고
        -- 마지막은 진술로 끝낸다. 특정 모델의 등급·의향 출력을 seed 기대값으로 고정하지 않는다.
        ('L1', 'P_OWNER2', 8, 'CALL', 'OUTBOUND', 'NO_ANSWER', 'LANDLORD', 2,
         '부재중. 문자 발송. 공동명의자 동의 확인 필요.'),
        ('L1', 'P_OWNER1', 2, 'CALL', 'OUTBOUND', 'CONNECTED', 'LANDLORD', 1,
         '매도 진행 의사 그대로다. 잔금일 협의 가능하고 이사 갈 집이 정해지면 2개월 안에 명도 가능하다고 함.'),
        -- 케이스 B 후보 L2
        ('L2', 'P_OWNER4', 14, 'CALL', 'OUTBOUND', 'CONNECTED', 'LANDLORD', 1,
         '매도 접수. 30.5억에 내놓지만 갈아타기 목적이라 조정해 줄 것 같음.'),
        ('L2', 'P_OWNER4', 6, 'CALL', 'INBOUND', 'CONNECTED', 'LANDLORD', 1,
         '29.8억까지는 검토 가능하다. 2월중 입주 가능.'),
        -- 케이스 B 제외 확인용 L3
        ('L3', 'P_OWNER5', 21, 'CALL', 'OUTBOUND', 'CONNECTED', 'LANDLORD', 1,
         '매도 접수. 39억. 급하지 않아 가격 조정 계획 없다고 함.'),
        -- 케이스 E 앵커 L4
        ('L4', 'P_OWNER3', 5, 'CALL', 'OUTBOUND', 'CONNECTED', 'LANDLORD', 1,
         '전세 접수. 21.5억. 임차인 명도가 끝나 즉시 입주 가능하다.'),
        ('L4', 'P_OWNER3', 3, 'CALL', 'INBOUND', 'CONNECTED', 'LANDLORD', 1,
         '만기 대기 조건은 받지 않는다. 즉시 입주 손님만 연결해 달라고 하심.'),
        ('L4', 'P_OWNER3', 1, 'CALL', 'OUTBOUND', 'CONNECTED', 'LANDLORD', 1,
         '보증금 21.5억은 고정이다. 조정 없다고 못 박음.'),
        -- 케이스 C 앵커 L5
        ('L5', 'P_OWNER6', 3, 'CALL', 'OUTBOUND', 'CONNECTED', 'LANDLORD', 1,
         '월세 내놓음. 보증 5000/380, 반려동물X 외국인X 조건.'),
        ('L5', 'P_OWNER6', 1, 'CALL', 'INBOUND', 'CONNECTED', 'LANDLORD', 1,
         '보증금 올리고 월세 낮추는 월환은 가능하다고 함. 현 임차인 만기 후 입주.')
) AS s(
    listing_key, party_key, offset_days, channel, direction, result,
    counterparty_role, counterparty_index, content
)
JOIN property_listing l
  ON l.brokerage_id = t.brokerage_id AND l.custom_fields->>'seed_key' = s.listing_key
JOIN party p
  ON p.brokerage_id = t.brokerage_id AND p.memo = 'seed_key=' || s.party_key;


-- ── 수요 측 상담 로그 ─────────────────────────────────────────────────────────
--
-- 손님 대리 카드는 이 로그만 읽는다. 예산 상한, 대출, 입주 시기, 평형 조건처럼 중개
-- 판정에서 결정적 장애로 지목될 문장을 명확하게 적는다.

INSERT INTO client_interaction (
    brokerage_id, interaction_at, interaction_channel, communication_direction,
    interaction_result, counterparty_role, counterparty_index, interaction_content,
    party_id, requirement_id, source_type, approval_status, created_by
)
SELECT
    t.brokerage_id,
    now() - (s.offset_days || ' days')::interval,
    s.channel, s.direction, s.result, 'BUYER', 1::smallint, s.content,
    p.id, r.id, 'HUMAN', 'NOT_REQUIRED', t.user_id
FROM (
    SELECT b.id AS brokerage_id, u.id AS user_id
    FROM brokerage b
    JOIN app_user u ON u.brokerage_id = b.id AND u.login_id = 'f3_synthetic_dev'
    WHERE b.name = 'F3_SYNTHETIC 합성중개사무소'
) t
CROSS JOIN (
    VALUES
        -- 케이스 A 강한 후보 · 케이스 B 앵커 R1
        ('R1', 3::integer, 'CALL', 'INBOUND', 'CONNECTED',
         '가온마을 33평 매수 희망. 예산 29억까지 가능하고 대출 승인은 이미 끝났다고 함.'::text),
        ('R1', 2, 'CALL', 'OUTBOUND', 'CONNECTED',
         '입주는 3개월 안이면 된다. 잔금일은 매도인 일정에 맞출 수 있다고 함.'),
        ('R1', 1, 'CALL', 'INBOUND', 'CONNECTED',
         '101동 라인 선호. 저층은 빼 달라고 요청.'),
        -- 케이스 A 약한 후보 R2
        ('R2', 20, 'CALL', 'INBOUND', 'CONNECTED',
         '가온마을 33평 매수 상담. 예산은 26.5억이 상한이다.'),
        ('R2', 9, 'CALL', 'OUTBOUND', 'CONNECTED',
         '26.5억을 넘으면 대출을 더 받아야 해서 어렵다. 조건이 아주 좋으면 27억까지는 검토해 보겠다고 함.'),
        ('R2', 4, 'CALL', 'INBOUND', 'CONNECTED',
         '현 전세 만기가 남아 입주는 내년 3월 이후에 가능하다.'),
        -- 케이스 A 기각 후보 R3
        ('R3', 40, 'CALL', 'INBOUND', 'CONNECTED',
         '44평 이상만 본다. 33평은 안 본다고 명확히 하심.'),
        ('R3', 25, 'CALL', 'OUTBOUND', 'CONNECTED',
         '예산은 32억까지 가능. 급하지 않다고 함.'),
        ('R3', 11, 'CALL', 'INBOUND', 'CONNECTED',
         '이사 계획은 2년 뒤다. 지금은 시세만 보고 있다.'),
        -- 케이스 E 후보 R4
        ('R4', 10, 'CALL', 'INBOUND', 'CONNECTED',
         '가온마을 25평 전세 문의. 보증금 22억까지 가능하다.'),
        ('R4', 7, 'CALL', 'OUTBOUND', 'CONNECTED',
         '현 거주지 전세 만기가 남아 있어 그 전에는 못 움직인다고 함.'),
        ('R4', 2, 'CALL', 'INBOUND', 'CONNECTED',
         '만기 전 이사는 계획 없다. 만기에 날짜를 맞춰 주는 집만 본다고 못 박음.'),
        -- 제외 확인용 R5 · R6 · R7 · 케이스 D 앵커 R8
        ('R5', 6, 'CALL', 'INBOUND', 'CONNECTED',
         '25평대 매수 상담. 예산은 20억을 넘길 수 없다고 함.'),
        ('R6', 8, 'CALL', 'INBOUND', 'CONNECTED',
         '나루오피스텔만 본다. 가온마을은 관심 없다고 하심.'),
        ('R7', 60, 'CALL', 'OUTBOUND', 'CONNECTED',
         '타사에서 계약을 마쳤다고 연락 옴. 구입장 종료 처리.'),
        ('R8', 12, 'CALL', 'INBOUND', 'CONNECTED',
         '가온마을 33평 매도 상담. 28억선을 희망한다.'),
        ('R8', 5, 'CALL', 'OUTBOUND', 'CONNECTED',
         '급매는 아니다. 시세 확인하고 세금 상담 받은 뒤 결정한다고 함.')
) AS s(requirement_key, offset_days, channel, direction, result, content)
JOIN property_requirement r
  ON r.brokerage_id = t.brokerage_id AND r.custom_fields->>'seed_key' = s.requirement_key
JOIN party p
  ON p.brokerage_id = t.brokerage_id AND p.id = r.party_id;


-- ── 대량 장부 상담 로그 ───────────────────────────────────────────────────────
--
-- 대량 매물·구입장도 각각 2건의 합성 상담 근거를 가진다. 번호의 나머지에 따라 가격
-- 유연성·시점·연락 가능성을 달리해 같은 문장만 반복되는 데이터가 되지 않게 한다.

INSERT INTO client_interaction (
    brokerage_id, interaction_at, interaction_channel, communication_direction,
    interaction_result, counterparty_role, counterparty_index, interaction_content,
    party_id, unit_id, listing_id, source_type, approval_status, created_by
)
SELECT
    t.brokerage_id,
    now() - ((g.n * 2 + e.event_index) || ' days')::interval,
    CASE WHEN e.event_index = 1 THEN 'CALL' ELSE 'MESSAGE' END,
    CASE WHEN e.event_index = 1 THEN 'OUTBOUND' ELSE 'INBOUND' END,
    CASE WHEN e.event_index = 2 AND g.n % 7 = 0 THEN 'NO_ANSWER' ELSE 'CONNECTED' END,
    'LANDLORD',
    1::smallint,
    CASE
        WHEN e.event_index = 1 AND g.n <= 12 THEN
            format('F3_SYNTHETIC 다온마을 33평 매매 상담. 표기 가격은 %s번 합성 구간이며 매도 의사가 있다.', g.n)
        WHEN e.event_index = 1 AND g.n <= 22 THEN
            format('F3_SYNTHETIC 라온마을 25평 전세 상담. 보증금 조건은 %s번 합성 구간이다.', g.n - 12)
        WHEN e.event_index = 1 THEN
            format('F3_SYNTHETIC 마루오피스텔 월세 상담. 보증금과 월 차임은 %s번 합성 구간이다.', g.n - 22)
        WHEN g.n % 7 = 0 THEN '합성 연락 점검에서 부재중이었다. 기존 의뢰는 철회하지 않았다.'
        WHEN g.n % 3 = 0 THEN '합성 상담에서 가격보다 빠른 계약과 입주 시점을 우선한다고 확인했다.'
        WHEN g.n % 3 = 1 THEN '합성 상담에서 조건이 맞으면 표기 금액을 일부 협의할 수 있다고 확인했다.'
        ELSE '합성 상담에서 표기 금액은 유지하되 잔금일과 입주일은 조정할 수 있다고 확인했다.'
    END,
    p.id,
    l.unit_id,
    l.id,
    'HUMAN',
    'NOT_REQUIRED',
    t.user_id
FROM (
    SELECT b.id AS brokerage_id, u.id AS user_id
    FROM brokerage b
    JOIN app_user u ON u.brokerage_id = b.id AND u.login_id = 'f3_synthetic_dev'
    WHERE b.name = 'F3_SYNTHETIC 합성중개사무소'
) t
CROSS JOIN generate_series(1, 30) AS g(n)
CROSS JOIN (VALUES (1), (2)) AS e(event_index)
JOIN property_listing l
  ON l.brokerage_id = t.brokerage_id
 AND l.custom_fields->>'seed_key' = 'BL' || lpad(g.n::text, 2, '0')
JOIN party p
  ON p.brokerage_id = t.brokerage_id
 AND p.memo = 'seed_key=BP_L' || lpad(g.n::text, 2, '0');

INSERT INTO client_interaction (
    brokerage_id, interaction_at, interaction_channel, communication_direction,
    interaction_result, counterparty_role, counterparty_index, interaction_content,
    party_id, requirement_id, source_type, approval_status, created_by
)
SELECT
    t.brokerage_id,
    now() - ((g.n * 2 + e.event_index) || ' days')::interval,
    CASE WHEN e.event_index = 1 THEN 'CALL' ELSE 'MESSAGE' END,
    CASE WHEN e.event_index = 1 THEN 'INBOUND' ELSE 'OUTBOUND' END,
    CASE WHEN e.event_index = 2 AND g.n % 9 = 0 THEN 'NO_ANSWER' ELSE 'CONNECTED' END,
    'BUYER',
    1::smallint,
    CASE
        WHEN e.event_index = 1 AND g.n <= 18 THEN
            format('F3_SYNTHETIC 다온마을 33평 매수 희망. BR%s 합성 예산 범위에서 찾는다.', lpad(g.n::text, 2, '0'))
        WHEN e.event_index = 1 AND g.n <= 30 THEN
            format('F3_SYNTHETIC 라온마을 25평 전세 희망. BR%s 합성 보증금 범위에서 찾는다.', lpad(g.n::text, 2, '0'))
        WHEN e.event_index = 1 THEN
            format('F3_SYNTHETIC 마루오피스텔 월세 희망. BR%s 합성 보증금 범위에서 찾는다.', lpad(g.n::text, 2, '0'))
        WHEN g.n % 9 = 0 THEN '합성 연락 점검에서 부재중이었다. 구입장 의뢰는 계속 유지한다.'
        WHEN g.n % 4 = 0 THEN '합성 상담에서 예산 상한은 고정이고 입주일은 조정할 수 없다고 확인했다.'
        WHEN g.n % 4 = 1 THEN '합성 상담에서 조건이 좋으면 예산을 소폭 높이고 잔금일도 맞출 수 있다고 확인했다.'
        WHEN g.n % 4 = 2 THEN '합성 상담에서 가격보다 빠른 입주와 연락 가능한 매물을 우선한다고 확인했다.'
        ELSE '합성 상담에서 평형과 단지는 고정이지만 세부 층과 방향은 협의할 수 있다고 확인했다.'
    END,
    p.id,
    r.id,
    'HUMAN',
    'NOT_REQUIRED',
    t.user_id
FROM (
    SELECT b.id AS brokerage_id, u.id AS user_id
    FROM brokerage b
    JOIN app_user u ON u.brokerage_id = b.id AND u.login_id = 'f3_synthetic_dev'
    WHERE b.name = 'F3_SYNTHETIC 합성중개사무소'
) t
CROSS JOIN generate_series(1, 40) AS g(n)
CROSS JOIN (VALUES (1), (2)) AS e(event_index)
JOIN property_requirement r
  ON r.brokerage_id = t.brokerage_id
 AND r.custom_fields->>'seed_key' = 'BR' || lpad(g.n::text, 2, '0')
JOIN party p
  ON p.brokerage_id = t.brokerage_id
 AND p.memo = 'seed_key=BP_R' || lpad(g.n::text, 2, '0');


-- ── 최종 접촉 시각 ───────────────────────────────────────────────────────────
--
-- 카드 입력의 days_since_last_contact 가 이 값에서 나온다. 비워 두면 접촉 신호가
-- 통째로 UNKNOWN 이 된다.

UPDATE property_unit u
SET last_contact_at = latest.moment
FROM (
    SELECT i.unit_id, max(i.interaction_at) AS moment
    FROM client_interaction i
    JOIN brokerage b ON b.id = i.brokerage_id
    WHERE b.name = 'F3_SYNTHETIC 합성중개사무소'
      AND i.unit_id IS NOT NULL
      AND i.is_voided = FALSE
    GROUP BY i.unit_id
) latest
WHERE u.id = latest.unit_id;

UPDATE property_requirement r
SET last_contact_at = latest.moment
FROM (
    SELECT i.requirement_id, max(i.interaction_at) AS moment
    FROM client_interaction i
    JOIN brokerage b ON b.id = i.brokerage_id
    WHERE b.name = 'F3_SYNTHETIC 합성중개사무소'
      AND i.requirement_id IS NOT NULL
      AND i.is_voided = FALSE
    GROUP BY i.requirement_id
) latest
WHERE r.id = latest.requirement_id;


-- ── 적용 결과 ────────────────────────────────────────────────────────────────
--
-- backend/.env 의 AUTH_DEVELOPMENT_BROKERAGE_ID 에 넣을 값과 각 케이스의 anchor_id 다.
-- 자동 증가 ID 는 로컬마다 다르므로 문서의 숫자를 그대로 쓰지 않는다.

SELECT
    b.id   AS "AUTH_DEVELOPMENT_BROKERAGE_ID",
    u.id   AS "user_id",
    u.login_id AS "AUTH_DEVELOPMENT_LOGIN_ID"
FROM brokerage b
JOIN app_user u ON u.brokerage_id = b.id
WHERE b.name = 'F3_SYNTHETIC 합성중개사무소';

SELECT 'A' AS "케이스", 'LISTING' AS "anchor_type", l.id AS "anchor_id", '매매 28.8억 · 기대 후보 3건' AS "설명"
FROM property_listing l JOIN brokerage b ON b.id = l.brokerage_id
WHERE b.name = 'F3_SYNTHETIC 합성중개사무소' AND l.custom_fields->>'seed_key' = 'L1'
UNION ALL
SELECT 'B', 'REQUIREMENT', r.id, '매수 29억 · 기대 후보 2건'
FROM property_requirement r JOIN brokerage b ON b.id = r.brokerage_id
WHERE b.name = 'F3_SYNTHETIC 합성중개사무소' AND r.custom_fields->>'seed_key' = 'R1'
UNION ALL
SELECT 'C', 'LISTING', l.id, '월세 · 기대 후보 0건'
FROM property_listing l JOIN brokerage b ON b.id = l.brokerage_id
WHERE b.name = 'F3_SYNTHETIC 합성중개사무소' AND l.custom_fields->>'seed_key' = 'L5'
UNION ALL
SELECT 'D', 'REQUIREMENT', r.id, '매도 구분 · 기대 후보 0건'
FROM property_requirement r JOIN brokerage b ON b.id = r.brokerage_id
WHERE b.name = 'F3_SYNTHETIC 합성중개사무소' AND r.custom_fields->>'seed_key' = 'R8'
UNION ALL
SELECT 'E', 'LISTING', l.id, '전세 21.5억 · 기대 후보 1건, 시점 불일치'
FROM property_listing l JOIN brokerage b ON b.id = l.brokerage_id
WHERE b.name = 'F3_SYNTHETIC 합성중개사무소' AND l.custom_fields->>'seed_key' = 'L4'
UNION ALL
SELECT 'F', 'LISTING', l.id, '대량 매매 · 전체 후보 19건, 카드화 5건'
FROM property_listing l JOIN brokerage b ON b.id = l.brokerage_id
WHERE b.name = 'F3_SYNTHETIC 합성중개사무소' AND l.custom_fields->>'seed_key' = 'BL01'
UNION ALL
SELECT 'G', 'REQUIREMENT', r.id, '대량 매수 · 기대 후보 12건'
FROM property_requirement r JOIN brokerage b ON b.id = r.brokerage_id
WHERE b.name = 'F3_SYNTHETIC 합성중개사무소' AND r.custom_fields->>'seed_key' = 'BR01'
UNION ALL
SELECT 'H', 'LISTING', l.id, '대량 전세 · 기대 후보 12건'
FROM property_listing l JOIN brokerage b ON b.id = l.brokerage_id
WHERE b.name = 'F3_SYNTHETIC 합성중개사무소' AND l.custom_fields->>'seed_key' = 'BL13'
UNION ALL
SELECT 'I', 'LISTING', l.id, '대량 월세 · 기대 후보 10건'
FROM property_listing l JOIN brokerage b ON b.id = l.brokerage_id
WHERE b.name = 'F3_SYNTHETIC 합성중개사무소' AND l.custom_fields->>'seed_key' = 'BL23'
ORDER BY 1;

COMMIT;
