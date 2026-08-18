-- PostgreSQL 15+
-- F3 A군 케이스 검증용 장부 시드 데이터
-- 요구 스키마: docs/db/migrate/001~010 적용 완료 상태
-- 원본: 06_프로토타입_F3플로우/data/010_DATA_F3_CASE_SEED.sql (생성기 data/build_ledger.py)
--
-- 이 파일은 데모·로컬용 합성 데이터를 넣는다. 운영 DB에는 적용하지 않는다.
-- migration 이 아니므로 migrate/ 의 번호 체계와 무관하고 실행기가 관리하지 않는다.
-- BEGIN/COMMIT 이 없다 — psql -1 로 단일 transaction 에 감싸 적용한다.
-- 상태값은 DDL에 CHECK 제약이 없어 제안값이다. 어휘는 seed/VALUES.md 를 따른다.

-- ══ 001 중개 플랫폼 ══════════════════════════════════════════════════
INSERT INTO brokerage (name, business_registration_number, settings, status)
VALUES ('한들공인중개사사무소', '000-00-00000', '{"seed": "f3-case", "base_date": "2026-08-17"}'::jsonb, 'ACTIVE');

INSERT INTO app_user (brokerage_id, login_id, password_hash, display_name, role)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), 'owner', '!seed-not-a-real-hash!', '대표 공인중개사', 'BROKER');
INSERT INTO app_user (brokerage_id, login_id, password_hash, display_name, role)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), 'staff1', '!seed-not-a-real-hash!', '직원 1', 'STAFF');
INSERT INTO app_user (brokerage_id, login_id, password_hash, display_name, role)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), 'viewer', '!seed-not-a-real-hash!', '읽기전용', 'READONLY');

INSERT INTO ai_model_config (brokerage_id, capability, config_key, config_version,
    provider, model_name, parameters, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), 'LISTING_DELEGATE', 'default', 1, 'openai', 'gpt-4o-mini', '{"temperature": 0}'::jsonb, (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO ai_model_config (brokerage_id, capability, config_key, config_version,
    provider, model_name, parameters, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), 'CUSTOMER_DELEGATE', 'default', 1, 'openai', 'gpt-4o-mini', '{"temperature": 0}'::jsonb, (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO ai_model_config (brokerage_id, capability, config_key, config_version,
    provider, model_name, parameters, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), 'BROKER_JUDGMENT', 'default', 1, 'openai', 'gpt-4o', '{"temperature": 0}'::jsonb, (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));

-- ══ 002 단지 ═════════════════════════════════════════════════════════
INSERT INTO property_complex (brokerage_id, property_type, name, road_address, memo, extra_info)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), 'APARTMENT', '한들마을 센트럴파크', '(가상) ○○시 ○○구 한들로 100', '가상 단지. 실존 단지와 무관하며 제원만 실제 대단지 공개 정보를 참고했다.', '{"total_households": 3206, "building_count": 48, "completed": "2020-11", "max_floor": 29, "types": [{"label": "25평형", "pyeong": 25, "exclusive_sqm": 59.94, "supply_sqm": 82.35, "households": 612, "unit_types": ["H1"], "market_sale": [15.5, 17.5]}, {"label": "33평형", "pyeong": 33, "exclusive_sqm": 84.96, "supply_sqm": 112.74, "households": 1704, "unit_types": ["J1", "J2"], "market_sale": [21.0, 24.5], "market_jeonse": [11.0, 12.5]}, {"label": "43평형", "pyeong": 43, "exclusive_sqm": 114.87, "supply_sqm": 148.2, "households": 620, "unit_types": ["K1"], "market_sale": [29.0, 33.0]}, {"label": "52평형", "pyeong": 52, "exclusive_sqm": 139.91, "supply_sqm": 179.63, "households": 270, "unit_types": ["L1"], "market_sale": [33.0, 38.0]}]}'::jsonb);

-- ══ 002 인물·연락처 ══════════════════════════════════════════════════
-- 전화번호는 국내 미할당 010-0 대역만 사용한다 (실번호 충돌 원천 차단).
INSERT INTO party (brokerage_id, party_type, name, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), 'CO_BROKER_OFFICE', '으뜸공인중개사', '합성 데이터 · P001');
INSERT INTO party (brokerage_id, party_type, name, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), 'CO_BROKER_OFFICE', '다올공인중개사', '합성 데이터 · P002');
INSERT INTO party (brokerage_id, party_type, name, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), 'PERSON', '윤O호', '합성 데이터 · P003');
INSERT INTO party_contact (brokerage_id, party_id, contact_method, contact_value,
    normalized_contact_value, contact_label, is_primary, contactability_status)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '윤O호'), 'PHONE', '010-0130-3370', '01001303370', '본인', TRUE, 'OK');
INSERT INTO party (brokerage_id, party_type, name, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), 'PERSON', '배O란', '합성 데이터 · P004');
INSERT INTO party_contact (brokerage_id, party_id, contact_method, contact_value,
    normalized_contact_value, contact_label, is_primary, contactability_status)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '배O란'), 'PHONE', '010-0140-7160', '01001407160', '본인', TRUE, 'OK');
INSERT INTO party (brokerage_id, party_type, name, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), 'PERSON', '서O철', '합성 데이터 · P005');
INSERT INTO party_contact (brokerage_id, party_id, contact_method, contact_value,
    normalized_contact_value, contact_label, is_primary, contactability_status)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '서O철'), 'PHONE', '010-0150-1950', '01001501950', '본인', TRUE, 'OK');
INSERT INTO party (brokerage_id, party_type, name, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), 'PERSON', '심O규', '합성 데이터 · P006');
INSERT INTO party_contact (brokerage_id, party_id, contact_method, contact_value,
    normalized_contact_value, contact_label, is_primary, contactability_status)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '심O규'), 'PHONE', '010-0160-5740', '01001605740', '본인', TRUE, 'OK');
INSERT INTO party (brokerage_id, party_type, name, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), 'PERSON', '임O선', '합성 데이터 · P007');
INSERT INTO party_contact (brokerage_id, party_id, contact_method, contact_value,
    normalized_contact_value, contact_label, is_primary, contactability_status)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '임O선'), 'PHONE', '010-0170-9530', '01001709530', '본인', TRUE, 'OK');
INSERT INTO party (brokerage_id, party_type, name, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), 'PERSON', '하O민', '합성 데이터 · P008');
INSERT INTO party_contact (brokerage_id, party_id, contact_method, contact_value,
    normalized_contact_value, contact_label, is_primary, contactability_status)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '하O민'), 'PHONE', '010-0180-4320', '01001804320', '본인', TRUE, 'OK');
INSERT INTO party (brokerage_id, party_type, name, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), 'PERSON', '노O기', '합성 데이터 · P009');
INSERT INTO party_contact (brokerage_id, party_id, contact_method, contact_value,
    normalized_contact_value, contact_label, is_primary, contactability_status)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '노O기'), 'PHONE', '010-0190-8110', '01001908110', '본인', TRUE, 'OK');
INSERT INTO party (brokerage_id, party_type, name, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), 'PERSON', '오O규', '합성 데이터 · P010');
INSERT INTO party_contact (brokerage_id, party_id, contact_method, contact_value,
    normalized_contact_value, contact_label, is_primary, contactability_status)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '오O규'), 'PHONE', '010-0200-2900', '01002002900', '본인', TRUE, 'CAUTION');
INSERT INTO party (brokerage_id, party_type, name, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), 'PERSON', '황O식', '합성 데이터 · P011');
INSERT INTO party_contact (brokerage_id, party_id, contact_method, contact_value,
    normalized_contact_value, contact_label, is_primary, contactability_status)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '황O식'), 'PHONE', '010-0210-6690', '01002106690', '본인', TRUE, 'OK');
INSERT INTO party (brokerage_id, party_type, name, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), 'PERSON', '강O주', '합성 데이터 · P012');
INSERT INTO party_contact (brokerage_id, party_id, contact_method, contact_value,
    normalized_contact_value, contact_label, is_primary, contactability_status)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '강O주'), 'PHONE', '010-0220-1480', '01002201480', '본인', TRUE, 'UNKNOWN');
INSERT INTO party (brokerage_id, party_type, name, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), 'PERSON', '천O아', '합성 데이터 · P013');
INSERT INTO party_contact (brokerage_id, party_id, contact_method, contact_value,
    normalized_contact_value, contact_label, is_primary, contactability_status)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '천O아'), 'PHONE', '010-0230-5270', '01002305270', '본인', TRUE, 'OK');
INSERT INTO party (brokerage_id, party_type, name, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), 'PERSON', '문O진', '합성 데이터 · P014');
INSERT INTO party_contact (brokerage_id, party_id, contact_method, contact_value,
    normalized_contact_value, contact_label, is_primary, contactability_status)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '문O진'), 'PHONE', '010-0240-9060', '01002409060', '본인', TRUE, 'OK');
INSERT INTO party (brokerage_id, party_type, name, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), 'PERSON', '문O아', '합성 데이터 · P015');
INSERT INTO party_contact (brokerage_id, party_id, contact_method, contact_value,
    normalized_contact_value, contact_label, is_primary, contactability_status)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '문O아'), 'PHONE', '010-0250-3850', '01002503850', '본인', TRUE, 'OK');
INSERT INTO party (brokerage_id, party_type, name, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), 'PERSON', '구O태', '합성 데이터 · P016');
INSERT INTO party_contact (brokerage_id, party_id, contact_method, contact_value,
    normalized_contact_value, contact_label, is_primary, contactability_status)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '구O태'), 'PHONE', '010-0260-7640', '01002607640', '본인', TRUE, 'OK');
INSERT INTO party (brokerage_id, party_type, name, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), 'PERSON', '봉O림', '합성 데이터 · P017');
INSERT INTO party_contact (brokerage_id, party_id, contact_method, contact_value,
    normalized_contact_value, contact_label, is_primary, contactability_status)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '봉O림'), 'PHONE', '010-0270-2430', '01002702430', '본인', TRUE, 'OK');
INSERT INTO party (brokerage_id, party_type, name, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), 'PERSON', '백O연', '합성 데이터 · P018');
INSERT INTO party_contact (brokerage_id, party_id, contact_method, contact_value,
    normalized_contact_value, contact_label, is_primary, contactability_status)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '백O연'), 'PHONE', '010-0280-6220', '01002806220', '본인', TRUE, 'OK');
INSERT INTO party (brokerage_id, party_type, name, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), 'PERSON', '차O민', '합성 데이터 · P019');
INSERT INTO party_contact (brokerage_id, party_id, contact_method, contact_value,
    normalized_contact_value, contact_label, is_primary, contactability_status)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '차O민'), 'PHONE', '010-0290-1010', '01002901010', '본인', TRUE, 'OK');
INSERT INTO party (brokerage_id, party_type, name, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), 'PERSON', '신O범', '합성 데이터 · P020');
INSERT INTO party_contact (brokerage_id, party_id, contact_method, contact_value,
    normalized_contact_value, contact_label, is_primary, contactability_status)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '신O범'), 'PHONE', '010-0300-4800', '01003004800', '본인', TRUE, 'UNREACHABLE');
INSERT INTO party (brokerage_id, party_type, name, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), 'PERSON', '고O정', '합성 데이터 · P021');
INSERT INTO party_contact (brokerage_id, party_id, contact_method, contact_value,
    normalized_contact_value, contact_label, is_primary, contactability_status)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '고O정'), 'PHONE', '010-0310-8590', '01003108590', '본인', TRUE, 'OK');
INSERT INTO party (brokerage_id, party_type, name, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), 'PERSON', '엄O현', '합성 데이터 · P022');
INSERT INTO party_contact (brokerage_id, party_id, contact_method, contact_value,
    normalized_contact_value, contact_label, is_primary, contactability_status)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '엄O현'), 'PHONE', '010-0320-3380', '01003203380', '본인', TRUE, 'OK');
INSERT INTO party (brokerage_id, party_type, name, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), 'PERSON', '류O경', '합성 데이터 · P023');
INSERT INTO party_contact (brokerage_id, party_id, contact_method, contact_value,
    normalized_contact_value, contact_label, is_primary, contactability_status)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '류O경'), 'PHONE', '010-0330-7170', '01003307170', '본인', TRUE, 'OK');
INSERT INTO party (brokerage_id, party_type, name, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), 'PERSON', '표O건', '합성 데이터 · P024');
INSERT INTO party_contact (brokerage_id, party_id, contact_method, contact_value,
    normalized_contact_value, contact_label, is_primary, contactability_status)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '표O건'), 'PHONE', '010-0340-1960', '01003401960', '본인', TRUE, 'OK');
INSERT INTO party (brokerage_id, party_type, name, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), 'PERSON', '표O아', '합성 데이터 · P025');
INSERT INTO party_contact (brokerage_id, party_id, contact_method, contact_value,
    normalized_contact_value, contact_label, is_primary, contactability_status)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '표O아'), 'PHONE', '010-0350-5750', '01003505750', '본인', TRUE, 'OK');
INSERT INTO party (brokerage_id, party_type, name, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), 'PERSON', '방O건', '합성 데이터 · P026');
INSERT INTO party_contact (brokerage_id, party_id, contact_method, contact_value,
    normalized_contact_value, contact_label, is_primary, contactability_status)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '방O건'), 'PHONE', '010-0360-9540', '01003609540', '본인', TRUE, 'OK');
INSERT INTO party (brokerage_id, party_type, name, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), 'PERSON', '방O수', '합성 데이터 · P027');
INSERT INTO party_contact (brokerage_id, party_id, contact_method, contact_value,
    normalized_contact_value, contact_label, is_primary, contactability_status)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '방O수'), 'PHONE', '010-0370-4330', '01003704330', '본인', TRUE, 'OK');
INSERT INTO party (brokerage_id, party_type, name, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), 'PERSON', '지O훈', '합성 데이터 · P028');
INSERT INTO party_contact (brokerage_id, party_id, contact_method, contact_value,
    normalized_contact_value, contact_label, is_primary, contactability_status)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '지O훈'), 'PHONE', '010-0380-8120', '01003808120', '본인', TRUE, 'OK');
INSERT INTO party (brokerage_id, party_type, name, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), 'PERSON', '편O주', '합성 데이터 · P029');
INSERT INTO party_contact (brokerage_id, party_id, contact_method, contact_value,
    normalized_contact_value, contact_label, is_primary, contactability_status)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '편O주'), 'PHONE', '010-0390-2910', '01003902910', '본인', TRUE, 'OK');
INSERT INTO party (brokerage_id, party_type, name, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), 'PERSON', '정O우', '합성 데이터 · P030');
INSERT INTO party_contact (brokerage_id, party_id, contact_method, contact_value,
    normalized_contact_value, contact_label, is_primary, contactability_status)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '정O우'), 'PHONE', '010-0400-6700', '01004006700', '본인', TRUE, 'OK');
INSERT INTO party (brokerage_id, party_type, name, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), 'PERSON', '탁O림', '합성 데이터 · P031');
INSERT INTO party_contact (brokerage_id, party_id, contact_method, contact_value,
    normalized_contact_value, contact_label, is_primary, contactability_status)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '탁O림'), 'PHONE', '010-0410-1490', '01004101490', '본인', TRUE, 'OK');
INSERT INTO party (brokerage_id, party_type, name, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), 'PERSON', '김O수', '합성 데이터 · P032');
INSERT INTO party_contact (brokerage_id, party_id, contact_method, contact_value,
    normalized_contact_value, contact_label, is_primary, contactability_status)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '김O수'), 'PHONE', '010-0420-5280', '01004205280', '본인', TRUE, 'OK');
INSERT INTO party (brokerage_id, party_type, name, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), 'PERSON', '박O희', '합성 데이터 · P033');
INSERT INTO party_contact (brokerage_id, party_id, contact_method, contact_value,
    normalized_contact_value, contact_label, is_primary, contactability_status)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '박O희'), 'PHONE', '010-0430-9070', '01004309070', '본인', TRUE, 'OK');
INSERT INTO party_contact (brokerage_id, party_id, contact_method, contact_value,
    normalized_contact_value, contact_label, is_primary, contactability_status)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '박O희'), 'PHONE', '010-0431-9449', '01004319449', '배우자', FALSE, 'OK');
INSERT INTO party (brokerage_id, party_type, name, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), 'PERSON', '이O민', '합성 데이터 · P034');
INSERT INTO party_contact (brokerage_id, party_id, contact_method, contact_value,
    normalized_contact_value, contact_label, is_primary, contactability_status)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '이O민'), 'PHONE', '010-0440-3860', '01004403860', '본인', TRUE, 'UNKNOWN');
INSERT INTO party (brokerage_id, party_type, name, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), 'PERSON', '최O정', '합성 데이터 · P035');
INSERT INTO party_contact (brokerage_id, party_id, contact_method, contact_value,
    normalized_contact_value, contact_label, is_primary, contactability_status)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '최O정'), 'PHONE', '010-0450-7650', '01004507650', '본인', TRUE, 'OK');
INSERT INTO party (brokerage_id, party_type, name, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), 'PERSON', '정O래', '합성 데이터 · P036');
INSERT INTO party_contact (brokerage_id, party_id, contact_method, contact_value,
    normalized_contact_value, contact_label, is_primary, contactability_status)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '정O래'), 'PHONE', '010-0460-2440', '01004602440', '본인', TRUE, 'OK');
INSERT INTO party (brokerage_id, party_type, name, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), 'PERSON', '한O빈', '합성 데이터 · P037');
INSERT INTO party_contact (brokerage_id, party_id, contact_method, contact_value,
    normalized_contact_value, contact_label, is_primary, contactability_status)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '한O빈'), 'PHONE', '010-0470-6230', '01004706230', '본인', TRUE, 'CAUTION');

-- ══ 002/009 세대 · 관계 · 매물 · 상담로그 ════════════════════════════
-- M01  203동 1101호 · 33평 J1 · 자가 · A-2-1/A-3-2
--   기대: 중간 79.0점 — 컷으로는 강함이지만 공동명의 + 가격 진술 상충(주① 24.5 / 주② 23.3)으로 1단계 강등. 추정가는 최신 화자 주①의 24.5억을 쓰고 주②의 23.3억은 병기한다
INSERT INTO property_unit (brokerage_id, complex_id, building_number, unit_number,
    floor_number, orientation, pyeong, exclusive_area_sqm, supply_area_sqm,
    unit_type, is_expanded, built_in_features, facility_condition,
    tenancy_status, current_deposit_amount, current_monthly_rent_amount, loan_amount,
    tenancy_expiry_date, tenancy_raw_text, assigned_user_id, memo,
    lifecycle_status, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_complex
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '한들마을 센트럴파크'),
    '203', '1101', '11', '남향', 33, 84.96, 112.74,
    'J1', TRUE, '붙박이장(안방·작은방), 식기세척기, 김치냉장고, 인덕션', '올수리 — 25년 도배·장판·욕실 2개 전체',
    'SELF_OCCUPIED', NULL, NULL, NULL,
    NULL, NULL, (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), 'J1 · 확장',
    'LISTED', '{"unit_id": "M01", "f3_case": ["A-2-1", "A-3-2"], "handover_pref_date": "2026-12-15", "handover_blocked_reason": null, "src_synthetic_unit": "U0012", "unresolved_speakers": ["세②", "중ⓐ"]}'::jsonb);
INSERT INTO property_unit_party_relation (brokerage_id, unit_id, party_id, role,
    role_index, is_primary, is_co_owner, valid_from, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M01'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '윤O호'),
    'OWNER_SIDE', 1, TRUE, TRUE, '2024-01-01', '상담로그 화자 주①');
INSERT INTO property_unit_party_relation (brokerage_id, unit_id, party_id, role,
    role_index, is_primary, is_co_owner, valid_from, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M01'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '배O란'),
    'OWNER_SIDE', 2, FALSE, TRUE, '2024-01-01', '상담로그 화자 주②');
INSERT INTO property_listing (brokerage_id, unit_id, client_party_id, received_at, status,
    is_sale_available, sale_price, is_jeonse_available, jeonse_deposit_amount,
    is_monthly_rent_available, monthly_rent_deposit_amount, monthly_rent_amount,
    price_raw_text, handover_condition, assigned_user_id, memo, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M01'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '윤O호'), '2026-07-01', 'ADVERTISING',
    TRUE, 2230000000, FALSE, NULL,
    FALSE, NULL, NULL,
    '22.3억', 'NEGOTIABLE', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), '중간 79.0점 — 컷으로는 강함이지만 공동명의 + 가격 진술 상충(주① 24.5 / 주② 23.3)으로 1단계 강등. 추정가는 최신 화자 주①의 24.5억을 쓰고 주②의 23.3억은 병기한다', '{"unit_id": "M01", "f3_case": ["A-2-1", "A-3-2"], "price_revision": null, "handover_condition_kr": "협의"}'::jsonb);
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-06-11 19:42:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '24.5억은 받아야 한다. 아래로는 생각 없다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '윤O호'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M01'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M01'), '{"raw_line": "[26-06-11 19:42 주]①24.5억은 받아야 한다. 아래로는 생각 없다", "origin": "케이스:A-2-1,A-3-2", "case_log": true, "log_type": "케이스", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-05-24 12:10:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 2,
    '23.3억에 진행한다. 전에 봐 두었던집이 매매가 되었으면 포기한다.', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '배O란'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M01'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M01'), '{"raw_line": "[26-05-24 12:10 주]②23.3억에 진행한다. 전에 봐 두었던집이 매매가 되었으면 포기한다.", "origin": "케이스:A-2-1,A-3-2", "case_log": true, "log_type": "케이스", "speaker_key": "주②", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-05-14 10:31:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '공동명의라 집사람이랑 상의해야 한다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '윤O호'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M01'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M01'), '{"raw_line": "[26-05-14 10:31 주]①공동명의라 집사람이랑 상의해야 한다", "origin": "케이스:A-2-1,A-3-2", "case_log": true, "log_type": "케이스", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-04-02 14:55:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 2,
    '12월 중순이면 비워줄 수 있다. 갈 곳은 정해뒀다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '배O란'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M01'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M01'), '{"raw_line": "[26-04-02 14:55 주]②12월 중순이면 비워줄 수 있다. 갈 곳은 정해뒀다", "origin": "케이스:A-2-1,A-3-2", "case_log": true, "log_type": "케이스", "speaker_key": "주②", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2023-10-13 17:57:00+09', 'SMS',
    'OUTBOUND', 'UNREACHABLE', 'OWNER_SIDE', 2,
    '8678/연결이되지않아멘트/문자.명함발송', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '배O란'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M01'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M01'), '{"raw_line": "[23-10-13 17:57 주]②8678/연결이되지않아멘트/문자.명함발송", "origin": "합성CSV:U0012#6", "case_log": false, "log_type": "부재/불통", "speaker_key": "주②", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2023-01-11 12:11:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 2,
    '예담공인중개사에서 매매 20.4억으로 받음', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '배O란'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M01'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M01'), '{"raw_line": "[23-01-11 12:11 주]②예담공인중개사에서 매매 20.4억으로 받음", "origin": "합성CSV:U0012#7", "case_log": false, "log_type": "매물접수", "speaker_key": "주②", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2022-11-21 17:52:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '끊을께요', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '윤O호'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M01'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M01'), '{"raw_line": "[22-11-21 17:52 주]①끊을께요", "origin": "합성CSV:U0012#8", "case_log": false, "log_type": "계획없음/거절", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2020-03-31 11:20:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 2,
    '월세 보증금 2.5억으로 임차료 얼마인지 문의함', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '배O란'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M01'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M01'), '{"raw_line": "[20-03-31 11:20 주]②월세 보증금 2.5억으로 임차료 얼마인지 문의함", "origin": "합성CSV:U0012#9", "case_log": false, "log_type": "시세문의/상담", "speaker_key": "주②", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2020-02-26 19:55:00+09', 'SMS',
    'OUTBOUND', 'UNREACHABLE', 'CO_BROKER', 1,
    '스팸걸린듯. 문자만 발송', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M01'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M01'), '{"raw_line": "[20-02-26 19:55 중]ⓐ스팸걸린듯. 문자만 발송", "origin": "합성CSV:U0012#10", "case_log": false, "log_type": "부재/불통", "speaker_key": "중ⓐ", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2018-12-12 10:23:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'TENANT', 2,
    '안받음.', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M01'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M01'), '{"raw_line": "[18-12-12 10:23 세]②안받음.", "origin": "합성CSV:U0012#12", "case_log": false, "log_type": "부재/불통", "speaker_key": "세②", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));

-- M02  108동 2701호 · 33평 J1 · 임차 · A-2-3
--   기대: 기각 G4 — 인도 2027-06-15 > C01 마감 2027-03-02
INSERT INTO property_unit (brokerage_id, complex_id, building_number, unit_number,
    floor_number, orientation, pyeong, exclusive_area_sqm, supply_area_sqm,
    unit_type, is_expanded, built_in_features, facility_condition,
    tenancy_status, current_deposit_amount, current_monthly_rent_amount, loan_amount,
    tenancy_expiry_date, tenancy_raw_text, assigned_user_id, memo,
    lifecycle_status, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_complex
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '한들마을 센트럴파크'),
    '108', '2701', '27', '남향', 33, 84.96, 112.74,
    'J1', FALSE, '붙박이장(안방), 가스쿡탑', '원상태 — 준공 당시 마감 유지',
    'LEASED', 1150000000, NULL, 240000000,
    '2027-06-15', '전세 11.5억 (25.06~27.06), 융자 2.4억', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), 'J1 · 비확장',
    'LISTED', '{"unit_id": "M02", "f3_case": ["A-2-3"], "handover_pref_date": null, "handover_blocked_reason": null, "src_synthetic_unit": "U0014", "unresolved_speakers": ["주②"]}'::jsonb);
INSERT INTO property_unit_party_relation (brokerage_id, unit_id, party_id, role,
    role_index, is_primary, is_co_owner, valid_from, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M02'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '서O철'),
    'OWNER_SIDE', 1, TRUE, FALSE, '2024-01-01', '상담로그 화자 주①');
INSERT INTO property_unit_party_relation (brokerage_id, unit_id, party_id, role,
    role_index, is_primary, is_co_owner, valid_from, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M02'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '심O규'),
    'TENANT', 1, FALSE, FALSE, '2024-01-01', '상담로그 화자 세①');
INSERT INTO property_listing (brokerage_id, unit_id, client_party_id, received_at, status,
    is_sale_available, sale_price, is_jeonse_available, jeonse_deposit_amount,
    is_monthly_rent_available, monthly_rent_deposit_amount, monthly_rent_amount,
    price_raw_text, handover_condition, assigned_user_id, memo, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M02'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '서O철'), '2026-07-01', 'ADVERTISING',
    TRUE, 2200000000, FALSE, NULL,
    FALSE, NULL, NULL,
    '22.0억', 'AFTER_TENANCY_EXPIRY', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), '기각 G4 — 인도 2027-06-15 > C01 마감 2027-03-02', '{"unit_id": "M02", "f3_case": ["A-2-3"], "price_revision": null, "handover_condition_kr": "임차만기후명도"}'::jsonb);
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-08-01 13:15:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '팔 생각 있다. 근데 세입자 만기가 27년 6월이라 그전엔 못 뺀다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '서O철'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M02'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M02'), '{"raw_line": "[26-08-01 13:15 주]①팔 생각 있다. 근데 세입자 만기가 27년 6월이라 그전엔 못 뺀다", "origin": "케이스:A-2-3", "case_log": true, "log_type": "케이스", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-07-10 17:02:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '22억 생각하고 있고 크게 안 깎는다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '서O철'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M02'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M02'), '{"raw_line": "[26-07-10 17:02 주]①22억 생각하고 있고 크게 안 깎는다", "origin": "케이스:A-2-3", "case_log": true, "log_type": "케이스", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-02-14 11:30:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'TENANT', 1,
    '저희는 만기까지 살 거예요. 갱신 얘기 들었습니다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '심O규'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M02'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M02'), '{"raw_line": "[26-02-14 11:30 세]①저희는 만기까지 살 거예요. 갱신 얘기 들었습니다", "origin": "케이스:A-2-3", "case_log": true, "log_type": "케이스", "speaker_key": "세①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2024-11-23 17:23:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '27.1억까지는 가능하다.', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '서O철'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M02'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M02'), '{"raw_line": "[24-11-23 17:23 주]①27.1억까지는 가능하다.", "origin": "합성CSV:U0014#1", "case_log": false, "log_type": "조건협의", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2023-10-24 13:48:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '1층이라도 정원 누릴수 있어 좋다고 하시며 시세 문의', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '서O철'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M02'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M02'), '{"raw_line": "[23-10-24 13:48 주]①1층이라도 정원 누릴수 있어 좋다고 하시며 시세 문의", "origin": "합성CSV:U0014#2", "case_log": false, "log_type": "시세문의/상담", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2023-02-23 11:24:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 2,
    '오늘까지 27.3억까지는 해 주는데 다른 집이 매도 되면 포기한다.', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M02'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M02'), '{"raw_line": "[23-02-23 11:24 주]②오늘까지 27.3억까지는 해 주는데 다른 집이 매도 되면 포기한다.", "origin": "합성CSV:U0014#3", "case_log": false, "log_type": "조건협의", "speaker_key": "주②", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2022-01-17 15:06:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 2,
    '1층이라도 정원 누릴수 있어 좋다고 하시며 시세 문의', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M02'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M02'), '{"raw_line": "[22-01-17 15:06 주]②1층이라도 정원 누릴수 있어 좋다고 하시며 시세 문의", "origin": "합성CSV:U0014#4", "case_log": false, "log_type": "시세문의/상담", "speaker_key": "주②", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2021-05-02 15:13:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 2,
    '청솔공인에서 매매 28.5억으로 받음', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M02'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M02'), '{"raw_line": "[21-05-02 15:13 주]②청솔공인에서 매매 28.5억으로 받음", "origin": "합성CSV:U0014#5", "case_log": false, "log_type": "매물접수", "speaker_key": "주②", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2020-06-07 10:49:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '매매 24.5억 / 월세 5억/350만원 동시 진행 원함', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '서O철'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M02'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M02'), '{"raw_line": "[20-06-07 10:49 주]①매매 24.5억 / 월세 5억/350만원 동시 진행 원함", "origin": "합성CSV:U0014#6", "case_log": false, "log_type": "매물접수", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));

-- M03  507동 1101호 · 33평 J2 · 공실 · G1
--   기대: 기각 G1 — 장부는 매매 21.5억(2024 접수)이라 SQL 후보로 올라오지만 최신 진술이 임대(2026-07-19 주②)라 코드가 기각한다. 「매매는 당분간 접는다」로 G2도 함께 걸린다
INSERT INTO property_unit (brokerage_id, complex_id, building_number, unit_number,
    floor_number, orientation, pyeong, exclusive_area_sqm, supply_area_sqm,
    unit_type, is_expanded, built_in_features, facility_condition,
    tenancy_status, current_deposit_amount, current_monthly_rent_amount, loan_amount,
    tenancy_expiry_date, tenancy_raw_text, assigned_user_id, memo,
    lifecycle_status, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_complex
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '한들마을 센트럴파크'),
    '507', '1101', '11', '동향', 33, 84.96, 112.74,
    'J2', FALSE, '붙박이장(안방), 가스쿡탑', '부분수리 — 24년 도배·싱크대',
    'VACANT', NULL, NULL, NULL,
    NULL, NULL, (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), 'J2 · 비확장',
    'LISTED', '{"unit_id": "M03", "f3_case": ["G1"], "handover_pref_date": "2026-10-01", "handover_blocked_reason": null, "src_synthetic_unit": "U0001", "unresolved_speakers": ["주③", "중③"]}'::jsonb);
INSERT INTO property_unit_party_relation (brokerage_id, unit_id, party_id, role,
    role_index, is_primary, is_co_owner, valid_from, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M03'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '임O선'),
    'OWNER_SIDE', 1, TRUE, FALSE, '2024-01-01', '상담로그 화자 주①');
INSERT INTO property_unit_party_relation (brokerage_id, unit_id, party_id, role,
    role_index, is_primary, is_co_owner, valid_from, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M03'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '하O민'),
    'OWNER_SIDE', 2, FALSE, FALSE, '2024-01-01', '상담로그 화자 주②');
INSERT INTO property_listing (brokerage_id, unit_id, client_party_id, received_at, status,
    is_sale_available, sale_price, is_jeonse_available, jeonse_deposit_amount,
    is_monthly_rent_available, monthly_rent_deposit_amount, monthly_rent_amount,
    price_raw_text, handover_condition, assigned_user_id, memo, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M03'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '임O선'), '2026-07-01', 'ADVERTISING',
    TRUE, 2150000000, FALSE, NULL,
    FALSE, NULL, NULL,
    '21.5억', 'IMMEDIATE', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), '기각 G1 — 장부는 매매 21.5억(2024 접수)이라 SQL 후보로 올라오지만 최신 진술이 임대(2026-07-19 주②)라 코드가 기각한다. 「매매는 당분간 접는다」로 G2도 함께 걸린다', '{"unit_id": "M03", "f3_case": ["G1"], "price_revision": null, "handover_condition_kr": "즉시명도"}'::jsonb);
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-07-19 15:45:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 2,
    '매매는 당분간 접는다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '하O민'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M03'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M03'), '{"raw_line": "[26-07-19 15:45 주]②매매는 당분간 접는다", "origin": "케이스:G1", "case_log": true, "log_type": "케이스", "speaker_key": "주②", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-07-19 15:44:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 2,
    '월세로 돌리기로 했다. 보증 2억/월 330만원', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '하O민'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M03'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M03'), '{"raw_line": "[26-07-19 15:44 주]②월세로 돌리기로 했다. 보증 2억/월 330만원", "origin": "케이스:G1", "case_log": true, "log_type": "케이스", "speaker_key": "주②", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2024-05-06 14:00:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 2,
    '21.5억에 매매 내놓음', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '하O민'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M03'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M03'), '{"raw_line": "[24-05-06 14:00 주]②21.5억에 매매 내놓음", "origin": "케이스:G1", "case_log": true, "log_type": "케이스", "speaker_key": "주②", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2023-12-31 12:31:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 3,
    '시세표 보내드림. 내년쯤 움직여 볼까 계획한다고 하심', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M03'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M03'), '{"raw_line": "[23-12-31 12:31 주]③시세표 보내드림. 내년쯤 움직여 볼까 계획한다고 하심", "origin": "합성CSV:U0001#4", "case_log": false, "log_type": "시세문의/상담", "speaker_key": "주③", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2023-10-26 13:44:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'CO_BROKER', 3,
    '매도 시기 고민중. 세금 상담 받아보고 결정한다고 함', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M03'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M03'), '{"raw_line": "[23-10-26 13:44 중]③매도 시기 고민중. 세금 상담 받아보고 결정한다고 함", "origin": "합성CSV:U0001#5", "case_log": false, "log_type": "시세문의/상담", "speaker_key": "중③", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2023-01-05 13:02:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 3,
    '소유자 종료. 법인 아니라 하심', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M03'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M03'), '{"raw_line": "[23-01-05 13:02 주]③소유자 종료. 법인 아니라 하심", "origin": "합성CSV:U0001#6", "case_log": false, "log_type": "정보갱신", "speaker_key": "주③", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2021-09-17 17:40:00+09', 'SMS',
    'OUTBOUND', 'UNREACHABLE', 'OWNER_SIDE', 1,
    '남/부재[문자.명함발송]', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '임O선'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M03'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M03'), '{"raw_line": "[21-09-17 17:40 주]①남/부재[문자.명함발송]", "origin": "합성CSV:U0001#8", "case_log": false, "log_type": "부재/불통", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));

-- M04  106동 2104호 · 33평 J1 · 자가 · A-1-4
--   기대: 강함 79.0점 — 양보 1.5억을 차감해 이격 +3.4% → 가격 22점. 양보를 못 읽으면 이격 +9.8% → 10점 → 중간 67.0점으로 내려간다
INSERT INTO property_unit (brokerage_id, complex_id, building_number, unit_number,
    floor_number, orientation, pyeong, exclusive_area_sqm, supply_area_sqm,
    unit_type, is_expanded, built_in_features, facility_condition,
    tenancy_status, current_deposit_amount, current_monthly_rent_amount, loan_amount,
    tenancy_expiry_date, tenancy_raw_text, assigned_user_id, memo,
    lifecycle_status, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_complex
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '한들마을 센트럴파크'),
    '106', '2104', '21', '남향', 33, 84.96, 112.74,
    'J1', TRUE, '붙박이장(안방·작은방), 식기세척기, 김치냉장고, 인덕션', '올수리 — 25년 도배·장판·욕실 2개 전체',
    'SELF_OCCUPIED', NULL, NULL, NULL,
    NULL, NULL, (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), 'J1 · 확장',
    'LISTED', '{"unit_id": "M04", "f3_case": ["A-1-4"], "handover_pref_date": "2026-12-31", "handover_blocked_reason": null, "src_synthetic_unit": "U0031", "unresolved_speakers": ["주②", "주ⓑ"]}'::jsonb);
INSERT INTO property_unit_party_relation (brokerage_id, unit_id, party_id, role,
    role_index, is_primary, is_co_owner, valid_from, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M04'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '노O기'),
    'OWNER_SIDE', 1, TRUE, FALSE, '2024-01-01', '상담로그 화자 주①');
INSERT INTO property_listing (brokerage_id, unit_id, client_party_id, received_at, status,
    is_sale_available, sale_price, is_jeonse_available, jeonse_deposit_amount,
    is_monthly_rent_available, monthly_rent_deposit_amount, monthly_rent_amount,
    price_raw_text, handover_condition, assigned_user_id, memo, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M04'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '노O기'), '2026-07-01', 'ADVERTISING',
    TRUE, 2580000000, FALSE, NULL,
    FALSE, NULL, NULL,
    '25.8억', 'ON_SETTLEMENT', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), '강함 79.0점 — 양보 1.5억을 차감해 이격 +3.4% → 가격 22점. 양보를 못 읽으면 이격 +9.8% → 10점 → 중간 67.0점으로 내려간다', '{"unit_id": "M04", "f3_case": ["A-1-4"], "price_revision": null, "handover_condition_kr": "잔금시명도"}'::jsonb);
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-08-11 19:31:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '잔금만 연말까지 맞춰주면 된다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '노O기'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M04'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M04'), '{"raw_line": "[26-08-11 19:31 주]①잔금만 연말까지 맞춰주면 된다", "origin": "케이스:A-1-4", "case_log": true, "log_type": "케이스", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-08-11 19:30:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '25.8억 받고 싶은데 좋은 손님이면 1억 5천까지는 뺀다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '노O기'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M04'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M04'), '{"raw_line": "[26-08-11 19:30 주]①25.8억 받고 싶은데 좋은 손님이면 1억 5천까지는 뺀다", "origin": "케이스:A-1-4", "case_log": true, "log_type": "케이스", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-07-28 12:10:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '지방 내려가기로 해서 정리해야 한다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '노O기'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M04'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M04'), '{"raw_line": "[26-07-28 12:10 주]①지방 내려가기로 해서 정리해야 한다", "origin": "케이스:A-1-4", "case_log": true, "log_type": "케이스", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2024-07-13 17:45:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '월세 내놓음. 보증 4억/320만원, 반려동물X 외국인X 조건', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '노O기'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M04'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M04'), '{"raw_line": "[24-07-13 17:45 주]①월세 내놓음. 보증 4억/320만원, 반려동물X 외국인X 조건", "origin": "합성CSV:U0031#4", "case_log": false, "log_type": "매물접수", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2023-03-01 17:41:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 2,
    '최소 21.7억은 해야 매도 한다.', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M04'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M04'), '{"raw_line": "[23-03-01 17:41 주]②최소 21.7억은 해야 매도 한다.", "origin": "합성CSV:U0031#5", "case_log": false, "log_type": "조건협의", "speaker_key": "주②", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2022-03-02 17:01:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 2,
    '본인집 아님/매매계획 없음', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M04'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M04'), '{"raw_line": "[22-03-02 17:01 주]②본인집 아님/매매계획 없음", "origin": "합성CSV:U0031#6", "case_log": false, "log_type": "계획없음/거절", "speaker_key": "주②", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2022-02-28 15:28:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 2,
    '전세 11.0억 / 월세 보증 2억에 350만원 시세 문의하심', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M04'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M04'), '{"raw_line": "[22-02-28 15:28 주]②전세 11.0억 / 월세 보증 2억에 350만원 시세 문의하심", "origin": "합성CSV:U0031#7", "case_log": false, "log_type": "시세문의/상담", "speaker_key": "주②", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2021-06-19 11:54:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 2,
    '그런 계획 없다고 함', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M04'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M04'), '{"raw_line": "[21-06-19 11:54 주]②그런 계획 없다고 함", "origin": "합성CSV:U0031#8", "case_log": false, "log_type": "계획없음/거절", "speaker_key": "주②", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2019-10-29 17:49:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 2,
    '안받음.', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M04'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M04'), '{"raw_line": "[19-10-29 17:49 주]ⓑ안받음.", "origin": "합성CSV:U0031#9", "case_log": false, "log_type": "부재/불통", "speaker_key": "주ⓑ", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));

-- M05  407동 1901호 · 33평 J2 · 불명 · D-1
--   기대: 약함 42.8점 — 로그 전부 불통. 가격·시점 판정 불가(각 배점 절반×0.7) + 접촉 불가. 보류·근거부족 이중 강등. 결과가 SQL 매칭과 같아진다
INSERT INTO property_unit (brokerage_id, complex_id, building_number, unit_number,
    floor_number, orientation, pyeong, exclusive_area_sqm, supply_area_sqm,
    unit_type, is_expanded, built_in_features, facility_condition,
    tenancy_status, current_deposit_amount, current_monthly_rent_amount, loan_amount,
    tenancy_expiry_date, tenancy_raw_text, assigned_user_id, memo,
    lifecycle_status, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_complex
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '한들마을 센트럴파크'),
    '407', '1901', '19', '북향', 33, 84.96, 112.74,
    'J2', FALSE, '없음', '원상태 — 준공 당시 마감 유지',
    'UNKNOWN', NULL, NULL, NULL,
    NULL, NULL, (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), 'J2 · 비확장',
    'LISTED', '{"unit_id": "M05", "f3_case": ["D-1"], "handover_pref_date": null, "handover_blocked_reason": null, "src_synthetic_unit": "U0002", "unresolved_speakers": ["중①"]}'::jsonb);
INSERT INTO property_unit_party_relation (brokerage_id, unit_id, party_id, role,
    role_index, is_primary, is_co_owner, valid_from, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M05'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '오O규'),
    'OWNER_SIDE', 1, TRUE, FALSE, '2024-01-01', '상담로그 화자 주①');
INSERT INTO property_listing (brokerage_id, unit_id, client_party_id, received_at, status,
    is_sale_available, sale_price, is_jeonse_available, jeonse_deposit_amount,
    is_monthly_rent_available, monthly_rent_deposit_amount, monthly_rent_amount,
    price_raw_text, handover_condition, assigned_user_id, memo, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M05'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '오O규'), '2026-07-01', 'ADVERTISING',
    TRUE, 2300000000, FALSE, NULL,
    FALSE, NULL, NULL,
    '23.0억', 'NEGOTIABLE', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), '약함 42.8점 — 로그 전부 불통. 가격·시점 판정 불가(각 배점 절반×0.7) + 접촉 불가. 보류·근거부족 이중 강등. 결과가 SQL 매칭과 같아진다', '{"unit_id": "M05", "f3_case": ["D-1"], "price_revision": null, "handover_condition_kr": "협의"}'::jsonb);
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-04-02 10:05:00+09', 'SMS',
    'OUTBOUND', 'UNREACHABLE', 'OTHER', 1,
    '부재중. 매매,임대계획 문자발송(시세표,명함)', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M05'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M05'), '{"raw_line": "[26-04-02 10:05 기]①부재중. 매매,임대계획 문자발송(시세표,명함)", "origin": "케이스:D-1", "case_log": true, "log_type": "케이스", "speaker_key": "기①", "needs_relation": false, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2025-08-17 16:40:00+09', 'CALL',
    'OUTBOUND', 'UNREACHABLE', 'OWNER_SIDE', 1,
    '지금거신 전화는 없는번호', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '오O규'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M05'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M05'), '{"raw_line": "[25-08-17 16:40 주]①지금거신 전화는 없는번호", "origin": "케이스:D-1", "case_log": true, "log_type": "케이스", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2023-03-20 16:49:00+09', 'CALL',
    'OUTBOUND', 'UNREACHABLE', 'OWNER_SIDE', 1,
    '전원꺼짐. 추후 재통화 예정', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '오O규'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M05'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M05'), '{"raw_line": "[23-03-20 16:49 주]①전원꺼짐. 추후 재통화 예정", "origin": "합성CSV:U0002#3", "case_log": false, "log_type": "부재/불통", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2022-07-02 18:23:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '매물 광고 여부 확인 요청. 아직 한군데만 준다고 하심', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '오O규'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M05'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M05'), '{"raw_line": "[22-07-02 18:23 주]①매물 광고 여부 확인 요청. 아직 한군데만 준다고 하심", "origin": "합성CSV:U0002#4", "case_log": false, "log_type": "시세문의/상담", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2022-06-07 19:38:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '한군데 부동산에 내 놨다. 29.5억에 내 놓지만 조정해 줄 것 같음. 갈아타기 목적', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '오O규'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M05'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M05'), '{"raw_line": "[22-06-07 19:38 주]①한군데 부동산에 내 놨다. 29.5억에 내 놓지만 조정해 줄 것 같음. 갈아타기 목적", "origin": "합성CSV:U0002#5", "case_log": false, "log_type": "매물접수", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2022-01-12 11:56:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'CO_BROKER', 1,
    '전세 광고 요청. 아침에 사진 받기로 함', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M05'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M05'), '{"raw_line": "[22-01-12 11:56 중]①전세 광고 요청. 아침에 사진 받기로 함", "origin": "합성CSV:U0002#6", "case_log": false, "log_type": "매물접수", "speaker_key": "중①", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2021-10-17 15:54:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '삼성공인 전완 12.7억 21.09.07', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '오O규'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M05'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M05'), '{"raw_line": "[21-10-17 15:54 주]①삼성공인 전완 12.7억 21.09.07", "origin": "합성CSV:U0002#7", "case_log": false, "log_type": "계약완료-전세", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2021-03-20 18:27:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OTHER', 1,
    '집주인 입주하여 보증금 12억~13억 월세 구함, 트인뷰 선호(임차인)', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M05'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M05'), '{"raw_line": "[21-03-20 18:27 기]①집주인 입주하여 보증금 12억~13억 월세 구함, 트인뷰 선호(임차인)", "origin": "합성CSV:U0002#8", "case_log": false, "log_type": "매물접수", "speaker_key": "기①", "needs_relation": false, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));

-- M06  601동 2302호 · 43평 K1 · 자가 · SQL-GATE
--   기대: C01 기준 후보 제외 — 추정 상한 23.5억 게이트(27.02억) 밖. LLM 태우기 전 걸러짐
INSERT INTO property_unit (brokerage_id, complex_id, building_number, unit_number,
    floor_number, orientation, pyeong, exclusive_area_sqm, supply_area_sqm,
    unit_type, is_expanded, built_in_features, facility_condition,
    tenancy_status, current_deposit_amount, current_monthly_rent_amount, loan_amount,
    tenancy_expiry_date, tenancy_raw_text, assigned_user_id, memo,
    lifecycle_status, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_complex
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '한들마을 센트럴파크'),
    '601', '2302', '23', '남향', 43, 114.87, 148.2,
    'K1', TRUE, '붙박이장(안방·작은방), 식기세척기, 김치냉장고, 인덕션', '올수리 — 25년 도배·장판·욕실 2개 전체',
    'SELF_OCCUPIED', NULL, NULL, NULL,
    NULL, NULL, (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), 'K1 · 확장',
    'LISTED', '{"unit_id": "M06", "f3_case": ["SQL-GATE"], "handover_pref_date": "2026-11-01", "handover_blocked_reason": null, "src_synthetic_unit": "U0051", "unresolved_speakers": []}'::jsonb);
INSERT INTO property_unit_party_relation (brokerage_id, unit_id, party_id, role,
    role_index, is_primary, is_co_owner, valid_from, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M06'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '황O식'),
    'OWNER_SIDE', 1, TRUE, FALSE, '2024-01-01', '상담로그 화자 주①');
INSERT INTO property_listing (brokerage_id, unit_id, client_party_id, received_at, status,
    is_sale_available, sale_price, is_jeonse_available, jeonse_deposit_amount,
    is_monthly_rent_available, monthly_rent_deposit_amount, monthly_rent_amount,
    price_raw_text, handover_condition, assigned_user_id, memo, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M06'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '황O식'), '2026-07-01', 'ADVERTISING',
    TRUE, 3150000000, FALSE, NULL,
    FALSE, NULL, NULL,
    '31.5억', 'NEGOTIABLE', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), 'C01 기준 후보 제외 — 추정 상한 23.5억 게이트(27.02억) 밖. LLM 태우기 전 걸러짐', '{"unit_id": "M06", "f3_case": ["SQL-GATE"], "price_revision": null, "handover_condition_kr": "협의"}'::jsonb);
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-08-09 11:00:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '31.5억 아래로는 절대 안 판다. 급할 것 없다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '황O식'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M06'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M06'), '{"raw_line": "[26-08-09 11:00 주]①31.5억 아래로는 절대 안 판다. 급할 것 없다", "origin": "케이스:SQL-GATE", "case_log": true, "log_type": "케이스", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-05-30 14:25:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '작년에도 30억 제안 거절했다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '황O식'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M06'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M06'), '{"raw_line": "[26-05-30 14:25 주]①작년에도 30억 제안 거절했다", "origin": "케이스:SQL-GATE", "case_log": true, "log_type": "케이스", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2024-10-17 15:25:00+09', 'SMS',
    'OUTBOUND', 'UNREACHABLE', 'OWNER_SIDE', NULL,
    '여/부재[문자.명함발송]', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M06'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M06'), '{"raw_line": "[24-10-17 15:25 주]여/부재[문자.명함발송]", "origin": "합성CSV:U0051#1", "case_log": false, "log_type": "부재/불통", "speaker_key": "주", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2024-04-30 13:21:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '매매 24.3억 / 월세 1억/350만원 동시 진행 원함', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '황O식'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M06'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M06'), '{"raw_line": "[24-04-30 13:21 주]①매매 24.3억 / 월세 1억/350만원 동시 진행 원함", "origin": "합성CSV:U0051#2", "case_log": false, "log_type": "매물접수", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2023-06-22 19:58:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '지금 저희 고객님의 전원이 꺼져있습니다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '황O식'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M06'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M06'), '{"raw_line": "[23-06-22 19:58 주]①지금 저희 고객님의 전원이 꺼져있습니다", "origin": "합성CSV:U0051#3", "case_log": false, "log_type": "부재/불통", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2022-11-30 19:26:00+09', 'SMS',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '업무중이라 문자로 달라고 함', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '황O식'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M06'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M06'), '{"raw_line": "[22-11-30 19:26 주]①업무중이라 문자로 달라고 함", "origin": "합성CSV:U0051#4", "case_log": false, "log_type": "계획없음/거절", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2022-07-17 10:57:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '요즘 매매 되냐고 물으심. 25.2억선 얘기드림', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '황O식'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M06'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M06'), '{"raw_line": "[22-07-17 10:57 주]①요즘 매매 되냐고 물으심. 25.2억선 얘기드림", "origin": "합성CSV:U0051#5", "case_log": false, "log_type": "시세문의/상담", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2021-12-21 16:42:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '가격 조정해 줄 것 같음. 갈아타기 목적이라 시기 협의 필요', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '황O식'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M06'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M06'), '{"raw_line": "[21-12-21 16:42 주]ⓐ가격 조정해 줄 것 같음. 갈아타기 목적이라 시기 협의 필요", "origin": "합성CSV:U0051#6", "case_log": false, "log_type": "조건협의", "speaker_key": "주ⓐ", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));

-- M07  205동 2501호 · 33평 J1 · 임차 · A-3-1
--   기대: 중간 88.0점 — 컷으로는 강함이지만 최근 진술이 임차인 발화뿐이라 결정권 미확인 보류 강등. 기각이 아니라 「확인 필요」다
INSERT INTO property_unit (brokerage_id, complex_id, building_number, unit_number,
    floor_number, orientation, pyeong, exclusive_area_sqm, supply_area_sqm,
    unit_type, is_expanded, built_in_features, facility_condition,
    tenancy_status, current_deposit_amount, current_monthly_rent_amount, loan_amount,
    tenancy_expiry_date, tenancy_raw_text, assigned_user_id, memo,
    lifecycle_status, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_complex
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '한들마을 센트럴파크'),
    '205', '2501', '25', '남동향', 33, 84.96, 112.74,
    'J1', FALSE, '붙박이장(안방), 가스쿡탑', '부분수리 — 24년 도배·싱크대',
    'LEASED', 200000000, 3100000, 0,
    '2026-11-30', '월세 보증 2억/월 310만원 (24.12~26.11)', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), 'J1 · 비확장',
    'LISTED', '{"unit_id": "M07", "f3_case": ["A-3-1"], "handover_pref_date": null, "handover_blocked_reason": null, "src_synthetic_unit": "U0006", "unresolved_speakers": ["주②"]}'::jsonb);
INSERT INTO property_unit_party_relation (brokerage_id, unit_id, party_id, role,
    role_index, is_primary, is_co_owner, valid_from, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M07'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '강O주'),
    'OWNER_SIDE', 1, TRUE, FALSE, '2024-01-01', '상담로그 화자 주①');
INSERT INTO property_unit_party_relation (brokerage_id, unit_id, party_id, role,
    role_index, is_primary, is_co_owner, valid_from, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M07'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '천O아'),
    'TENANT', 1, FALSE, FALSE, '2024-01-01', '상담로그 화자 세①');
INSERT INTO property_listing (brokerage_id, unit_id, client_party_id, received_at, status,
    is_sale_available, sale_price, is_jeonse_available, jeonse_deposit_amount,
    is_monthly_rent_available, monthly_rent_deposit_amount, monthly_rent_amount,
    price_raw_text, handover_condition, assigned_user_id, memo, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M07'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '강O주'), '2026-07-01', 'ADVERTISING',
    TRUE, 2250000000, FALSE, NULL,
    FALSE, NULL, NULL,
    '22.5억', 'AFTER_TENANCY_EXPIRY', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), '중간 88.0점 — 컷으로는 강함이지만 최근 진술이 임차인 발화뿐이라 결정권 미확인 보류 강등. 기각이 아니라 「확인 필요」다', '{"unit_id": "M07", "f3_case": ["A-3-1"], "price_revision": null, "handover_condition_kr": "임차만기후명도"}'::jsonb);
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-08-07 16:12:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'TENANT', 1,
    '사장님 연락처는 모르고 관리실 통해서 하세요. 저희는 11월 말에 나갑니다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '천O아'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M07'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M07'), '{"raw_line": "[26-08-07 16:12 세]①사장님 연락처는 모르고 관리실 통해서 하세요. 저희는 11월 말에 나갑니다", "origin": "케이스:A-3-1", "case_log": true, "log_type": "케이스", "speaker_key": "세①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-08-07 16:10:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'TENANT', 1,
    '집주인이 판다고 들었어요. 22.5억 부른다고 하시더라구요', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '천O아'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M07'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M07'), '{"raw_line": "[26-08-07 16:10 세]①집주인이 판다고 들었어요. 22.5억 부른다고 하시더라구요", "origin": "케이스:A-3-1", "case_log": true, "log_type": "케이스", "speaker_key": "세①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2024-11-28 16:51:00+09', 'SMS',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '푸른부동산에서 문자로 물건 줌, 2월 초중순 입주 가능', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '강O주'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M07'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M07'), '{"raw_line": "[24-11-28 16:51 주]①푸른부동산에서 문자로 물건 줌, 2월 초중순 입주 가능", "origin": "합성CSV:U0006#2", "case_log": false, "log_type": "매물접수", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2024-09-20 15:27:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 2,
    '1003호는 아들집이라고 하심', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M07'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M07'), '{"raw_line": "[24-09-20 15:27 주]②1003호는 아들집이라고 하심", "origin": "합성CSV:U0006#3", "case_log": false, "log_type": "정보갱신", "speaker_key": "주②", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2024-09-07 16:43:00+09', 'CALL',
    'OUTBOUND', 'UNREACHABLE', 'OWNER_SIDE', 2,
    '불통', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M07'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M07'), '{"raw_line": "[24-09-07 16:43 주]②불통", "origin": "합성CSV:U0006#4", "case_log": false, "log_type": "부재/불통", "speaker_key": "주②", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2024-01-03 11:39:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '동방공인 물건 받음 전세 9.8억, 융자 1.6억 남김(원금 기준)', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '강O주'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M07'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M07'), '{"raw_line": "[24-01-03 11:39 주]①동방공인 물건 받음 전세 9.8억, 융자 1.6억 남김(원금 기준)", "origin": "합성CSV:U0006#5", "case_log": false, "log_type": "매물접수", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2023-01-10 18:42:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '전세 광고 요청. 아침에 사진 받기로 함', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '강O주'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M07'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M07'), '{"raw_line": "[23-01-10 18:42 주]①전세 광고 요청. 아침에 사진 받기로 함", "origin": "합성CSV:U0006#6", "case_log": false, "log_type": "매물접수", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2023-01-04 16:38:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 2,
    '지금 저희 고객님의 전원이 꺼져있습니다', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M07'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M07'), '{"raw_line": "[23-01-04 16:38 주]②지금 저희 고객님의 전원이 꺼져있습니다", "origin": "합성CSV:U0006#7", "case_log": false, "log_type": "부재/불통", "speaker_key": "주②", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));

-- M08  105동 901호 · 33평 J1 · 자가 · A-1-1
--   기대: 중간 67.0점 — 장부 표기 22.0억 게이트(25.30억) 밖이라 표기 기준 SQL에서는 안 뽑힌다. 추정 23.5억 게이트(27.02억)로는 후보. 이격 +12.3% → 가격 10점
INSERT INTO property_unit (brokerage_id, complex_id, building_number, unit_number,
    floor_number, orientation, pyeong, exclusive_area_sqm, supply_area_sqm,
    unit_type, is_expanded, built_in_features, facility_condition,
    tenancy_status, current_deposit_amount, current_monthly_rent_amount, loan_amount,
    tenancy_expiry_date, tenancy_raw_text, assigned_user_id, memo,
    lifecycle_status, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_complex
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '한들마을 센트럴파크'),
    '105', '901', '9', '남향', 33, 84.96, 112.74,
    'J1', TRUE, '붙박이장(안방·작은방), 식기세척기, 김치냉장고, 인덕션', '올수리 — 25년 도배·장판·욕실 2개 전체',
    'SELF_OCCUPIED', NULL, NULL, NULL,
    NULL, NULL, (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), 'J1 · 확장',
    'LISTED', '{"unit_id": "M08", "f3_case": ["A-1-1"], "handover_pref_date": "2026-12-20", "handover_blocked_reason": null, "src_synthetic_unit": "U0003", "unresolved_speakers": ["세①"]}'::jsonb);
INSERT INTO property_unit_party_relation (brokerage_id, unit_id, party_id, role,
    role_index, is_primary, is_co_owner, valid_from, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M08'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '문O진'),
    'OWNER_SIDE', 1, TRUE, FALSE, '2024-01-01', '상담로그 화자 주①');
INSERT INTO property_unit_party_relation (brokerage_id, unit_id, party_id, role,
    role_index, is_primary, is_co_owner, valid_from, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M08'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '문O아'),
    'OWNER_SIDE', 2, FALSE, FALSE, '2024-01-01', '상담로그 화자 주②');
INSERT INTO property_listing (brokerage_id, unit_id, client_party_id, received_at, status,
    is_sale_available, sale_price, is_jeonse_available, jeonse_deposit_amount,
    is_monthly_rent_available, monthly_rent_deposit_amount, monthly_rent_amount,
    price_raw_text, handover_condition, assigned_user_id, memo, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M08'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '문O진'), '2026-07-01', 'ADVERTISING',
    TRUE, 2640000000, FALSE, NULL,
    FALSE, NULL, NULL,
    '26.4억', 'ON_SETTLEMENT', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), '중간 67.0점 — 장부 표기 22.0억 게이트(25.30억) 밖이라 표기 기준 SQL에서는 안 뽑힌다. 추정 23.5억 게이트(27.02억)로는 후보. 이격 +12.3% → 가격 10점', '{"unit_id": "M08", "f3_case": ["A-1-1"], "price_revision": null, "handover_condition_kr": "잔금시명도"}'::jsonb);
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-08-04 15:20:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 2,
    '26.4억이면 정리한다. 이사 갈 곳은 이미 계약해뒀다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '문O아'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M08'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M08'), '{"raw_line": "[26-08-04 15:20 주]②26.4억이면 정리한다. 이사 갈 곳은 이미 계약해뒀다", "origin": "케이스:A-1-1", "case_log": true, "log_type": "케이스", "speaker_key": "주②", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-07-11 11:05:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 2,
    '12월 20일 이후면 언제든 비워줄 수 있다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '문O아'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M08'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M08'), '{"raw_line": "[26-07-11 11:05 주]②12월 20일 이후면 언제든 비워줄 수 있다", "origin": "케이스:A-1-1", "case_log": true, "log_type": "케이스", "speaker_key": "주②", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2024-10-07 15:53:00+09', 'CALL',
    'OUTBOUND', 'UNREACHABLE', 'OWNER_SIDE', 1,
    '지금거신 전화는 없는번호', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '문O진'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M08'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M08'), '{"raw_line": "[24-10-07 15:53 주]①지금거신 전화는 없는번호", "origin": "합성CSV:U0003#5", "case_log": false, "log_type": "부재/불통", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2023-09-12 16:27:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'TENANT', 1,
    '매물 접수 - 33평 9층, 확장/올수리 상태 양호', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M08'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M08'), '{"raw_line": "[23-09-12 16:27 세]①매물 접수 - 33평 9층, 확장/올수리 상태 양호", "origin": "합성CSV:U0003#6", "case_log": false, "log_type": "매물접수", "speaker_key": "세①", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2019-09-11 14:22:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OTHER', NULL,
    '*77-수신차단.', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M08'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M08'), '{"raw_line": "[19-09-11 14:22 기]*77-수신차단.", "origin": "합성CSV:U0003#7", "case_log": false, "log_type": "부재/불통", "speaker_key": "기", "needs_relation": false, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2019-09-06 11:04:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 2,
    '베스트부동산에서 매매 13.4억으로 받음', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '문O아'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M08'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M08'), '{"raw_line": "[19-09-06 11:04 주]ⓑ베스트부동산에서 매매 13.4억으로 받음", "origin": "합성CSV:U0003#8", "case_log": false, "log_type": "매물접수", "speaker_key": "주ⓑ", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2018-09-06 10:32:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 2,
    '로밍중이라고 함. 추후 연락', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '문O아'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M08'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M08'), '{"raw_line": "[18-09-06 10:32 주]ⓑ로밍중이라고 함. 추후 연락", "origin": "합성CSV:U0003#9", "case_log": false, "log_type": "부재/불통", "speaker_key": "주ⓑ", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));

-- M09  601동 1402호 · 33평 J1 · 임차 · A-2-2
--   기대: 강함 91.0점 — 임차 만기 2026-11-30(기준일 D-105)을 코드가 인도 가능일로 산출. 시급도 급함. 의향은 「그때 생각해보겠다」라 불명(6점)
INSERT INTO property_unit (brokerage_id, complex_id, building_number, unit_number,
    floor_number, orientation, pyeong, exclusive_area_sqm, supply_area_sqm,
    unit_type, is_expanded, built_in_features, facility_condition,
    tenancy_status, current_deposit_amount, current_monthly_rent_amount, loan_amount,
    tenancy_expiry_date, tenancy_raw_text, assigned_user_id, memo,
    lifecycle_status, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_complex
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '한들마을 센트럴파크'),
    '601', '1402', '14', '남향', 33, 84.96, 112.74,
    'J1', FALSE, '붙박이장(안방), 가스쿡탑', '원상태 — 준공 당시 마감 유지',
    'LEASED', 1100000000, NULL, 180000000,
    '2026-11-30', '전세 11억 (24.12~26.11), 융자 1.8억', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), 'J1 · 비확장',
    'LISTED', '{"unit_id": "M09", "f3_case": ["A-2-2"], "handover_pref_date": null, "handover_blocked_reason": null, "src_synthetic_unit": "U0021", "unresolved_speakers": ["주②", "중②"]}'::jsonb);
INSERT INTO property_unit_party_relation (brokerage_id, unit_id, party_id, role,
    role_index, is_primary, is_co_owner, valid_from, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M09'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '구O태'),
    'OWNER_SIDE', 1, TRUE, FALSE, '2024-01-01', '상담로그 화자 주①');
INSERT INTO property_unit_party_relation (brokerage_id, unit_id, party_id, role,
    role_index, is_primary, is_co_owner, valid_from, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M09'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '봉O림'),
    'TENANT', 1, FALSE, FALSE, '2024-01-01', '상담로그 화자 세①');
INSERT INTO property_listing (brokerage_id, unit_id, client_party_id, received_at, status,
    is_sale_available, sale_price, is_jeonse_available, jeonse_deposit_amount,
    is_monthly_rent_available, monthly_rent_deposit_amount, monthly_rent_amount,
    price_raw_text, handover_condition, assigned_user_id, memo, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M09'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '구O태'), '2026-07-01', 'ADVERTISING',
    TRUE, 2220000000, FALSE, NULL,
    FALSE, NULL, NULL,
    '22.2억', 'AFTER_TENANCY_EXPIRY', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), '강함 91.0점 — 임차 만기 2026-11-30(기준일 D-105)을 코드가 인도 가능일로 산출. 시급도 급함. 의향은 「그때 생각해보겠다」라 불명(6점)', '{"unit_id": "M09", "f3_case": ["A-2-2"], "price_revision": null, "handover_condition_kr": "임차만기후명도"}'::jsonb);
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-08-06 18:21:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '시세가 22억 초반이면 굳이 붙들고 있을 이유는 없다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '구O태'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M09'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M09'), '{"raw_line": "[26-08-06 18:21 주]①시세가 22억 초반이면 굳이 붙들고 있을 이유는 없다", "origin": "케이스:A-2-2", "case_log": true, "log_type": "케이스", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-08-06 18:20:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '세입자 만기가 11월 말이라 만기 되면 그때 생각해보겠다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '구O태'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M09'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M09'), '{"raw_line": "[26-08-06 18:20 주]①세입자 만기가 11월 말이라 만기 되면 그때 생각해보겠다", "origin": "케이스:A-2-2", "case_log": true, "log_type": "케이스", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-06-19 10:40:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'TENANT', 1,
    '저희는 만기에 나갑니다. 이미 다른 데 알아보고 있어요', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '봉O림'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M09'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M09'), '{"raw_line": "[26-06-19 10:40 세]①저희는 만기에 나갑니다. 이미 다른 데 알아보고 있어요", "origin": "케이스:A-2-2", "case_log": true, "log_type": "케이스", "speaker_key": "세①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2024-02-18 18:43:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '전속은 안하고 조건 맞으면 진행한다고 하심', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '구O태'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M09'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M09'), '{"raw_line": "[24-02-18 18:43 주]①전속은 안하고 조건 맞으면 진행한다고 하심", "origin": "합성CSV:U0021#4", "case_log": false, "log_type": "조건협의", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2023-06-17 18:09:00+09', 'SMS',
    'OUTBOUND', 'UNREACHABLE', 'OWNER_SIDE', 1,
    '부재중. 매매,임대계획 문자발송(시세표,명함)', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '구O태'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M09'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M09'), '{"raw_line": "[23-06-17 18:09 주]①부재중. 매매,임대계획 문자발송(시세표,명함)", "origin": "합성CSV:U0021#5", "case_log": false, "log_type": "부재/불통", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2022-11-07 10:05:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 2,
    '여자분이 받았다가 그냥 끊음', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M09'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M09'), '{"raw_line": "[22-11-07 10:05 주]②여자분이 받았다가 그냥 끊음", "origin": "합성CSV:U0021#6", "case_log": false, "log_type": "부재/불통", "speaker_key": "주②", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2022-01-19 18:45:00+09', 'SMS',
    'OUTBOUND', 'CONNECTED', 'CO_BROKER', 2,
    '업무중이라 문자로 달라고 함', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M09'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M09'), '{"raw_line": "[22-01-19 18:45 중]②업무중이라 문자로 달라고 함", "origin": "합성CSV:U0021#7", "case_log": false, "log_type": "계획없음/거절", "speaker_key": "중②", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2022-01-17 09:35:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '로밍중이라고 함. 추후 연락', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '구O태'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M09'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M09'), '{"raw_line": "[22-01-17 09:35 주]①로밍중이라고 함. 추후 연락", "origin": "합성CSV:U0021#8", "case_log": false, "log_type": "부재/불통", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2021-08-30 10:10:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'TENANT', 1,
    '602호는 아들집이라고 하심', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '봉O림'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M09'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M09'), '{"raw_line": "[21-08-30 10:10 세]①602호는 아들집이라고 하심", "origin": "합성CSV:U0021#9", "case_log": false, "log_type": "정보갱신", "speaker_key": "세①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));

-- M10  301동 1404호 · 33평 J2 · 자가 · A-2-4
--   기대: 중간 80.8점 — 선행 매수가 미확정이라 인도 가능일이 산출되지 않는다(시점 8.8). 보류 게이트로 1단계 강등. 행동 제안은 매수 권유가 아니라 선행 매수 진행 확인이어야 한다
INSERT INTO property_unit (brokerage_id, complex_id, building_number, unit_number,
    floor_number, orientation, pyeong, exclusive_area_sqm, supply_area_sqm,
    unit_type, is_expanded, built_in_features, facility_condition,
    tenancy_status, current_deposit_amount, current_monthly_rent_amount, loan_amount,
    tenancy_expiry_date, tenancy_raw_text, assigned_user_id, memo,
    lifecycle_status, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_complex
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '한들마을 센트럴파크'),
    '301', '1404', '14', '남향', 33, 84.96, 112.74,
    'J2', TRUE, '붙박이장(안방), 가스쿡탑', '부분수리 — 24년 도배·싱크대',
    'SELF_OCCUPIED', NULL, NULL, NULL,
    NULL, NULL, (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), 'J2 · 확장',
    'LISTED', '{"unit_id": "M10", "f3_case": ["A-2-4"], "handover_pref_date": null, "handover_blocked_reason": "선행 매수 미확정", "src_synthetic_unit": "U0011", "unresolved_speakers": ["주②"]}'::jsonb);
INSERT INTO property_unit_party_relation (brokerage_id, unit_id, party_id, role,
    role_index, is_primary, is_co_owner, valid_from, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M10'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '백O연'),
    'OWNER_SIDE', 1, TRUE, FALSE, '2024-01-01', '상담로그 화자 주①');
INSERT INTO property_listing (brokerage_id, unit_id, client_party_id, received_at, status,
    is_sale_available, sale_price, is_jeonse_available, jeonse_deposit_amount,
    is_monthly_rent_available, monthly_rent_deposit_amount, monthly_rent_amount,
    price_raw_text, handover_condition, assigned_user_id, memo, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M10'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '백O연'), '2026-07-01', 'ADVERTISING',
    TRUE, 2340000000, FALSE, NULL,
    FALSE, NULL, NULL,
    '23.4억', 'PENDING_PRIOR_PURCHASE', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), '중간 80.8점 — 선행 매수가 미확정이라 인도 가능일이 산출되지 않는다(시점 8.8). 보류 게이트로 1단계 강등. 행동 제안은 매수 권유가 아니라 선행 매수 진행 확인이어야 한다', '{"unit_id": "M10", "f3_case": ["A-2-4"], "price_revision": null, "handover_condition_kr": "선행매수후협의"}'::jsonb);
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-08-10 20:06:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '23.4억이면 진행할 수 있다. 잔금 날짜는 맞춰주는 대로 한다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '백O연'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M10'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M10'), '{"raw_line": "[26-08-10 20:06 주]①23.4억이면 진행할 수 있다. 잔금 날짜는 맞춰주는 대로 한다", "origin": "케이스:A-2-4", "case_log": true, "log_type": "케이스", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-08-10 20:05:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '새로 갈 집이 계약돼야 내놓을 수 있다. 지금 알아보는 중이다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '백O연'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M10'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M10'), '{"raw_line": "[26-08-10 20:05 주]①새로 갈 집이 계약돼야 내놓을 수 있다. 지금 알아보는 중이다", "origin": "케이스:A-2-4", "case_log": true, "log_type": "케이스", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-06-22 13:12:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '갈아타기 목적이라 순서만 맞으면 바로 한다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '백O연'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M10'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M10'), '{"raw_line": "[26-06-22 13:12 주]①갈아타기 목적이라 순서만 맞으면 바로 한다", "origin": "케이스:A-2-4", "case_log": true, "log_type": "케이스", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2024-12-31 18:41:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 2,
    '월세 보증금 3억으로 임차료 얼마인지 문의함', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M10'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M10'), '{"raw_line": "[24-12-31 18:41 주]②월세 보증금 3억으로 임차료 얼마인지 문의함", "origin": "합성CSV:U0011#3", "case_log": false, "log_type": "시세문의/상담", "speaker_key": "주②", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2023-08-04 17:16:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 2,
    '매물 광고 여부 확인 요청. 아직 한군데만 준다고 하심', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M10'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M10'), '{"raw_line": "[23-08-04 17:16 주]②매물 광고 여부 확인 요청. 아직 한군데만 준다고 하심", "origin": "합성CSV:U0011#4", "case_log": false, "log_type": "시세문의/상담", "speaker_key": "주②", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2023-07-20 17:40:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OTHER', 1,
    '월세 내놓음. 보증 10억/320만원, 반려동물X 외국인X 조건', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M10'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M10'), '{"raw_line": "[23-07-20 17:40 기]①월세 내놓음. 보증 10억/320만원, 반려동물X 외국인X 조건", "origin": "합성CSV:U0011#5", "case_log": false, "log_type": "매물접수", "speaker_key": "기①", "needs_relation": false, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2023-01-05 11:20:00+09', 'CALL',
    'OUTBOUND', 'UNREACHABLE', 'OWNER_SIDE', 2,
    '전원꺼짐. 추후 재통화 예정', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M10'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M10'), '{"raw_line": "[23-01-05 11:20 주]②전원꺼짐. 추후 재통화 예정", "origin": "합성CSV:U0011#6", "case_log": false, "log_type": "부재/불통", "speaker_key": "주②", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2022-10-13 14:42:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '전세 재연장 완료. 조건 동일', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '백O연'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M10'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M10'), '{"raw_line": "[22-10-13 14:42 주]①전세 재연장 완료. 조건 동일", "origin": "합성CSV:U0011#7", "case_log": false, "log_type": "계약완료-전세", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2020-12-12 17:26:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '신규월완20.11.26  2.5/380 (20.12~22.12)', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '백O연'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M10'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M10'), '{"raw_line": "[20-12-12 17:26 주]ⓐ신규월완20.11.26  2.5/380 (20.12~22.12)", "origin": "합성CSV:U0011#8", "case_log": false, "log_type": "계약완료-월세", "speaker_key": "주ⓐ", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));

-- M11  115동 2301호 · 33평 J1 · 자가 · A-1-3
--   기대: 인하 전 후보 제외(27.5억 > 게이트 27.02억) → 인하 저장 후 [손님 찾기]에서 중간 67.0점으로 진입
INSERT INTO property_unit (brokerage_id, complex_id, building_number, unit_number,
    floor_number, orientation, pyeong, exclusive_area_sqm, supply_area_sqm,
    unit_type, is_expanded, built_in_features, facility_condition,
    tenancy_status, current_deposit_amount, current_monthly_rent_amount, loan_amount,
    tenancy_expiry_date, tenancy_raw_text, assigned_user_id, memo,
    lifecycle_status, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_complex
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '한들마을 센트럴파크'),
    '115', '2301', '23', '남향', 33, 84.96, 112.74,
    'J1', TRUE, '붙박이장(안방·작은방), 식기세척기, 김치냉장고, 인덕션', '올수리 — 25년 도배·장판·욕실 2개 전체',
    'SELF_OCCUPIED', NULL, NULL, NULL,
    NULL, NULL, (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), 'J1 · 확장',
    'LISTED', '{"unit_id": "M11", "f3_case": ["A-1-3"], "handover_pref_date": "2026-12-31", "handover_blocked_reason": null, "src_synthetic_unit": "U0033", "unresolved_speakers": ["세①", "세ⓑ", "중①"]}'::jsonb);
INSERT INTO property_unit_party_relation (brokerage_id, unit_id, party_id, role,
    role_index, is_primary, is_co_owner, valid_from, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M11'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '차O민'),
    'OWNER_SIDE', 1, TRUE, FALSE, '2024-01-01', '상담로그 화자 주①');
INSERT INTO property_listing (brokerage_id, unit_id, client_party_id, received_at, status,
    is_sale_available, sale_price, is_jeonse_available, jeonse_deposit_amount,
    is_monthly_rent_available, monthly_rent_deposit_amount, monthly_rent_amount,
    price_raw_text, handover_condition, assigned_user_id, memo, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M11'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '차O민'), '2026-07-01', 'ADVERTISING',
    TRUE, 2750000000, FALSE, NULL,
    FALSE, NULL, NULL,
    '27.5억', 'ON_SETTLEMENT', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), '인하 전 후보 제외(27.5억 > 게이트 27.02억) → 인하 저장 후 [손님 찾기]에서 중간 67.0점으로 진입', '{"unit_id": "M11", "f3_case": ["A-1-3"], "price_revision": {"to": 26.5, "at": "2026-08-17"}, "handover_condition_kr": "잔금시명도"}'::jsonb);
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-08-17 09:40:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '26.5억으로 낮춰서 다시 내놓겠다. 오래 걸리는 게 더 손해다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '차O민'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M11'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M11'), '{"raw_line": "[26-08-17 09:40 주]①26.5억으로 낮춰서 다시 내놓겠다. 오래 걸리는 게 더 손해다", "origin": "케이스:A-1-3(인하 저장)", "case_log": true, "log_type": "케이스", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-07-30 16:22:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '27.5억에 내놨는데 문의가 없다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '차O민'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M11'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M11'), '{"raw_line": "[26-07-30 16:22 주]①27.5억에 내놨는데 문의가 없다", "origin": "케이스:A-1-3", "case_log": true, "log_type": "케이스", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-07-02 11:15:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '연말 잔금이면 맞춰줄 수 있다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '차O민'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M11'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M11'), '{"raw_line": "[26-07-02 11:15 주]①연말 잔금이면 맞춰줄 수 있다", "origin": "케이스:A-1-3", "case_log": true, "log_type": "케이스", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2024-06-07 11:19:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'CO_BROKER', 1,
    '지금은 계획없다고 하심', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M11'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M11'), '{"raw_line": "[24-06-07 11:19 중]①지금은 계획없다고 하심", "origin": "합성CSV:U0033#2", "case_log": false, "log_type": "계획없음/거절", "speaker_key": "중①", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2023-03-04 15:08:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '본인집은 특A라고 하심. 얼마 받을수 있겠느냐 문의', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '차O민'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M11'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M11'), '{"raw_line": "[23-03-04 15:08 주]①본인집은 특A라고 하심. 얼마 받을수 있겠느냐 문의", "origin": "합성CSV:U0033#3", "case_log": false, "log_type": "시세문의/상담", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2022-03-11 12:20:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '동일 소유자 물건 3건 - 115동 2602호 / 407동 804호 확인', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '차O민'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M11'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M11'), '{"raw_line": "[22-03-11 12:20 주]①동일 소유자 물건 3건 - 115동 2602호 / 407동 804호 확인", "origin": "합성CSV:U0033#4", "case_log": false, "log_type": "정보갱신", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2021-09-10 09:24:00+09', 'SMS',
    'OUTBOUND', 'UNREACHABLE', 'TENANT', 1,
    '전화를 받을수 없다고 문자옴[문자.명함발송]', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M11'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M11'), '{"raw_line": "[21-09-10 09:24 세]①전화를 받을수 없다고 문자옴[문자.명함발송]", "origin": "합성CSV:U0033#5", "case_log": false, "log_type": "부재/불통", "speaker_key": "세①", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2021-08-09 17:26:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'TENANT', 2,
    '전세 13.5억 / 월세 보증 1.5억에 380만원 시세 문의하심', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M11'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M11'), '{"raw_line": "[21-08-09 17:26 세]ⓑ전세 13.5억 / 월세 보증 1.5억에 380만원 시세 문의하심", "origin": "합성CSV:U0033#6", "case_log": false, "log_type": "시세문의/상담", "speaker_key": "세ⓑ", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2021-05-25 11:04:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '시세표,명함 발송 후 통화. 시세만 확인하고 마무리', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '차O민'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M11'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M11'), '{"raw_line": "[21-05-25 11:04 주]①시세표,명함 발송 후 통화. 시세만 확인하고 마무리", "origin": "합성CSV:U0033#7", "case_log": false, "log_type": "시세문의/상담", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));

-- M12  503동 2203호 · 33평 J1 · 자가 · A-4-1
--   기대: 강함 97.0점 — 주①은 3회 연속 불통이지만 주②는 통화 성공. 접촉 축 8점(양호)이고 행동 경로는 주②. 세대 단위로 뭉치면 「주의」가 되어 틀린다
INSERT INTO property_unit (brokerage_id, complex_id, building_number, unit_number,
    floor_number, orientation, pyeong, exclusive_area_sqm, supply_area_sqm,
    unit_type, is_expanded, built_in_features, facility_condition,
    tenancy_status, current_deposit_amount, current_monthly_rent_amount, loan_amount,
    tenancy_expiry_date, tenancy_raw_text, assigned_user_id, memo,
    lifecycle_status, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_complex
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '한들마을 센트럴파크'),
    '503', '2203', '22', '남향', 33, 84.96, 112.74,
    'J1', FALSE, '붙박이장(안방), 가스쿡탑', '부분수리 — 24년 도배·싱크대',
    'SELF_OCCUPIED', NULL, NULL, NULL,
    NULL, NULL, (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), 'J1 · 비확장',
    'LISTED', '{"unit_id": "M12", "f3_case": ["A-4-1"], "handover_pref_date": "2026-12-20", "handover_blocked_reason": null, "src_synthetic_unit": "U0032", "unresolved_speakers": ["중①"]}'::jsonb);
INSERT INTO property_unit_party_relation (brokerage_id, unit_id, party_id, role,
    role_index, is_primary, is_co_owner, valid_from, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M12'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '신O범'),
    'OWNER_SIDE', 1, TRUE, FALSE, '2024-01-01', '상담로그 화자 주①');
INSERT INTO property_unit_party_relation (brokerage_id, unit_id, party_id, role,
    role_index, is_primary, is_co_owner, valid_from, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M12'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '고O정'),
    'OWNER_SIDE', 2, FALSE, FALSE, '2024-01-01', '상담로그 화자 주②');
INSERT INTO property_listing (brokerage_id, unit_id, client_party_id, received_at, status,
    is_sale_available, sale_price, is_jeonse_available, jeonse_deposit_amount,
    is_monthly_rent_available, monthly_rent_deposit_amount, monthly_rent_amount,
    price_raw_text, handover_condition, assigned_user_id, memo, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M12'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '신O범'), '2026-07-01', 'ADVERTISING',
    TRUE, 2280000000, FALSE, NULL,
    FALSE, NULL, NULL,
    '22.8억', 'ON_SETTLEMENT', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), '강함 97.0점 — 주①은 3회 연속 불통이지만 주②는 통화 성공. 접촉 축 8점(양호)이고 행동 경로는 주②. 세대 단위로 뭉치면 「주의」가 되어 틀린다', '{"unit_id": "M12", "f3_case": ["A-4-1"], "price_revision": null, "handover_condition_kr": "잔금시명도"}'::jsonb);
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-08-12 17:40:00+09', 'CALL',
    'OUTBOUND', 'UNREACHABLE', 'OWNER_SIDE', 1,
    '전원꺼짐. 추후 재통화 예정', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '신O범'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M12'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M12'), '{"raw_line": "[26-08-12 17:40 주]①전원꺼짐. 추후 재통화 예정", "origin": "케이스:A-4-1", "case_log": true, "log_type": "케이스", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-07-29 16:07:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 2,
    '12월 20일 이후 입주 가능하다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '고O정'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M12'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M12'), '{"raw_line": "[26-07-29 16:07 주]②12월 20일 이후 입주 가능하다", "origin": "케이스:A-4-1", "case_log": true, "log_type": "케이스", "speaker_key": "주②", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-07-29 16:05:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 2,
    '22.8억에 내놓는다. 남편은 전화를 잘 안 받으니 저한테 하세요', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '고O정'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M12'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M12'), '{"raw_line": "[26-07-29 16:05 주]②22.8억에 내놓는다. 남편은 전화를 잘 안 받으니 저한테 하세요", "origin": "케이스:A-4-1", "case_log": true, "log_type": "케이스", "speaker_key": "주②", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-07-15 14:33:00+09', 'SMS',
    'OUTBOUND', 'UNREACHABLE', 'OWNER_SIDE', 1,
    '부재[문자.명함발송]', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '신O범'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M12'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M12'), '{"raw_line": "[26-07-15 14:33 주]①부재[문자.명함발송]", "origin": "케이스:A-4-1", "case_log": true, "log_type": "케이스", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-06-28 11:20:00+09', 'SMS',
    'OUTBOUND', 'UNREACHABLE', 'OWNER_SIDE', 1,
    '전화를 받을수 없다고 문자옴[문자.명함발송]', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '신O범'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M12'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M12'), '{"raw_line": "[26-06-28 11:20 주]①전화를 받을수 없다고 문자옴[문자.명함발송]", "origin": "케이스:A-4-1", "case_log": true, "log_type": "케이스", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2024-03-29 14:32:00+09', 'CALL',
    'OUTBOUND', 'UNREACHABLE', 'OWNER_SIDE', 2,
    '결번', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '고O정'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M12'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M12'), '{"raw_line": "[24-03-29 14:32 주]②결번", "origin": "합성CSV:U0032#2", "case_log": false, "log_type": "부재/불통", "speaker_key": "주②", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2023-09-09 14:48:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 2,
    '월세 보증금 2.5억으로 임차료 얼마인지 문의함', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '고O정'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M12'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M12'), '{"raw_line": "[23-09-09 14:48 주]②월세 보증금 2.5억으로 임차료 얼마인지 문의함", "origin": "합성CSV:U0032#3", "case_log": false, "log_type": "시세문의/상담", "speaker_key": "주②", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2023-07-12 12:19:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '월완 보증 4억 / 월 500만원 (23.07~25.07)', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '신O범'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M12'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M12'), '{"raw_line": "[23-07-12 12:19 주]①월완 보증 4억 / 월 500만원 (23.07~25.07)", "origin": "합성CSV:U0032#4", "case_log": false, "log_type": "계약완료-월세", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2022-11-16 10:46:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '매매 임대 안함. 매매 분위기만 문의', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '신O범'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M12'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M12'), '{"raw_line": "[22-11-16 10:46 주]①매매 임대 안함. 매매 분위기만 문의", "origin": "합성CSV:U0032#5", "case_log": false, "log_type": "계획없음/거절", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2021-10-29 15:27:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'CO_BROKER', 1,
    '가온부동산 전완 16.1억 21.10.03', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M12'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M12'), '{"raw_line": "[21-10-29 15:27 중]①가온부동산 전완 16.1억 21.10.03", "origin": "합성CSV:U0032#6", "case_log": false, "log_type": "계약완료-전세", "speaker_key": "중①", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2021-04-10 12:30:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 2,
    '실거주 중이라 매매 임대 안함', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '고O정'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M12'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M12'), '{"raw_line": "[21-04-10 12:30 주]②실거주 중이라 매매 임대 안함", "origin": "합성CSV:U0032#7", "case_log": false, "log_type": "계획없음/거절", "speaker_key": "주②", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));

-- M13  105동 2103호 · 33평 J2 · 자가 · A-4-2
--   기대: 중간 91.0점 — 가격·시점 축은 만점인데 2026-02 이후 4회 연속 무응답이라 접촉 축 2점 + 보류 게이트(접촉 불가). 장부의 party_contact 는 여전히 「양호」다
INSERT INTO property_unit (brokerage_id, complex_id, building_number, unit_number,
    floor_number, orientation, pyeong, exclusive_area_sqm, supply_area_sqm,
    unit_type, is_expanded, built_in_features, facility_condition,
    tenancy_status, current_deposit_amount, current_monthly_rent_amount, loan_amount,
    tenancy_expiry_date, tenancy_raw_text, assigned_user_id, memo,
    lifecycle_status, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_complex
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '한들마을 센트럴파크'),
    '105', '2103', '21', '동향', 33, 84.96, 112.74,
    'J2', FALSE, '붙박이장(안방), 가스쿡탑', '원상태 — 준공 당시 마감 유지',
    'SELF_OCCUPIED', NULL, NULL, NULL,
    NULL, NULL, (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), 'J2 · 비확장',
    'LISTED', '{"unit_id": "M13", "f3_case": ["A-4-2"], "handover_pref_date": "2026-12-10", "handover_blocked_reason": null, "src_synthetic_unit": "U0035", "unresolved_speakers": ["세②", "중①"]}'::jsonb);
INSERT INTO property_unit_party_relation (brokerage_id, unit_id, party_id, role,
    role_index, is_primary, is_co_owner, valid_from, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M13'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '엄O현'),
    'OWNER_SIDE', 1, TRUE, FALSE, '2024-01-01', '상담로그 화자 주①');
INSERT INTO property_listing (brokerage_id, unit_id, client_party_id, received_at, status,
    is_sale_available, sale_price, is_jeonse_available, jeonse_deposit_amount,
    is_monthly_rent_available, monthly_rent_deposit_amount, monthly_rent_amount,
    price_raw_text, handover_condition, assigned_user_id, memo, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M13'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '엄O현'), '2026-07-01', 'ADVERTISING',
    TRUE, 2260000000, FALSE, NULL,
    FALSE, NULL, NULL,
    '22.6억', 'ON_SETTLEMENT', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), '중간 91.0점 — 가격·시점 축은 만점인데 2026-02 이후 4회 연속 무응답이라 접촉 축 2점 + 보류 게이트(접촉 불가). 장부의 party_contact 는 여전히 「양호」다', '{"unit_id": "M13", "f3_case": ["A-4-2"], "price_revision": null, "handover_condition_kr": "잔금시명도"}'::jsonb);
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-07-18 15:22:00+09', 'SMS',
    'OUTBOUND', 'UNREACHABLE', 'OWNER_SIDE', 1,
    '부재[문자.명함발송]', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '엄O현'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M13'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M13'), '{"raw_line": "[26-07-18 15:22 주]①부재[문자.명함발송]", "origin": "케이스:A-4-2", "case_log": true, "log_type": "케이스", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-06-30 11:04:00+09', 'SMS',
    'OUTBOUND', 'UNREACHABLE', 'OWNER_SIDE', 1,
    '전화를 받을수 없다고 문자옴[문자.명함발송]', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '엄O현'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M13'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M13'), '{"raw_line": "[26-06-30 11:04 주]①전화를 받을수 없다고 문자옴[문자.명함발송]", "origin": "케이스:A-4-2", "case_log": true, "log_type": "케이스", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-06-02 16:48:00+09', 'CALL',
    'OUTBOUND', 'UNREACHABLE', 'OWNER_SIDE', 1,
    '전원꺼짐. 추후 재통화 예정', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '엄O현'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M13'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M13'), '{"raw_line": "[26-06-02 16:48 주]①전원꺼짐. 추후 재통화 예정", "origin": "케이스:A-4-2", "case_log": true, "log_type": "케이스", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-04-15 10:12:00+09', 'CALL',
    'OUTBOUND', 'UNREACHABLE', 'OWNER_SIDE', 1,
    '지금거신 전화는 없는번호', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '엄O현'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M13'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M13'), '{"raw_line": "[26-04-15 10:12 주]①지금거신 전화는 없는번호", "origin": "케이스:A-4-2", "case_log": true, "log_type": "케이스", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-03-21 14:33:00+09', 'SMS',
    'OUTBOUND', 'UNREACHABLE', 'OTHER', 1,
    '부재중. 매매,임대계획 문자발송(시세표,명함)', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M13'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M13'), '{"raw_line": "[26-03-21 14:33 기]①부재중. 매매,임대계획 문자발송(시세표,명함)", "origin": "케이스:A-4-2", "case_log": true, "log_type": "케이스", "speaker_key": "기①", "needs_relation": false, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-02-10 09:50:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '22.6억에 내놓는다. 12월 10일 이후 입주 가능하다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '엄O현'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M13'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M13'), '{"raw_line": "[26-02-10 09:50 주]①22.6억에 내놓는다. 12월 10일 이후 입주 가능하다", "origin": "케이스:A-4-2", "case_log": true, "log_type": "케이스", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2022-12-02 15:12:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'CO_BROKER', 1,
    '오늘까지 18.5억까지는 해 주는데 다른 집이 매도 되면 포기한다.', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M13'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M13'), '{"raw_line": "[22-12-02 15:12 중]①오늘까지 18.5억까지는 해 주는데 다른 집이 매도 되면 포기한다.", "origin": "합성CSV:U0035#3", "case_log": false, "log_type": "조건협의", "speaker_key": "중①", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2021-12-02 15:51:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '본인집 아님/매매계획 없음', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '엄O현'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M13'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M13'), '{"raw_line": "[21-12-02 15:51 주]①본인집 아님/매매계획 없음", "origin": "합성CSV:U0035#5", "case_log": false, "log_type": "계획없음/거절", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2021-07-14 16:59:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'TENANT', 2,
    '월세 보증금 1.5억으로 임차료 얼마인지 문의함', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M13'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M13'), '{"raw_line": "[21-07-14 16:59 세]②월세 보증금 1.5억으로 임차료 얼마인지 문의함", "origin": "합성CSV:U0035#6", "case_log": false, "log_type": "시세문의/상담", "speaker_key": "세②", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2020-07-08 17:34:00+09', 'SMS',
    'OUTBOUND', 'UNREACHABLE', 'OWNER_SIDE', 1,
    '남/부재[문자.명함발송]', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '엄O현'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M13'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M13'), '{"raw_line": "[20-07-08 17:34 주]①남/부재[문자.명함발송]", "origin": "합성CSV:U0035#7", "case_log": false, "log_type": "부재/불통", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2020-07-01 17:22:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '층/향 좋은 물건 나오면 연락달라 하심', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '엄O현'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M13'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M13'), '{"raw_line": "[20-07-01 17:22 주]①층/향 좋은 물건 나오면 연락달라 하심", "origin": "합성CSV:U0035#8", "case_log": false, "log_type": "시세문의/상담", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2019-09-04 15:06:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '입주한다.', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '엄O현'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M13'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M13'), '{"raw_line": "[19-09-04 15:06 주]①입주한다.", "origin": "합성CSV:U0035#10", "case_log": false, "log_type": "계획없음/거절", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));

-- M14  305동 904호 · 33평 J1 · 자가 · A-3-3
--   기대: 관계 수정 전 중간(결정권 미확인 보류 강등) → 수정 후 카드 무효화·재생성 → 강함
INSERT INTO property_unit (brokerage_id, complex_id, building_number, unit_number,
    floor_number, orientation, pyeong, exclusive_area_sqm, supply_area_sqm,
    unit_type, is_expanded, built_in_features, facility_condition,
    tenancy_status, current_deposit_amount, current_monthly_rent_amount, loan_amount,
    tenancy_expiry_date, tenancy_raw_text, assigned_user_id, memo,
    lifecycle_status, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_complex
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '한들마을 센트럴파크'),
    '305', '904', '9', '남향', 33, 84.96, 112.74,
    'J1', TRUE, '붙박이장(안방·작은방), 식기세척기, 김치냉장고, 인덕션', '올수리 — 25년 도배·장판·욕실 2개 전체',
    'SELF_OCCUPIED', NULL, NULL, NULL,
    NULL, NULL, (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), 'J1 · 확장',
    'LISTED', '{"unit_id": "M14", "f3_case": ["A-3-3"], "handover_pref_date": "2026-12-10", "handover_blocked_reason": null, "src_synthetic_unit": "U0048", "unresolved_speakers": ["주③"]}'::jsonb);
INSERT INTO property_unit_party_relation (brokerage_id, unit_id, party_id, role,
    role_index, is_primary, is_co_owner, valid_from, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M14'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '류O경'),
    'TENANT', 1, TRUE, FALSE, '2024-01-01', '상담로그 화자 세①');
INSERT INTO property_listing (brokerage_id, unit_id, client_party_id, received_at, status,
    is_sale_available, sale_price, is_jeonse_available, jeonse_deposit_amount,
    is_monthly_rent_available, monthly_rent_deposit_amount, monthly_rent_amount,
    price_raw_text, handover_condition, assigned_user_id, memo, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M14'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '류O경'), '2026-07-01', 'ADVERTISING',
    TRUE, 2240000000, FALSE, NULL,
    FALSE, NULL, NULL,
    '22.4억', 'ON_SETTLEMENT', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), '관계 수정 전 중간(결정권 미확인 보류 강등) → 수정 후 카드 무효화·재생성 → 강함', '{"unit_id": "M14", "f3_case": ["A-3-3"], "price_revision": null, "handover_condition_kr": "잔금시명도"}'::jsonb);
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-08-05 14:32:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'TENANT', 1,
    '제가 직접 결정합니다. 연락은 이 번호로 주세요', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '류O경'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M14'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M14'), '{"raw_line": "[26-08-05 14:32 세]①제가 직접 결정합니다. 연락은 이 번호로 주세요", "origin": "케이스:A-3-3", "case_log": true, "log_type": "케이스", "speaker_key": "세①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-08-05 14:30:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'TENANT', 1,
    '22.4억에 내놓습니다. 12월 10일 이후 입주 가능해요', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '류O경'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M14'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M14'), '{"raw_line": "[26-08-05 14:30 세]①22.4억에 내놓습니다. 12월 10일 이후 입주 가능해요", "origin": "케이스:A-3-3", "case_log": true, "log_type": "케이스", "speaker_key": "세①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2022-12-16 12:30:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 3,
    '5338 안받음', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M14'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M14'), '{"raw_line": "[22-12-16 12:30 주]③5338 안받음", "origin": "합성CSV:U0048#5", "case_log": false, "log_type": "부재/불통", "speaker_key": "주③", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));

-- M15  115동 504호 · 25평 H1 · 자가 · G3
--   기대: 기각 G3 — 25평. C01 inflexible 「33평 아래는 안 봅니다」 위반
INSERT INTO property_unit (brokerage_id, complex_id, building_number, unit_number,
    floor_number, orientation, pyeong, exclusive_area_sqm, supply_area_sqm,
    unit_type, is_expanded, built_in_features, facility_condition,
    tenancy_status, current_deposit_amount, current_monthly_rent_amount, loan_amount,
    tenancy_expiry_date, tenancy_raw_text, assigned_user_id, memo,
    lifecycle_status, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_complex
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '한들마을 센트럴파크'),
    '115', '504', '5', '남향', 25, 59.94, 82.35,
    'H1', FALSE, '붙박이장(안방), 가스쿡탑', '부분수리 — 24년 도배·싱크대',
    'SELF_OCCUPIED', NULL, NULL, NULL,
    NULL, NULL, (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), 'H1 · 비확장',
    'LISTED', '{"unit_id": "M15", "f3_case": ["G3"], "handover_pref_date": "2026-11-15", "handover_blocked_reason": null, "src_synthetic_unit": "U0034", "unresolved_speakers": ["주③", "중②"]}'::jsonb);
INSERT INTO property_unit_party_relation (brokerage_id, unit_id, party_id, role,
    role_index, is_primary, is_co_owner, valid_from, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M15'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '표O건'),
    'OWNER_SIDE', 1, TRUE, FALSE, '2024-01-01', '상담로그 화자 주①');
INSERT INTO property_unit_party_relation (brokerage_id, unit_id, party_id, role,
    role_index, is_primary, is_co_owner, valid_from, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M15'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '표O아'),
    'OWNER_SIDE', 2, FALSE, FALSE, '2024-01-01', '상담로그 화자 주②');
INSERT INTO property_listing (brokerage_id, unit_id, client_party_id, received_at, status,
    is_sale_available, sale_price, is_jeonse_available, jeonse_deposit_amount,
    is_monthly_rent_available, monthly_rent_deposit_amount, monthly_rent_amount,
    price_raw_text, handover_condition, assigned_user_id, memo, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M15'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '표O건'), '2026-07-01', 'ADVERTISING',
    TRUE, 1720000000, FALSE, NULL,
    FALSE, NULL, NULL,
    '17.2억', 'ON_SETTLEMENT', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), '기각 G3 — 25평. C01 inflexible 「33평 아래는 안 봅니다」 위반', '{"unit_id": "M15", "f3_case": ["G3"], "price_revision": null, "handover_condition_kr": "잔금시명도"}'::jsonb);
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-08-03 11:44:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 2,
    '17.2억이면 바로 정리한다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '표O아'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M15'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M15'), '{"raw_line": "[26-08-03 11:44 주]②17.2억이면 바로 정리한다", "origin": "케이스:G3", "case_log": true, "log_type": "케이스", "speaker_key": "주②", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-07-20 15:02:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 2,
    '11월 중순이면 비워줄 수 있다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '표O아'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M15'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M15'), '{"raw_line": "[26-07-20 15:02 주]②11월 중순이면 비워줄 수 있다", "origin": "케이스:G3", "case_log": true, "log_type": "케이스", "speaker_key": "주②", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2024-10-31 13:45:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '여자분이 받았다가 그냥 끊음', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '표O건'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M15'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M15'), '{"raw_line": "[24-10-31 13:45 주]①여자분이 받았다가 그냥 끊음", "origin": "합성CSV:U0034#4", "case_log": false, "log_type": "부재/불통", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2023-10-02 18:12:00+09', 'SMS',
    'OUTBOUND', 'UNREACHABLE', 'OWNER_SIDE', 1,
    '5092/연결이되지않아멘트/문자.명함발송', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '표O건'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M15'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M15'), '{"raw_line": "[23-10-02 18:12 주]①5092/연결이되지않아멘트/문자.명함발송", "origin": "합성CSV:U0034#5", "case_log": false, "log_type": "부재/불통", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2022-12-29 14:59:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 3,
    '25평 매매 시세 문의함. 좋은 소식있으면 또 전화달라.', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M15'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M15'), '{"raw_line": "[22-12-29 14:59 주]③25평 매매 시세 문의함. 좋은 소식있으면 또 전화달라.", "origin": "합성CSV:U0034#6", "case_log": false, "log_type": "시세문의/상담", "speaker_key": "주③", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2021-06-17 09:12:00+09', 'CALL',
    'OUTBOUND', 'UNREACHABLE', 'OTHER', 2,
    '결번', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M15'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M15'), '{"raw_line": "[21-06-17 09:12 기]②결번", "origin": "합성CSV:U0034#8", "case_log": false, "log_type": "부재/불통", "speaker_key": "기②", "needs_relation": false, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2020-11-12 17:48:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'CO_BROKER', 2,
    '신규전완20.10.29  6.2(20.11~22.11)', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M15'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M15'), '{"raw_line": "[20-11-12 17:48 중]②신규전완20.10.29  6.2(20.11~22.11)", "origin": "합성CSV:U0034#9", "case_log": false, "log_type": "계약완료-전세", "speaker_key": "중②", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2018-10-12 17:14:00+09', 'SMS',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 2,
    '업무중이라 문자로 달라고 함', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '표O아'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M15'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M15'), '{"raw_line": "[18-10-12 17:14 주]②업무중이라 문자로 달라고 함", "origin": "합성CSV:U0034#10", "case_log": false, "log_type": "계획없음/거절", "speaker_key": "주②", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));

-- M16  201동 2003호 · 52평 L1 · 자가 · C04-대조
--   기대: C01 기준 제외(게이트 밖). C04(43평 31억) 기준으로는 후보이며 평형 조건 충족
INSERT INTO property_unit (brokerage_id, complex_id, building_number, unit_number,
    floor_number, orientation, pyeong, exclusive_area_sqm, supply_area_sqm,
    unit_type, is_expanded, built_in_features, facility_condition,
    tenancy_status, current_deposit_amount, current_monthly_rent_amount, loan_amount,
    tenancy_expiry_date, tenancy_raw_text, assigned_user_id, memo,
    lifecycle_status, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_complex
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '한들마을 센트럴파크'),
    '201', '2003', '20', '남향', 52, 139.91, 179.63,
    'L1', TRUE, '붙박이장(안방·작은방), 식기세척기, 김치냉장고, 인덕션', '올수리 — 25년 도배·장판·욕실 2개 전체',
    'SELF_OCCUPIED', NULL, NULL, NULL,
    NULL, NULL, (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), 'L1 · 확장',
    'LISTED', '{"unit_id": "M16", "f3_case": ["C04-대조"], "handover_pref_date": "2027-01-31", "handover_blocked_reason": null, "src_synthetic_unit": "U0013", "unresolved_speakers": []}'::jsonb);
INSERT INTO property_unit_party_relation (brokerage_id, unit_id, party_id, role,
    role_index, is_primary, is_co_owner, valid_from, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M16'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '방O건'),
    'OWNER_SIDE', 1, TRUE, FALSE, '2024-01-01', '상담로그 화자 주①');
INSERT INTO property_unit_party_relation (brokerage_id, unit_id, party_id, role,
    role_index, is_primary, is_co_owner, valid_from, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M16'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '방O수'),
    'OWNER_SIDE', 2, FALSE, FALSE, '2024-01-01', '상담로그 화자 주②');
INSERT INTO property_listing (brokerage_id, unit_id, client_party_id, received_at, status,
    is_sale_available, sale_price, is_jeonse_available, jeonse_deposit_amount,
    is_monthly_rent_available, monthly_rent_deposit_amount, monthly_rent_amount,
    price_raw_text, handover_condition, assigned_user_id, memo, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M16'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '방O건'), '2026-07-01', 'ADVERTISING',
    TRUE, 3350000000, FALSE, NULL,
    FALSE, NULL, NULL,
    '33.5억', 'NEGOTIABLE', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), 'C01 기준 제외(게이트 밖). C04(43평 31억) 기준으로는 후보이며 평형 조건 충족', '{"unit_id": "M16", "f3_case": ["C04-대조"], "price_revision": null, "handover_condition_kr": "협의"}'::jsonb);
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-07-08 10:15:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 2,
    '33.5억에 내놓는다. 급하지는 않다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '방O수'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M16'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M16'), '{"raw_line": "[26-07-08 10:15 주]②33.5억에 내놓는다. 급하지는 않다", "origin": "케이스:C04-대조", "case_log": true, "log_type": "케이스", "speaker_key": "주②", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-05-19 14:40:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 2,
    '1월 말이면 비워줄 수 있다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '방O수'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M16'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M16'), '{"raw_line": "[26-05-19 14:40 주]②1월 말이면 비워줄 수 있다", "origin": "케이스:C04-대조", "case_log": true, "log_type": "케이스", "speaker_key": "주②", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2024-07-15 13:10:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 2,
    '52평 매매 시세 문의함. 좋은 소식있으면 또 전화달라.', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '방O수'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M16'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M16'), '{"raw_line": "[24-07-15 13:10 주]②52평 매매 시세 문의함. 좋은 소식있으면 또 전화달라.", "origin": "합성CSV:U0013#1", "case_log": false, "log_type": "시세문의/상담", "speaker_key": "주②", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2024-05-02 09:55:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', NULL,
    '우리공인에서 매매 31.9억으로 받음', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M16'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M16'), '{"raw_line": "[24-05-02 09:55 주]우리공인에서 매매 31.9억으로 받음", "origin": "합성CSV:U0013#2", "case_log": false, "log_type": "매물접수", "speaker_key": "주", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2024-03-24 19:15:00+09', 'SMS',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', NULL,
    '업무중이라 문자로 달라고 함', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M16'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M16'), '{"raw_line": "[24-03-24 19:15 주]업무중이라 문자로 달라고 함", "origin": "합성CSV:U0013#3", "case_log": false, "log_type": "계획없음/거절", "speaker_key": "주", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2023-07-16 13:51:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 2,
    '매매 29.1억 / 월세 3억/180만원 동시 진행 원함', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '방O수'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M16'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M16'), '{"raw_line": "[23-07-16 13:51 주]②매매 29.1억 / 월세 3억/180만원 동시 진행 원함", "origin": "합성CSV:U0013#4", "case_log": false, "log_type": "매물접수", "speaker_key": "주②", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2022-07-19 14:16:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 2,
    '당분간 그냥 살기로 했다고 함', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '방O수'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M16'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M16'), '{"raw_line": "[22-07-19 14:16 주]②당분간 그냥 살기로 했다고 함", "origin": "합성CSV:U0013#5", "case_log": false, "log_type": "계획없음/거절", "speaker_key": "주②", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2020-07-16 16:44:00+09', 'SMS',
    'OUTBOUND', 'UNREACHABLE', 'OWNER_SIDE', 1,
    '전화를 받을수 없다고 문자옴[문자.명함발송]', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '방O건'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M16'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M16'), '{"raw_line": "[20-07-16 16:44 주]ⓐ전화를 받을수 없다고 문자옴[문자.명함발송]", "origin": "합성CSV:U0013#6", "case_log": false, "log_type": "부재/불통", "speaker_key": "주ⓐ", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));

-- M17  101동 1702호 · 43평 K1 · 자가 · C04-대조
--   기대: C04 기준 강함 — 이격 -2.6% · 여유 116일
INSERT INTO property_unit (brokerage_id, complex_id, building_number, unit_number,
    floor_number, orientation, pyeong, exclusive_area_sqm, supply_area_sqm,
    unit_type, is_expanded, built_in_features, facility_condition,
    tenancy_status, current_deposit_amount, current_monthly_rent_amount, loan_amount,
    tenancy_expiry_date, tenancy_raw_text, assigned_user_id, memo,
    lifecycle_status, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_complex
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '한들마을 센트럴파크'),
    '101', '1702', '17', '남향', 43, 114.87, 148.2,
    'K1', TRUE, '붙박이장(안방·작은방), 식기세척기, 김치냉장고, 인덕션', '올수리 — 25년 도배·장판·욕실 2개 전체',
    'SELF_OCCUPIED', NULL, NULL, NULL,
    NULL, NULL, (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), 'K1 · 확장',
    'LISTED', '{"unit_id": "M17", "f3_case": ["C04-대조"], "handover_pref_date": "2026-12-05", "handover_blocked_reason": null, "src_synthetic_unit": "U0026", "unresolved_speakers": ["중①"]}'::jsonb);
INSERT INTO property_unit_party_relation (brokerage_id, unit_id, party_id, role,
    role_index, is_primary, is_co_owner, valid_from, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M17'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '지O훈'),
    'OWNER_SIDE', 1, TRUE, FALSE, '2024-01-01', '상담로그 화자 주①');
INSERT INTO property_listing (brokerage_id, unit_id, client_party_id, received_at, status,
    is_sale_available, sale_price, is_jeonse_available, jeonse_deposit_amount,
    is_monthly_rent_available, monthly_rent_deposit_amount, monthly_rent_amount,
    price_raw_text, handover_condition, assigned_user_id, memo, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M17'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '지O훈'), '2026-07-01', 'ADVERTISING',
    TRUE, 3020000000, FALSE, NULL,
    FALSE, NULL, NULL,
    '30.2억', 'ON_SETTLEMENT', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), 'C04 기준 강함 — 이격 -2.6% · 여유 116일', '{"unit_id": "M17", "f3_case": ["C04-대조"], "price_revision": null, "handover_condition_kr": "잔금시명도"}'::jsonb);
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-08-08 09:52:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '12월 초면 비워줄 수 있다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '지O훈'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M17'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M17'), '{"raw_line": "[26-08-08 09:52 주]①12월 초면 비워줄 수 있다", "origin": "케이스:C04-대조", "case_log": true, "log_type": "케이스", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-08-08 09:50:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '30.2억이면 정리한다. 이사 갈 곳은 계약했다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '지O훈'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M17'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M17'), '{"raw_line": "[26-08-08 09:50 주]①30.2억이면 정리한다. 이사 갈 곳은 계약했다", "origin": "케이스:C04-대조", "case_log": true, "log_type": "케이스", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2024-01-16 15:29:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '통화중', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '지O훈'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M17'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M17'), '{"raw_line": "[24-01-16 15:29 주]①통화중", "origin": "합성CSV:U0026#3", "case_log": false, "log_type": "부재/불통", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2022-11-04 10:28:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '갱신월완22.10.21 1.5/350 전 1.5/330', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '지O훈'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M17'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M17'), '{"raw_line": "[22-11-04 10:28 주]①갱신월완22.10.21 1.5/350 전 1.5/330", "origin": "합성CSV:U0026#4", "case_log": false, "log_type": "계약완료-월세", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2021-08-17 18:48:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'CO_BROKER', 1,
    '매매 임대 안함. 매매 분위기만 문의', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M17'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M17'), '{"raw_line": "[21-08-17 18:48 중]①매매 임대 안함. 매매 분위기만 문의", "origin": "합성CSV:U0026#5", "case_log": false, "log_type": "계획없음/거절", "speaker_key": "중①", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2021-06-28 16:55:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '다주택자. 임대사업자 등록해둠. 만기 9월 위치 문의', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '지O훈'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M17'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M17'), '{"raw_line": "[21-06-28 16:55 주]ⓐ다주택자. 임대사업자 등록해둠. 만기 9월 위치 문의", "origin": "합성CSV:U0026#6", "case_log": false, "log_type": "시세문의/상담", "speaker_key": "주ⓐ", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2021-01-31 16:41:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '연결이 되지않아 소리샘으로', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '지O훈'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M17'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M17'), '{"raw_line": "[21-01-31 16:41 주]①연결이 되지않아 소리샘으로", "origin": "합성CSV:U0026#7", "case_log": false, "log_type": "부재/불통", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2020-10-31 10:36:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '최소 20.1억은 해야 매도 한다.', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '지O훈'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M17'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M17'), '{"raw_line": "[20-10-31 10:36 주]①최소 20.1억은 해야 매도 한다.", "origin": "합성CSV:U0026#8", "case_log": false, "log_type": "조건협의", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));

-- M18  605동 902호 · 43평 K1 · 임차 · C04-대조
--   기대: C04 기준 기각 G4 — 인도 2027-08-31 > 마감 2027-03-31
INSERT INTO property_unit (brokerage_id, complex_id, building_number, unit_number,
    floor_number, orientation, pyeong, exclusive_area_sqm, supply_area_sqm,
    unit_type, is_expanded, built_in_features, facility_condition,
    tenancy_status, current_deposit_amount, current_monthly_rent_amount, loan_amount,
    tenancy_expiry_date, tenancy_raw_text, assigned_user_id, memo,
    lifecycle_status, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_complex
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '한들마을 센트럴파크'),
    '605', '902', '9', '북향', 43, 114.87, 148.2,
    'K1', FALSE, '붙박이장(안방), 가스쿡탑', '원상태 — 준공 당시 마감 유지',
    'LEASED', 1450000000, NULL, 320000000,
    '2027-08-31', '전세 14.5억 (25.09~27.08), 융자 3.2억', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), 'K1 · 비확장',
    'LISTED', '{"unit_id": "M18", "f3_case": ["C04-대조"], "handover_pref_date": null, "handover_blocked_reason": null, "src_synthetic_unit": "U0036", "unresolved_speakers": ["주②"]}'::jsonb);
INSERT INTO property_unit_party_relation (brokerage_id, unit_id, party_id, role,
    role_index, is_primary, is_co_owner, valid_from, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M18'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '편O주'),
    'OWNER_SIDE', 1, TRUE, FALSE, '2024-01-01', '상담로그 화자 주①');
INSERT INTO property_listing (brokerage_id, unit_id, client_party_id, received_at, status,
    is_sale_available, sale_price, is_jeonse_available, jeonse_deposit_amount,
    is_monthly_rent_available, monthly_rent_deposit_amount, monthly_rent_amount,
    price_raw_text, handover_condition, assigned_user_id, memo, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M18'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '편O주'), '2026-07-01', 'ADVERTISING',
    TRUE, 2940000000, FALSE, NULL,
    FALSE, NULL, NULL,
    '29.4억', 'AFTER_TENANCY_EXPIRY', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), 'C04 기준 기각 G4 — 인도 2027-08-31 > 마감 2027-03-31', '{"unit_id": "M18", "f3_case": ["C04-대조"], "price_revision": null, "handover_condition_kr": "임차만기후명도"}'::jsonb);
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-07-25 16:30:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '29.4억 생각한다. 세입자 만기는 27년 8월이다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '편O주'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M18'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M18'), '{"raw_line": "[26-07-25 16:30 주]①29.4억 생각한다. 세입자 만기는 27년 8월이다", "origin": "케이스:C04-대조", "case_log": true, "log_type": "케이스", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2024-10-06 18:13:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 2,
    '43평 매매 시세 문의함. 좋은 소식있으면 또 전화달라.', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M18'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M18'), '{"raw_line": "[24-10-06 18:13 주]②43평 매매 시세 문의함. 좋은 소식있으면 또 전화달라.", "origin": "합성CSV:U0036#3", "case_log": false, "log_type": "시세문의/상담", "speaker_key": "주②", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2024-08-04 19:27:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 2,
    '본인집 아님/매매계획 없음', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M18'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M18'), '{"raw_line": "[24-08-04 19:27 주]②본인집 아님/매매계획 없음", "origin": "합성CSV:U0036#4", "case_log": false, "log_type": "계획없음/거절", "speaker_key": "주②", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2024-06-06 17:56:00+09', 'SMS',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '문자답장옴:무계획입니다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '편O주'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M18'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M18'), '{"raw_line": "[24-06-06 17:56 주]①문자답장옴:무계획입니다", "origin": "합성CSV:U0036#5", "case_log": false, "log_type": "계획없음/거절", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2024-03-08 16:54:00+09', 'SMS',
    'OUTBOUND', 'UNREACHABLE', 'OTHER', 1,
    '전화를 받을수 없다고 문자옴[문자.명함발송]', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M18'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M18'), '{"raw_line": "[24-03-08 16:54 기]①전화를 받을수 없다고 문자옴[문자.명함발송]", "origin": "합성CSV:U0036#6", "case_log": false, "log_type": "부재/불통", "speaker_key": "기①", "needs_relation": false, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2024-01-11 19:00:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '입주한다.', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '편O주'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M18'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M18'), '{"raw_line": "[24-01-11 19:00 주]①입주한다.", "origin": "합성CSV:U0036#7", "case_log": false, "log_type": "계획없음/거절", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2024-01-10 17:58:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '*77 연결안됨', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '편O주'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M18'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M18'), '{"raw_line": "[24-01-10 17:58 주]①*77 연결안됨", "origin": "합성CSV:U0036#8", "case_log": false, "log_type": "부재/불통", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));

-- M19  302동 1102호 · 33평 J1 · 자가 · 기준선
--   기대: 강함 97.0점 — 보류 항목 없음. 다른 케이스의 대조 기준
INSERT INTO property_unit (brokerage_id, complex_id, building_number, unit_number,
    floor_number, orientation, pyeong, exclusive_area_sqm, supply_area_sqm,
    unit_type, is_expanded, built_in_features, facility_condition,
    tenancy_status, current_deposit_amount, current_monthly_rent_amount, loan_amount,
    tenancy_expiry_date, tenancy_raw_text, assigned_user_id, memo,
    lifecycle_status, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_complex
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '한들마을 센트럴파크'),
    '302', '1102', '11', '남향', 33, 84.96, 112.74,
    'J1', TRUE, '붙박이장(안방·작은방), 식기세척기, 김치냉장고, 인덕션', '올수리 — 25년 도배·장판·욕실 2개 전체',
    'SELF_OCCUPIED', NULL, NULL, NULL,
    NULL, NULL, (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), 'J1 · 확장',
    'LISTED', '{"unit_id": "M19", "f3_case": ["기준선"], "handover_pref_date": "2026-12-10", "handover_blocked_reason": null, "src_synthetic_unit": "U0047", "unresolved_speakers": ["세①", "주③", "주ⓑ", "중③"]}'::jsonb);
INSERT INTO property_unit_party_relation (brokerage_id, unit_id, party_id, role,
    role_index, is_primary, is_co_owner, valid_from, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M19'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '정O우'),
    'OWNER_SIDE', 1, TRUE, FALSE, '2024-01-01', '상담로그 화자 주①');
INSERT INTO property_listing (brokerage_id, unit_id, client_party_id, received_at, status,
    is_sale_available, sale_price, is_jeonse_available, jeonse_deposit_amount,
    is_monthly_rent_available, monthly_rent_deposit_amount, monthly_rent_amount,
    price_raw_text, handover_condition, assigned_user_id, memo, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M19'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '정O우'), '2026-07-01', 'ADVERTISING',
    TRUE, 2190000000, FALSE, NULL,
    FALSE, NULL, NULL,
    '21.9억', 'ON_SETTLEMENT', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), '강함 97.0점 — 보류 항목 없음. 다른 케이스의 대조 기준', '{"unit_id": "M19", "f3_case": ["기준선"], "price_revision": null, "handover_condition_kr": "잔금시명도"}'::jsonb);
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-08-13 10:07:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '12월 10일 이후면 언제든 비워줄 수 있다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '정O우'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M19'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M19'), '{"raw_line": "[26-08-13 10:07 주]①12월 10일 이후면 언제든 비워줄 수 있다", "origin": "케이스:기준선", "case_log": true, "log_type": "케이스", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-08-13 10:05:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '21.9억이면 바로 정리한다. 이사 갈 곳은 이미 계약해뒀다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '정O우'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M19'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M19'), '{"raw_line": "[26-08-13 10:05 주]①21.9억이면 바로 정리한다. 이사 갈 곳은 이미 계약해뒀다", "origin": "케이스:기준선", "case_log": true, "log_type": "케이스", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-07-02 18:40:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '올해 안엔 넘기고 싶다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '정O우'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M19'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M19'), '{"raw_line": "[26-07-02 18:40 주]①올해 안엔 넘기고 싶다", "origin": "케이스:기준선", "case_log": true, "log_type": "케이스", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2024-05-14 11:33:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'CO_BROKER', 3,
    '매매는 26.0억에 진행한다. 일시적으로 금액 내려갈것 같다고 하심', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M19'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M19'), '{"raw_line": "[24-05-14 11:33 중]③매매는 26.0억에 진행한다. 일시적으로 금액 내려갈것 같다고 하심", "origin": "합성CSV:U0047#2", "case_log": false, "log_type": "조건협의", "speaker_key": "중③", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2023-08-10 10:21:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'TENANT', 1,
    '세입자 변동 없다.', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M19'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M19'), '{"raw_line": "[23-08-10 10:21 세]①세입자 변동 없다.", "origin": "합성CSV:U0047#3", "case_log": false, "log_type": "계획없음/거절", "speaker_key": "세①", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2023-04-03 10:57:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '그런 계획 없다고 함', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '정O우'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M19'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M19'), '{"raw_line": "[23-04-03 10:57 주]①그런 계획 없다고 함", "origin": "합성CSV:U0047#4", "case_log": false, "log_type": "계획없음/거절", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2022-08-01 16:27:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 3,
    '월세 내놓음. 보증 3억/250만원, 반려동물X 외국인X 조건', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M19'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M19'), '{"raw_line": "[22-08-01 16:27 주]③월세 내놓음. 보증 3억/250만원, 반려동물X 외국인X 조건", "origin": "합성CSV:U0047#5", "case_log": false, "log_type": "매물접수", "speaker_key": "주③", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2022-06-03 10:21:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '27.1억 제안 거절. 더 받아야 한다고 하심', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '정O우'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M19'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M19'), '{"raw_line": "[22-06-03 10:21 주]①27.1억 제안 거절. 더 받아야 한다고 하심", "origin": "합성CSV:U0047#6", "case_log": false, "log_type": "조건협의", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2019-02-20 11:01:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 2,
    '성원공인중개사에서 받음(월세). 광고는 하지말라 하심', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M19'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M19'), '{"raw_line": "[19-02-20 11:01 주]ⓑ성원공인중개사에서 받음(월세). 광고는 하지말라 하심", "origin": "합성CSV:U0047#8", "case_log": false, "log_type": "매물접수", "speaker_key": "주ⓑ", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));

-- M20  205동 1503호 · 33평 J1 · 자가 · A-2-1
--   기대: 기각 G2 — 같은 화자(주①)의 최신 진술이 철회. 과거 매도 진술을 덮는다
INSERT INTO property_unit (brokerage_id, complex_id, building_number, unit_number,
    floor_number, orientation, pyeong, exclusive_area_sqm, supply_area_sqm,
    unit_type, is_expanded, built_in_features, facility_condition,
    tenancy_status, current_deposit_amount, current_monthly_rent_amount, loan_amount,
    tenancy_expiry_date, tenancy_raw_text, assigned_user_id, memo,
    lifecycle_status, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_complex
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '한들마을 센트럴파크'),
    '205', '1503', '15', '남향', 33, 84.96, 112.74,
    'J1', FALSE, '붙박이장(안방), 가스쿡탑', '부분수리 — 24년 도배·싱크대',
    'SELF_OCCUPIED', NULL, NULL, NULL,
    NULL, NULL, (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), 'J1 · 비확장',
    'LISTED', '{"unit_id": "M20", "f3_case": ["A-2-1"], "handover_pref_date": "2026-12-20", "handover_blocked_reason": null, "src_synthetic_unit": "U0019", "unresolved_speakers": ["주②", "중①"]}'::jsonb);
INSERT INTO property_unit_party_relation (brokerage_id, unit_id, party_id, role,
    role_index, is_primary, is_co_owner, valid_from, memo)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M20'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '탁O림'),
    'OWNER_SIDE', 1, TRUE, FALSE, '2024-01-01', '상담로그 화자 주①');
INSERT INTO property_listing (brokerage_id, unit_id, client_party_id, received_at, status,
    is_sale_available, sale_price, is_jeonse_available, jeonse_deposit_amount,
    is_monthly_rent_available, monthly_rent_deposit_amount, monthly_rent_amount,
    price_raw_text, handover_condition, assigned_user_id, memo, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M20'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '탁O림'), '2026-07-01', 'ADVERTISING',
    TRUE, 2390000000, FALSE, NULL,
    FALSE, NULL, NULL,
    '23.9억', 'NEGOTIABLE', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), '기각 G2 — 같은 화자(주①)의 최신 진술이 철회. 과거 매도 진술을 덮는다', '{"unit_id": "M20", "f3_case": ["A-2-1"], "price_revision": null, "handover_condition_kr": "협의"}'::jsonb);
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-07-21 13:26:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '당분간 계획 없습니다. 그냥 살기로 했어요', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '탁O림'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M20'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M20'), '{"raw_line": "[26-07-21 13:26 주]①당분간 계획 없습니다. 그냥 살기로 했어요", "origin": "케이스:A-2-1", "case_log": true, "log_type": "케이스", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-03-04 11:12:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '23.9억에 내놨는데 조정은 2천 정도 가능', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '탁O림'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M20'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M20'), '{"raw_line": "[26-03-04 11:12 주]①23.9억에 내놨는데 조정은 2천 정도 가능", "origin": "케이스:A-2-1", "case_log": true, "log_type": "케이스", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2024-08-10 11:13:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 2,
    '세금때문에 지금은 계획없다', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M20'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M20'), '{"raw_line": "[24-08-10 11:13 주]②세금때문에 지금은 계획없다", "origin": "합성CSV:U0019#4", "case_log": false, "log_type": "계획없음/거절", "speaker_key": "주②", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2024-05-23 09:14:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'CO_BROKER', 1,
    '태평공인에서 매매 17.7억으로 받음', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M20'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M20'), '{"raw_line": "[24-05-23 09:14 중]①태평공인에서 매매 17.7억으로 받음", "origin": "합성CSV:U0019#5", "case_log": false, "log_type": "매물접수", "speaker_key": "중①", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2023-10-04 16:10:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 2,
    '본인집은 특A라고 하심. 얼마 받을수 있겠느냐 문의', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M20'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M20'), '{"raw_line": "[23-10-04 16:10 주]②본인집은 특A라고 하심. 얼마 받을수 있겠느냐 문의", "origin": "합성CSV:U0019#6", "case_log": false, "log_type": "시세문의/상담", "speaker_key": "주②", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2023-03-11 14:20:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 1,
    '요즘 매매 되냐고 물으심. 16.8억선 얘기드림', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '탁O림'), (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M20'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M20'), '{"raw_line": "[23-03-11 14:20 주]①요즘 매매 되냐고 물으심. 16.8억선 얘기드림", "origin": "합성CSV:U0019#7", "case_log": false, "log_type": "시세문의/상담", "speaker_key": "주①", "needs_relation": true, "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2023-03-02 12:14:00+09', 'CALL',
    'OUTBOUND', 'CONNECTED', 'OWNER_SIDE', 2,
    '전세 7.4억 / 월세 보증 2.5억에 450만원 시세 문의하심', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M20'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M20'), '{"raw_line": "[23-03-02 12:14 주]②전세 7.4억 / 월세 보증 2.5억에 450만원 시세 문의하심", "origin": "합성CSV:U0019#8", "case_log": false, "log_type": "시세문의/상담", "speaker_key": "주②", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, unit_id, listing_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2022-08-02 14:19:00+09', 'SMS',
    'OUTBOUND', 'UNREACHABLE', 'OWNER_SIDE', 2,
    '여/부재[문자.명함발송]', NULL, (SELECT id FROM property_unit
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M20'), (SELECT id FROM property_listing
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'unit_id' = 'M20'), '{"raw_line": "[22-08-02 14:19 주]②여/부재[문자.명함발송]", "origin": "합성CSV:U0019#9", "case_log": false, "log_type": "부재/불통", "speaker_key": "주②", "needs_relation": true, "speaker_resolved": false}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));

-- ══ 002/009 구입장 ═══════════════════════════════════════════════════
-- C01 김O수 · 33평 · 표기 22.0억 · A-1-1/A-2-4
INSERT INTO property_requirement (brokerage_id, party_id, received_at, demand_type,
    desired_pyeongs, min_area_sqm, min_budget_amount, max_budget_amount, budget_raw_text,
    desired_move_in_date, move_in_date_raw_text, request_expiry_date, status,
    co_broker_party_id, current_tenancy_expiry_date, classification, workflow_stage,
    assigned_user_id, memo, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '김O수'), '2026-07-01', 'BUY',
    ARRAY[33]::numeric(6,2)[], 84.96, NULL, 2200000000, '22.0억',
    '2027-03-02', '희망 입주 2027-03-02', NULL, 'ACTIVE',
    NULL, NULL, '실입주-갈아타기', '조건확정',
    (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), 'A군 기본 앵커. 표기 22.0억 / 로그 근거 상한 23.5억', '{"customer_id": "C01", "f3_case": ["A-1-1", "A-2-4"], "inflexible_hint": ["33평 아래는 안 봅니다", "3월 초 입주 아니면 의미가 없다"]}'::jsonb);
INSERT INTO property_requirement_complex (brokerage_id, requirement_id, complex_id,
    preference_order)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_requirement
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'customer_id' = 'C01'), (SELECT id FROM property_complex
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '한들마을 센트럴파크'), 1);
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, requirement_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-08-11 20:15:00+09', 'CALL',
    'INBOUND', 'CONNECTED', 'BUYER', 1,
    '좋은 거 나오면 바로 봅니다. 이번엔 진짜 정리하려고요', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '김O수'), (SELECT id FROM property_requirement
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'customer_id' = 'C01'), '{"raw_line": "[26-08-11 20:15 손]①좋은 거 나오면 바로 봅니다. 이번엔 진짜 정리하려고요", "origin": "케이스:A-1-1,A-2-4", "case_log": true, "speaker_key": "손①", "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, requirement_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-08-02 21:40:00+09', 'CALL',
    'INBOUND', 'CONNECTED', 'BUYER', 1,
    '아이 학교 때문에 3월 초 입주 아니면 의미가 없어요', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '김O수'), (SELECT id FROM property_requirement
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'customer_id' = 'C01'), '{"raw_line": "[26-08-02 21:40 손]①아이 학교 때문에 3월 초 입주 아니면 의미가 없어요", "origin": "케이스:A-1-1,A-2-4", "case_log": true, "speaker_key": "손①", "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, requirement_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-07-19 20:05:00+09', 'CALL',
    'INBOUND', 'CONNECTED', 'BUYER', 1,
    '23억 5천까지는 어떻게든 맞춰볼 수 있어요', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '김O수'), (SELECT id FROM property_requirement
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'customer_id' = 'C01'), '{"raw_line": "[26-07-19 20:05 손]①23억 5천까지는 어떻게든 맞춰볼 수 있어요", "origin": "케이스:A-1-1,A-2-4", "case_log": true, "speaker_key": "손①", "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, requirement_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-07-05 19:50:00+09', 'CALL',
    'INBOUND', 'CONNECTED', 'BUYER', 1,
    '저층도 정원 보이면 괜찮아요. 수리는 나중에 해도 되고', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '김O수'), (SELECT id FROM property_requirement
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'customer_id' = 'C01'), '{"raw_line": "[26-07-05 19:50 손]①저층도 정원 보이면 괜찮아요. 수리는 나중에 해도 되고", "origin": "케이스:A-1-1,A-2-4", "case_log": true, "speaker_key": "손①", "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, requirement_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-06-30 21:10:00+09', 'CALL',
    'INBOUND', 'CONNECTED', 'BUYER', 1,
    '우리 집이 계약돼야 진행 가능합니다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '김O수'), (SELECT id FROM property_requirement
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'customer_id' = 'C01'), '{"raw_line": "[26-06-30 21:10 손]①우리 집이 계약돼야 진행 가능합니다", "origin": "케이스:A-1-1,A-2-4", "case_log": true, "speaker_key": "손①", "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, requirement_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-06-12 20:30:00+09', 'CALL',
    'INBOUND', 'CONNECTED', 'BUYER', 1,
    '33평 아래는 안 봅니다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '김O수'), (SELECT id FROM property_requirement
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'customer_id' = 'C01'), '{"raw_line": "[26-06-12 20:30 손]①33평 아래는 안 봅니다", "origin": "케이스:A-1-1,A-2-4", "case_log": true, "speaker_key": "손①", "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));

-- C02 박O희 · 33평 · 표기 25.0억 · 앵커-대조
INSERT INTO property_requirement (brokerage_id, party_id, received_at, demand_type,
    desired_pyeongs, min_area_sqm, min_budget_amount, max_budget_amount, budget_raw_text,
    desired_move_in_date, move_in_date_raw_text, request_expiry_date, status,
    co_broker_party_id, current_tenancy_expiry_date, classification, workflow_stage,
    assigned_user_id, memo, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '박O희'), '2026-07-01', 'BUY',
    ARRAY[33]::numeric(6,2)[], 84.96, NULL, 2500000000, '25.0억',
    NULL, '시점 자유', NULL, 'ACTIVE',
    (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '으뜸공인중개사'), NULL, '투자', '상담중',
    (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), '투자 목적 — 시점 자유. 같은 매물이 앵커에 따라 다르게 판정되는지 확인', '{"customer_id": "C02", "f3_case": ["앵커-대조"], "inflexible_hint": ["33평 아래는 안 봅니다"]}'::jsonb);
INSERT INTO property_requirement_complex (brokerage_id, requirement_id, complex_id,
    preference_order)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_requirement
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'customer_id' = 'C02'), (SELECT id FROM property_complex
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '한들마을 센트럴파크'), 1);
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, requirement_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-08-08 15:20:00+09', 'CALL',
    'INBOUND', 'CONNECTED', 'BUYER', 2,
    '실입주 아니고 투자예요. 세 껴 있어도 상관없습니다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '박O희'), (SELECT id FROM property_requirement
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'customer_id' = 'C02'), '{"raw_line": "[26-08-08 15:20 손]②실입주 아니고 투자예요. 세 껴 있어도 상관없습니다", "origin": "케이스:앵커-대조", "case_log": true, "speaker_key": "손②", "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, requirement_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-08-08 15:22:00+09', 'CALL',
    'INBOUND', 'CONNECTED', 'BUYER', 2,
    '25억까지 보는데 물건 좋으면 조금 더도 가능', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '박O희'), (SELECT id FROM property_requirement
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'customer_id' = 'C02'), '{"raw_line": "[26-08-08 15:22 손]②25억까지 보는데 물건 좋으면 조금 더도 가능", "origin": "케이스:앵커-대조", "case_log": true, "speaker_key": "손②", "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, requirement_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-07-25 14:10:00+09', 'CALL',
    'INBOUND', 'CONNECTED', 'BUYER', 2,
    '층은 높을수록 좋고 조망 중요합니다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '박O희'), (SELECT id FROM property_requirement
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'customer_id' = 'C02'), '{"raw_line": "[26-07-25 14:10 손]②층은 높을수록 좋고 조망 중요합니다", "origin": "케이스:앵커-대조", "case_log": true, "speaker_key": "손②", "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, requirement_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-07-25 14:12:00+09', 'CALL',
    'INBOUND', 'CONNECTED', 'BUYER', 1,
    '자금은 준비돼 있어요', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '박O희'), (SELECT id FROM property_requirement
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'customer_id' = 'C02'), '{"raw_line": "[26-07-25 14:12 손]①자금은 준비돼 있어요", "origin": "케이스:앵커-대조", "case_log": true, "speaker_key": "손①", "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));

-- C03 이O민 · 33평 · 표기 23.0억 · D-2
INSERT INTO property_requirement (brokerage_id, party_id, received_at, demand_type,
    desired_pyeongs, min_area_sqm, min_budget_amount, max_budget_amount, budget_raw_text,
    desired_move_in_date, move_in_date_raw_text, request_expiry_date, status,
    co_broker_party_id, current_tenancy_expiry_date, classification, workflow_stage,
    assigned_user_id, memo, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '이O민'), '2026-07-01', 'BUY',
    ARRAY[33]::numeric(6,2)[], 84.96, NULL, 2300000000, '23.0억',
    NULL, '시점 자유', NULL, 'ACTIVE',
    NULL, NULL, '신규', '상담중',
    (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), '신규 등록 직후 — 진술 1건. 추정 상한을 만들 근거가 없다', '{"customer_id": "C03", "f3_case": ["D-2"], "inflexible_hint": ["33평"]}'::jsonb);
INSERT INTO property_requirement_complex (brokerage_id, requirement_id, complex_id,
    preference_order)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_requirement
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'customer_id' = 'C03'), (SELECT id FROM property_complex
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '한들마을 센트럴파크'), 1);
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, requirement_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-08-16 11:30:00+09', 'CALL',
    'INBOUND', 'CONNECTED', 'BUYER', 1,
    '33평 매물 있으면 연락 달라고 방문. 예산 23억', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '이O민'), (SELECT id FROM property_requirement
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'customer_id' = 'C03'), '{"raw_line": "[26-08-16 11:30 손]①33평 매물 있으면 연락 달라고 방문. 예산 23억", "origin": "케이스:D-2", "case_log": true, "speaker_key": "손①", "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));

-- C04 최O정 · 43평 · 표기 31.0억 · 앵커-평형
INSERT INTO property_requirement (brokerage_id, party_id, received_at, demand_type,
    desired_pyeongs, min_area_sqm, min_budget_amount, max_budget_amount, budget_raw_text,
    desired_move_in_date, move_in_date_raw_text, request_expiry_date, status,
    co_broker_party_id, current_tenancy_expiry_date, classification, workflow_stage,
    assigned_user_id, memo, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '최O정'), '2026-07-01', 'BUY',
    ARRAY[43]::numeric(6,2)[], 114.87, NULL, 3100000000, '31.0억',
    '2027-03-31', '희망 입주 2027-03-31', NULL, 'ACTIVE',
    (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '다올공인중개사'), '2027-03-31', '실입주-확장', '임장예정',
    (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), '43평 앵커 — 평형 조건축과 다른 가격대 게이트를 확인. 공동중개 건', '{"customer_id": "C04", "f3_case": ["앵커-평형"], "inflexible_hint": ["43평 이상", "3월 말까지 입주"]}'::jsonb);
INSERT INTO property_requirement_complex (brokerage_id, requirement_id, complex_id,
    preference_order)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_requirement
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'customer_id' = 'C04'), (SELECT id FROM property_complex
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '한들마을 센트럴파크'), 1);
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, requirement_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-08-09 19:12:00+09', 'CALL',
    'INBOUND', 'CONNECTED', 'BUYER', 1,
    '43평 이상으로 봅니다. 아이 둘이라 방 4개는 있어야 해요', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '최O정'), (SELECT id FROM property_requirement
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'customer_id' = 'C04'), '{"raw_line": "[26-08-09 19:12 손]①43평 이상으로 봅니다. 아이 둘이라 방 4개는 있어야 해요", "origin": "케이스:앵커-평형", "case_log": true, "speaker_key": "손①", "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, requirement_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-08-09 19:14:00+09', 'CALL',
    'INBOUND', 'CONNECTED', 'BUYER', 1,
    '31억까지 준비돼 있고 조금은 더 볼 수 있습니다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '최O정'), (SELECT id FROM property_requirement
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'customer_id' = 'C04'), '{"raw_line": "[26-08-09 19:14 손]①31억까지 준비돼 있고 조금은 더 볼 수 있습니다", "origin": "케이스:앵커-평형", "case_log": true, "speaker_key": "손①", "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, requirement_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-07-28 20:40:00+09', 'CALL',
    'INBOUND', 'CONNECTED', 'BUYER', 1,
    '3월 말까지는 들어가야 합니다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '최O정'), (SELECT id FROM property_requirement
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'customer_id' = 'C04'), '{"raw_line": "[26-07-28 20:40 손]①3월 말까지는 들어가야 합니다", "origin": "케이스:앵커-평형", "case_log": true, "speaker_key": "손①", "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));

-- C05 정O래 · 33평 · 표기 24.0억 · A-1-2
INSERT INTO property_requirement (brokerage_id, party_id, received_at, demand_type,
    desired_pyeongs, min_area_sqm, min_budget_amount, max_budget_amount, budget_raw_text,
    desired_move_in_date, move_in_date_raw_text, request_expiry_date, status,
    co_broker_party_id, current_tenancy_expiry_date, classification, workflow_stage,
    assigned_user_id, memo, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '정O래'), '2026-07-01', 'BUY',
    ARRAY[33]::numeric(6,2)[], 84.96, NULL, 2400000000, '24.0억',
    '2026-11-30', '희망 입주 2026-11-30', NULL, 'ACTIVE',
    NULL, '2026-11-30', '실입주-전세만기', '조건확정',
    (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), 'A-1-2 — 가격은 맞는데 시점이 안 맞는 앵커. 현 거주지 전세 만기가 마감을 만든다', '{"customer_id": "C05", "f3_case": ["A-1-2"], "inflexible_hint": ["33평 아래는 안 봅니다", "11월 말까지 입주"]}'::jsonb);
INSERT INTO property_requirement_complex (brokerage_id, requirement_id, complex_id,
    preference_order)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_requirement
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'customer_id' = 'C05'), (SELECT id FROM property_complex
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '한들마을 센트럴파크'), 1);
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, requirement_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-08-14 20:22:00+09', 'CALL',
    'INBOUND', 'CONNECTED', 'BUYER', 1,
    '전세 만기가 11월 말이라 그때까지는 들어가야 합니다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '정O래'), (SELECT id FROM property_requirement
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'customer_id' = 'C05'), '{"raw_line": "[26-08-14 20:22 손]①전세 만기가 11월 말이라 그때까지는 들어가야 합니다", "origin": "케이스:A-1-2", "case_log": true, "speaker_key": "손①", "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, requirement_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-08-14 20:24:00+09', 'CALL',
    'INBOUND', 'CONNECTED', 'BUYER', 1,
    '24억까지 가능하고 그 이상은 무리입니다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '정O래'), (SELECT id FROM property_requirement
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'customer_id' = 'C05'), '{"raw_line": "[26-08-14 20:24 손]①24억까지 가능하고 그 이상은 무리입니다", "origin": "케이스:A-1-2", "case_log": true, "speaker_key": "손①", "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, requirement_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-08-01 21:05:00+09', 'CALL',
    'INBOUND', 'CONNECTED', 'BUYER', 1,
    '33평 아래는 안 봅니다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '정O래'), (SELECT id FROM property_requirement
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'customer_id' = 'C05'), '{"raw_line": "[26-08-01 21:05 손]①33평 아래는 안 봅니다", "origin": "케이스:A-1-2", "case_log": true, "speaker_key": "손①", "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));

-- C06 한O빈 · 33평 · 표기 22.5억 · A-4-2-앵커
INSERT INTO property_requirement (brokerage_id, party_id, received_at, demand_type,
    desired_pyeongs, min_area_sqm, min_budget_amount, max_budget_amount, budget_raw_text,
    desired_move_in_date, move_in_date_raw_text, request_expiry_date, status,
    co_broker_party_id, current_tenancy_expiry_date, classification, workflow_stage,
    assigned_user_id, memo, custom_fields)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '한O빈'), '2026-07-01', 'BUY',
    ARRAY[33]::numeric(6,2)[], 84.96, NULL, 2250000000, '22.5억',
    '2027-01-31', '희망 입주 2027-01-31', NULL, 'ACTIVE',
    NULL, '2027-01-31', '실입주-전세만기', '보류',
    (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'), '앵커 쪽 접촉이 나쁜 경우 — 접촉 축은 나쁜 쪽을 따른다', '{"customer_id": "C06", "f3_case": ["A-4-2-앵커"], "inflexible_hint": ["33평 아래는 안 봅니다"]}'::jsonb);
INSERT INTO property_requirement_complex (brokerage_id, requirement_id, complex_id,
    preference_order)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), (SELECT id FROM property_requirement
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'customer_id' = 'C06'), (SELECT id FROM property_complex
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '한들마을 센트럴파크'), 1);
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, requirement_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-08-12 11:40:00+09', 'SMS',
    'INBOUND', 'UNREACHABLE', 'BUYER', 1,
    '전화를 받을수 없다고 문자옴[문자.명함발송]', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '한O빈'), (SELECT id FROM property_requirement
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'customer_id' = 'C06'), '{"raw_line": "[26-08-12 11:40 손]①전화를 받을수 없다고 문자옴[문자.명함발송]", "origin": "케이스:A-4-2-앵커", "case_log": true, "speaker_key": "손①", "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, requirement_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-07-30 17:15:00+09', 'SMS',
    'INBOUND', 'UNREACHABLE', 'BUYER', 1,
    '부재[문자.명함발송]', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '한O빈'), (SELECT id FROM property_requirement
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'customer_id' = 'C06'), '{"raw_line": "[26-07-30 17:15 손]①부재[문자.명함발송]", "origin": "케이스:A-4-2-앵커", "case_log": true, "speaker_key": "손①", "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, requirement_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-06-05 20:10:00+09', 'CALL',
    'INBOUND', 'CONNECTED', 'BUYER', 1,
    '22억 5천 정도 보고 있습니다. 1월 말까지 들어가면 됩니다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '한O빈'), (SELECT id FROM property_requirement
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'customer_id' = 'C06'), '{"raw_line": "[26-06-05 20:10 손]①22억 5천 정도 보고 있습니다. 1월 말까지 들어가면 됩니다", "origin": "케이스:A-4-2-앵커", "case_log": true, "speaker_key": "손①", "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));
INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_channel,
    communication_direction, interaction_result, counterparty_role, counterparty_index,
    interaction_content, party_id, requirement_id, related_context,
    source_type, created_by)
VALUES ((SELECT id FROM brokerage WHERE name = '한들공인중개사사무소'), '2026-05-22 19:48:00+09', 'CALL',
    'INBOUND', 'CONNECTED', 'BUYER', 1,
    '33평 아래는 안 봅니다', (SELECT id FROM party
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND name = '한O빈'), (SELECT id FROM property_requirement
         WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND custom_fields ->> 'customer_id' = 'C06'), '{"raw_line": "[26-05-22 19:48 손]①33평 아래는 안 봅니다", "origin": "케이스:A-4-2-앵커", "case_log": true, "speaker_key": "손①", "speaker_resolved": true}'::jsonb,
    'HUMAN', (SELECT id FROM app_user WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소') AND login_id = 'owner'));

