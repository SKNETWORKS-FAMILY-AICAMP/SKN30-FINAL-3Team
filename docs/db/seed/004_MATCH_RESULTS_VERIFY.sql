-- Read-only verification of explicit deterministic example results, not model quality.
\set ON_ERROR_STOP on
WITH tenant AS (
    SELECT id FROM brokerage WHERE name = 'F3_SYNTHETIC 합성중개사무소'
), runs AS (
    SELECT r.* FROM agent_run r JOIN tenant t ON t.id=r.brokerage_id
    WHERE r.redacted_output_snapshot->'synthetic_fixture'->>'kind'='DETERMINISTIC_MATCH_SEED'
), states AS (
    SELECT s.* FROM match_target_state s JOIN tenant t ON t.id=s.brokerage_id
), checks(ordering, name, expected, actual) AS (
    SELECT 1, '합성 사무소', 1, count(*) FROM tenant
    UNION ALL SELECT 2, '전체 대상 상태', 84, count(*) FROM states
    UNION ALL SELECT 3, '적격 대상의 완료 예시', 81, count(*) FROM runs WHERE status='COMPLETED'
    UNION ALL SELECT 4, '완료 결과 포인터', 81, count(*) FROM states s
        JOIN runs r ON r.brokerage_id=s.brokerage_id AND r.id=s.current_run_id
        JOIN match_evaluation m ON m.brokerage_id=s.brokerage_id AND m.id=s.current_result_id
        AND m.agent_run_id=r.id
    UNION ALL SELECT 5, '최신 입력·날짜 검증', 81, count(*) FROM states s
        JOIN match_source_revision rev ON rev.brokerage_id=s.brokerage_id
        WHERE s.current_result_id IS NOT NULL AND s.verified_revision=rev.revision
        AND s.verified_day=(now() AT TIME ZONE 'UTC')::date AND s.config_identity IS NOT NULL
        AND s.input_identity IS NOT NULL
    UNION ALL SELECT 6, '잔여 예시 실행', 0, count(*) FROM runs WHERE status<>'COMPLETED'
    UNION ALL SELECT 7, '자동 처리 대기', 0, count(*) FROM states WHERE due_at IS NOT NULL
    UNION ALL SELECT 8, '소비할 합성 변경 이벤트', 0, count(*) FROM match_change_outbox o JOIN tenant t ON t.id=o.brokerage_id
    UNION ALL SELECT 9, '유효 앵커 카드', 81, count(*) FROM runs r
        JOIN match_evaluation m ON m.brokerage_id=r.brokerage_id AND m.agent_run_id=r.id
        JOIN negotiation_position_analysis p ON p.brokerage_id=r.brokerage_id AND p.id=m.anchor_position_analysis_id
        WHERE p.invalidated_at IS NULL
    UNION ALL SELECT 10, '상위 5건 초과 AI 판정 없음', 0, count(*) FROM (
        SELECT m.id FROM match_evaluation m JOIN runs r ON r.id=m.agent_run_id AND r.brokerage_id=m.brokerage_id
        JOIN match_candidate_evaluation c ON c.match_evaluation_id=m.id AND c.brokerage_id=m.brokerage_id
        GROUP BY m.id HAVING count(*)>5
    ) x
    UNION ALL SELECT 11, '강함·약함·기각 예시', 3, count(DISTINCT c.match_grade)
        FROM match_candidate_evaluation c JOIN runs r ON r.brokerage_id=c.brokerage_id
        JOIN match_evaluation m ON m.id=c.match_evaluation_id AND m.agent_run_id=r.id
    UNION ALL SELECT 12, '모델 추론 미실행 표시', 81, count(*) FROM runs
        WHERE redacted_output_snapshot->'synthetic_fixture'->>'model_inference'='false'
)
SELECT name AS "검사",expected AS "기대",actual AS "실제",
       CASE WHEN expected=actual THEN 'PASS' ELSE 'FAIL' END AS "결과"
FROM checks ORDER BY ordering;
