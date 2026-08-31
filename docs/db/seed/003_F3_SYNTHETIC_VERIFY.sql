-- PostgreSQL 15+
-- F3 합성 장부의 자기 점검. 읽기 전용이며 어떤 행도 바꾸지 않는다.
--
-- 002_F3_SYNTHETIC_SEED.sql 을 적용한 직후에 실행한다. Worker 를 켜기 전에 데이터가
-- 의도한 모양인지 먼저 확인하기 위한 파일이다.
--
-- 마지막 열이 전부 PASS 여야 한다. 하나라도 FAIL 이면 파이프라인을 돌리기 전에 seed 를
-- 다시 적용한다.
--
-- ## 여기서 검증하지 않는 것
--
-- 모델이 만든 문장, 등급 분포, 카드의 정확한 표현은 검증하지 않는다. 그것들은 실행
-- 결과이며 seed 의 책임이 아니다. 실행 후 확인 항목은 README.md 에 있다.

\set ON_ERROR_STOP on


-- 후보 추출은 앵커 카드의 추정가를 쓰고, 추정가가 없으면 장부 표기가를 쓴다. 아래
-- 재현 쿼리는 장부 표기가 기준이다. 모델이 상담 로그를 근거로 추정가를 내도 이 seed 의
-- 후보 집합은 바뀌지 않도록 각 후보의 예산을 경계에서 충분히 떨어뜨려 두었다.

WITH tenant AS (
    SELECT id AS brokerage_id FROM brokerage WHERE name = 'F3_SYNTHETIC 합성중개사무소'
),
ledger AS (
    SELECT
        t.brokerage_id,
        (SELECT id FROM property_complex   WHERE brokerage_id = t.brokerage_id AND extra_info->>'seed_key'   = 'C1') AS complex_c1,
        (SELECT id FROM property_complex   WHERE brokerage_id = t.brokerage_id AND extra_info->>'seed_key'   = 'C2') AS complex_c2,
        (SELECT id FROM property_complex   WHERE brokerage_id = t.brokerage_id AND extra_info->>'seed_key'   = 'C3') AS complex_c3,
        (SELECT id FROM property_complex   WHERE brokerage_id = t.brokerage_id AND extra_info->>'seed_key'   = 'C4') AS complex_c4,
        (SELECT id FROM property_complex   WHERE brokerage_id = t.brokerage_id AND extra_info->>'seed_key'   = 'C5') AS complex_c5,
        (SELECT id FROM property_listing   WHERE brokerage_id = t.brokerage_id AND custom_fields->>'seed_key' = 'L1') AS listing_l1,
        (SELECT id FROM property_listing   WHERE brokerage_id = t.brokerage_id AND custom_fields->>'seed_key' = 'L4') AS listing_l4,
        (SELECT id FROM property_listing   WHERE brokerage_id = t.brokerage_id AND custom_fields->>'seed_key' = 'L5') AS listing_l5,
        (SELECT id FROM property_listing   WHERE brokerage_id = t.brokerage_id AND custom_fields->>'seed_key' = 'BL01') AS listing_bl01,
        (SELECT id FROM property_listing   WHERE brokerage_id = t.brokerage_id AND custom_fields->>'seed_key' = 'BL13') AS listing_bl13,
        (SELECT id FROM property_listing   WHERE brokerage_id = t.brokerage_id AND custom_fields->>'seed_key' = 'BL23') AS listing_bl23,
        (SELECT id FROM property_requirement WHERE brokerage_id = t.brokerage_id AND custom_fields->>'seed_key' = 'R1') AS requirement_r1,
        (SELECT id FROM property_requirement WHERE brokerage_id = t.brokerage_id AND custom_fields->>'seed_key' = 'BR01') AS requirement_br01
    FROM tenant t
),
checks(sort_key, "검사", "기대", "실제") AS (

    -- ── 1. 행 수 ─────────────────────────────────────────────────────────────
    SELECT 101, '사무소 수', 1, (SELECT count(*) FROM brokerage WHERE name = 'F3_SYNTHETIC 합성중개사무소')
    UNION ALL SELECT 102, '개발 사용자 수', 1,
        (SELECT count(*) FROM app_user u JOIN tenant t ON t.brokerage_id = u.brokerage_id)
    UNION ALL SELECT 103, '활성 AI 모델 설정 수 (POSITION_CARD + BROKERAGE_JUDGMENT)', 2,
        (SELECT count(*) FROM ai_model_config c JOIN tenant t ON t.brokerage_id = c.brokerage_id
          WHERE c.is_active AND c.capability IN ('POSITION_CARD', 'BROKERAGE_JUDGMENT'))
    UNION ALL SELECT 104, '단지 수', 5,
        (SELECT count(*) FROM property_complex x JOIN tenant t ON t.brokerage_id = x.brokerage_id)
    UNION ALL SELECT 105, '세대 수', 36,
        (SELECT count(*) FROM property_unit x JOIN tenant t ON t.brokerage_id = x.brokerage_id)
    UNION ALL SELECT 106, '인물 수', 87,
        (SELECT count(*) FROM party x JOIN tenant t ON t.brokerage_id = x.brokerage_id)
    UNION ALL SELECT 107, '매물 수', 36,
        (SELECT count(*) FROM property_listing x JOIN tenant t ON t.brokerage_id = x.brokerage_id)
    UNION ALL SELECT 108, '구입장 수', 48,
        (SELECT count(*) FROM property_requirement x JOIN tenant t ON t.brokerage_id = x.brokerage_id)
    UNION ALL SELECT 109, '상담 로그 수', 169,
        (SELECT count(*) FROM client_interaction x JOIN tenant t ON t.brokerage_id = x.brokerage_id)

    -- ── 2. 실행 결과는 seed 하지 않는다 ──────────────────────────────────────
    --
    -- 아래가 0 이 아니면 이전 실행 결과가 남아 있는 것이다. Worker 가 처음부터 만드는지
    -- 확인할 수 없으므로 reset 후 다시 seed 한다.

    UNION ALL SELECT 201, 'agent_run 수 (Worker 가 만든다)', 0,
        (SELECT count(*) FROM agent_run x JOIN tenant t ON t.brokerage_id = x.brokerage_id)
    UNION ALL SELECT 202, '포지션 카드 수 (Worker 가 만든다)', 0,
        (SELECT count(*) FROM negotiation_position_analysis x JOIN tenant t ON t.brokerage_id = x.brokerage_id)
    UNION ALL SELECT 203, '판정 결과 수 (Worker 가 만든다)', 0,
        (SELECT count(*) FROM match_evaluation x JOIN tenant t ON t.brokerage_id = x.brokerage_id)

    -- ── 3. 케이스별 기대 후보 수 ─────────────────────────────────────────────
    --
    -- 결정적 SQL 추출을 그대로 재현한다. 이 수가 다르면 실행해도 기대한 결과가 나오지
    -- 않는다.

    -- 케이스 A: 매매 앵커 L1 → 매수·활성·예산 하한(28.8억의 90%)·희망 단지 조건
    UNION ALL SELECT 301, '케이스 A (매물 L1 앵커) 후보 구입장 수', 3, (
        SELECT count(*)
        FROM property_requirement r
        JOIN party p ON p.brokerage_id = r.brokerage_id AND p.id = r.party_id
        JOIN ledger g ON g.brokerage_id = r.brokerage_id
        WHERE r.is_deleted = FALSE
          AND p.is_deleted = FALSE
          AND r.demand_type = '매수'
          AND r.status = 'ACTIVE'
          AND (
              r.max_budget_amount IS NULL
              OR r.max_budget_amount >= trunc(
                  (SELECT sale_price FROM property_listing WHERE id = g.listing_l1) * 0.9
              )
          )
          AND (
              NOT EXISTS (
                  SELECT 1 FROM property_requirement_complex rc
                  WHERE rc.brokerage_id = r.brokerage_id AND rc.requirement_id = r.id
              )
              OR EXISTS (
                  SELECT 1 FROM property_requirement_complex rc
                  WHERE rc.brokerage_id = r.brokerage_id
                    AND rc.requirement_id = r.id
                    AND rc.complex_id = g.complex_c1
              )
          )
    )

    -- 케이스 B: 매수 구입장 R1 앵커 → 매매 가능·활성·예산 상한(29억의 110%)·희망 단지
    UNION ALL SELECT 302, '케이스 B (구입장 R1 앵커) 후보 매물 수', 2, (
        SELECT count(*)
        FROM property_listing l
        JOIN property_unit u ON u.brokerage_id = l.brokerage_id AND u.id = l.unit_id
        JOIN ledger g ON g.brokerage_id = l.brokerage_id
        WHERE l.is_deleted = FALSE
          AND u.is_deleted = FALSE
          AND l.is_sale_available = TRUE
          AND l.status = 'RECEIVED'
          AND (
              l.sale_price IS NULL
              OR l.sale_price <= trunc(
                  (SELECT max_budget_amount FROM property_requirement WHERE id = g.requirement_r1) * 1.1
              )
          )
          AND u.complex_id IN (
              SELECT rc.complex_id FROM property_requirement_complex rc
              WHERE rc.brokerage_id = l.brokerage_id AND rc.requirement_id = g.requirement_r1
          )
    )

    -- 케이스 C: 월세 앵커 L5 → 월세 구입장은 있지만 해당 단지 C2를 희망하지 않는다
    UNION ALL SELECT 303, '케이스 C (월세 매물 앵커) 후보 구입장 수', 0, (
        SELECT count(*)
        FROM property_requirement r
        JOIN party p ON p.brokerage_id = r.brokerage_id AND p.id = r.party_id
        JOIN ledger g ON g.brokerage_id = r.brokerage_id
        WHERE r.is_deleted = FALSE
          AND p.is_deleted = FALSE
          AND r.status = 'ACTIVE'
          AND r.demand_type = '월세'
          AND (
              r.max_budget_amount IS NULL
              OR r.max_budget_amount >= trunc(
                  (SELECT monthly_rent_deposit_amount FROM property_listing WHERE id = g.listing_l5) * 0.9
              )
          )
          AND (
              NOT EXISTS (
                  SELECT 1 FROM property_requirement_complex rc
                  WHERE rc.brokerage_id = r.brokerage_id AND rc.requirement_id = r.id
              )
              OR EXISTS (
                  SELECT 1 FROM property_requirement_complex rc
                  WHERE rc.brokerage_id = r.brokerage_id
                    AND rc.requirement_id = r.id
                    AND rc.complex_id = g.complex_c2
              )
          )
    )

    -- 케이스 D: 매도 구분 앵커 R8 → 대응하는 매물 거래 유형이 없다
    UNION ALL SELECT 304, '케이스 D (매도 구입장 앵커) 대응 매물 거래 유형 수', 0, (
        SELECT count(*)
        FROM property_requirement r
        JOIN tenant t ON t.brokerage_id = r.brokerage_id
        WHERE r.custom_fields->>'seed_key' = 'R8'
          AND r.demand_type IN ('매수', '전세', '월세')
    )

    -- 케이스 E: 전세 앵커 L4 → 전세·활성·예산 하한(21.5억의 90%)·희망 단지
    UNION ALL SELECT 305, '케이스 E (전세 매물 앵커) 후보 구입장 수', 1, (
        SELECT count(*)
        FROM property_requirement r
        JOIN party p ON p.brokerage_id = r.brokerage_id AND p.id = r.party_id
        JOIN ledger g ON g.brokerage_id = r.brokerage_id
        WHERE r.is_deleted = FALSE
          AND p.is_deleted = FALSE
          AND r.demand_type = '전세'
          AND r.status = 'ACTIVE'
          AND (
              r.max_budget_amount IS NULL
              OR r.max_budget_amount >= trunc(
                  (SELECT jeonse_deposit_amount FROM property_listing WHERE id = g.listing_l4) * 0.9
              )
          )
          AND (
              NOT EXISTS (
                  SELECT 1 FROM property_requirement_complex rc
                  WHERE rc.brokerage_id = r.brokerage_id AND rc.requirement_id = r.id
              )
              OR EXISTS (
                  SELECT 1 FROM property_requirement_complex rc
                  WHERE rc.brokerage_id = r.brokerage_id
                    AND rc.requirement_id = r.id
                    AND rc.complex_id = g.complex_c1
              )
          )
    )

    -- ── 4. 관계 일관성 ───────────────────────────────────────────────────────

    UNION ALL SELECT 401, 'brokerage_id 가 어긋난 세대·단지 조합', 0, (
        SELECT count(*) FROM property_unit u
        JOIN tenant t ON t.brokerage_id = u.brokerage_id
        LEFT JOIN property_complex c ON c.id = u.complex_id AND c.brokerage_id = u.brokerage_id
        WHERE c.id IS NULL
    )
    UNION ALL SELECT 402, 'brokerage_id 가 어긋난 매물·세대 조합', 0, (
        SELECT count(*) FROM property_listing l
        JOIN tenant t ON t.brokerage_id = l.brokerage_id
        LEFT JOIN property_unit u ON u.id = l.unit_id AND u.brokerage_id = l.brokerage_id
        WHERE u.id IS NULL
    )
    UNION ALL SELECT 403, '거래 가능 플래그가 정확히 1개가 아닌 매물', 0, (
        SELECT count(*) FROM property_listing l
        JOIN tenant t ON t.brokerage_id = l.brokerage_id
        WHERE (l.is_sale_available::int + l.is_jeonse_available::int + l.is_monthly_rent_available::int) <> 1
    )
    UNION ALL SELECT 404, '개인정보 활용 동의가 없는 구입장 인물', 0, (
        SELECT count(DISTINCT r.party_id) FROM property_requirement r
        JOIN tenant t ON t.brokerage_id = r.brokerage_id
        JOIN party p ON p.brokerage_id = r.brokerage_id AND p.id = r.party_id
        WHERE p.privacy_consent_at IS NULL
    )
    UNION ALL SELECT 405, '상담 로그가 없는 활성 매물·구입장', 0, (
        SELECT count(*) FROM (
            SELECT l.id FROM property_listing l JOIN tenant t ON t.brokerage_id = l.brokerage_id
            WHERE l.status = 'RECEIVED' AND l.is_deleted = FALSE
              AND NOT EXISTS (SELECT 1 FROM client_interaction i WHERE i.listing_id = l.id AND i.is_voided = FALSE)
            UNION ALL
            SELECT r.id FROM property_requirement r JOIN tenant t ON t.brokerage_id = r.brokerage_id
            WHERE r.status = 'ACTIVE' AND r.is_deleted = FALSE
              AND NOT EXISTS (SELECT 1 FROM client_interaction i WHERE i.requirement_id = r.id AND i.is_voided = FALSE)
        ) missing
    )
    UNION ALL SELECT 406, '대량 케이스 F·G·H·I 후보 수 불일치', 0, (
        SELECT count(*)
        FROM (
            SELECT 'F' AS case_key, 19 AS expected, (
                SELECT count(*)
                FROM property_requirement r
                JOIN party p ON p.brokerage_id = r.brokerage_id AND p.id = r.party_id
                JOIN ledger g ON g.brokerage_id = r.brokerage_id
                WHERE r.is_deleted = FALSE
                  AND p.is_deleted = FALSE
                  AND r.demand_type = '매수'
                  AND r.status = 'ACTIVE'
                  AND (
                      r.max_budget_amount IS NULL
                      OR r.max_budget_amount >= trunc(
                          (SELECT sale_price FROM property_listing WHERE id = g.listing_bl01) * 0.9
                      )
                  )
                  AND (
                      NOT EXISTS (
                          SELECT 1 FROM property_requirement_complex rc
                          WHERE rc.brokerage_id = r.brokerage_id AND rc.requirement_id = r.id
                      )
                      OR EXISTS (
                          SELECT 1 FROM property_requirement_complex rc
                          WHERE rc.brokerage_id = r.brokerage_id
                            AND rc.requirement_id = r.id
                            AND rc.complex_id = g.complex_c3
                      )
                  )
            ) AS actual
            UNION ALL
            SELECT 'G', 12, (
                SELECT count(*)
                FROM property_listing l
                JOIN property_unit u ON u.brokerage_id = l.brokerage_id AND u.id = l.unit_id
                JOIN ledger g ON g.brokerage_id = l.brokerage_id
                WHERE l.is_deleted = FALSE
                  AND u.is_deleted = FALSE
                  AND l.is_sale_available = TRUE
                  AND l.status = 'RECEIVED'
                  AND u.complex_id = g.complex_c3
                  AND (
                      l.sale_price IS NULL
                      OR l.sale_price <= trunc(
                          (SELECT max_budget_amount FROM property_requirement WHERE id = g.requirement_br01) * 1.1
                      )
                  )
            )
            UNION ALL
            SELECT 'H', 12, (
                SELECT count(*)
                FROM property_requirement r
                JOIN party p ON p.brokerage_id = r.brokerage_id AND p.id = r.party_id
                JOIN ledger g ON g.brokerage_id = r.brokerage_id
                WHERE r.is_deleted = FALSE
                  AND p.is_deleted = FALSE
                  AND r.demand_type = '전세'
                  AND r.status = 'ACTIVE'
                  AND (
                      r.max_budget_amount IS NULL
                      OR r.max_budget_amount >= trunc(
                          (SELECT jeonse_deposit_amount FROM property_listing WHERE id = g.listing_bl13) * 0.9
                      )
                  )
                  AND EXISTS (
                      SELECT 1 FROM property_requirement_complex rc
                      WHERE rc.brokerage_id = r.brokerage_id
                        AND rc.requirement_id = r.id
                        AND rc.complex_id = g.complex_c4
                  )
            )
            UNION ALL
            SELECT 'I', 10, (
                SELECT count(*)
                FROM property_requirement r
                JOIN party p ON p.brokerage_id = r.brokerage_id AND p.id = r.party_id
                JOIN ledger g ON g.brokerage_id = r.brokerage_id
                WHERE r.is_deleted = FALSE
                  AND p.is_deleted = FALSE
                  AND r.demand_type = '월세'
                  AND r.status = 'ACTIVE'
                  AND (
                      r.max_budget_amount IS NULL
                      OR r.max_budget_amount >= trunc(
                          (SELECT monthly_rent_deposit_amount FROM property_listing WHERE id = g.listing_bl23) * 0.9
                      )
                  )
                  AND EXISTS (
                      SELECT 1 FROM property_requirement_complex rc
                      WHERE rc.brokerage_id = r.brokerage_id
                        AND rc.requirement_id = r.id
                        AND rc.complex_id = g.complex_c5
                  )
            )
        ) matrix
        WHERE matrix.expected <> matrix.actual
    )
    UNION ALL SELECT 407, '최종 접촉 시각이 비어 있는 앵커 세대·구입장', 0, (
        SELECT count(*) FROM (
            SELECT u.id FROM property_unit u JOIN tenant t ON t.brokerage_id = u.brokerage_id
            WHERE u.custom_fields->>'seed_key' IN ('U1', 'U2', 'U5') AND u.last_contact_at IS NULL
            UNION ALL
            SELECT r.id FROM property_requirement r JOIN tenant t ON t.brokerage_id = r.brokerage_id
            WHERE r.custom_fields->>'seed_key' IN ('R1', 'R8') AND r.last_contact_at IS NULL
        ) missing
    )

    -- ── 5. 개인정보와 날짜 ───────────────────────────────────────────────────

    UNION ALL SELECT 501, '합성 테스트 형식(010-0000-)을 벗어난 연락처', 0, (
        SELECT count(*) FROM party_contact c
        JOIN tenant t ON t.brokerage_id = c.brokerage_id
        WHERE c.contact_value NOT LIKE '010-0000-%'
    )
    UNION ALL SELECT 502, 'F3_SYNTHETIC 표식이 없는 인물', 0, (
        SELECT count(*) FROM party p
        JOIN tenant t ON t.brokerage_id = p.brokerage_id
        WHERE p.name NOT LIKE 'F3_SYNTHETIC %'
    )
    UNION ALL SELECT 503, '이미 지난 임대차 만기일', 0, (
        SELECT count(*) FROM property_unit u
        JOIN tenant t ON t.brokerage_id = u.brokerage_id
        WHERE u.tenancy_expiry_date IS NOT NULL AND u.tenancy_expiry_date < CURRENT_DATE
    )
    UNION ALL SELECT 504, '이미 지난 희망 입주일·의뢰 만료일 (종료 구입장 제외)', 0, (
        SELECT count(*) FROM property_requirement r
        JOIN tenant t ON t.brokerage_id = r.brokerage_id
        WHERE r.status = 'ACTIVE'
          AND (r.desired_move_in_date < CURRENT_DATE OR r.request_expiry_date < CURRENT_DATE)
    )
    UNION ALL SELECT 505, '미래에 접수된 매물·구입장', 0, (
        SELECT count(*) FROM (
            SELECT l.id FROM property_listing l JOIN tenant t ON t.brokerage_id = l.brokerage_id
            WHERE l.received_at > CURRENT_DATE
            UNION ALL
            SELECT r.id FROM property_requirement r JOIN tenant t ON t.brokerage_id = r.brokerage_id
            WHERE r.received_at > CURRENT_DATE
        ) future
    )
)
SELECT
    "검사",
    "기대",
    "실제",
    CASE WHEN "기대" = "실제" THEN 'PASS' ELSE 'FAIL' END AS "결과"
FROM checks
ORDER BY sort_key;
