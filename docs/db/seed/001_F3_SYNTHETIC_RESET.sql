-- PostgreSQL 15+
-- F3 합성 테스트 사무소의 모든 데이터를 지운다. migration 이 아니며 prod 에 적용하지 않는다.
--
-- 삭제 범위는 brokerage.name = 'F3_SYNTHETIC 합성중개사무소' 한 곳뿐이다. 이름이 정확히
-- 일치하는 사무소가 없으면 어떤 행도 지우지 않는다. 다른 사무소, 다른 개발 계정과
-- seed-sample-ledger 가 만든 데이터는 건드리지 않는다.
--
-- 002_F3_SYNTHETIC_SEED.sql 을 다시 적용하기 전에 실행한다. 두 파일을 순서대로 돌리면
-- 몇 번을 반복해도 같은 상태가 된다.
--
-- seed 는 migration 실행기가 관리하지 않으므로 transaction 을 이 파일이 직접 연다.
-- 중간에 실패하면 사무소가 반쯤 지워진 상태로 남지 않는다.

\set ON_ERROR_STOP on

BEGIN;

CREATE TEMP TABLE f3_synthetic_tenant ON COMMIT DROP AS
SELECT id AS brokerage_id
FROM brokerage
WHERE name = 'F3_SYNTHETIC 합성중개사무소';

-- 삭제 순서는 참조를 거슬러 올라간다. agent_run 은 model_config_id 로 ai_model_config 를
-- 참조하므로 반드시 그보다 먼저 지운다.

DELETE FROM ai_evaluation_result          WHERE brokerage_id IN (SELECT brokerage_id FROM f3_synthetic_tenant);
DELETE FROM ai_decision_feedback          WHERE brokerage_id IN (SELECT brokerage_id FROM f3_synthetic_tenant);
DELETE FROM match_candidate_evidence      WHERE brokerage_id IN (SELECT brokerage_id FROM f3_synthetic_tenant);
DELETE FROM match_candidate_evaluation    WHERE brokerage_id IN (SELECT brokerage_id FROM f3_synthetic_tenant);
DELETE FROM match_evaluation              WHERE brokerage_id IN (SELECT brokerage_id FROM f3_synthetic_tenant);
DELETE FROM negotiation_position_price    WHERE brokerage_id IN (SELECT brokerage_id FROM f3_synthetic_tenant);
DELETE FROM negotiation_position_evidence WHERE brokerage_id IN (SELECT brokerage_id FROM f3_synthetic_tenant);
DELETE FROM negotiation_position_analysis WHERE brokerage_id IN (SELECT brokerage_id FROM f3_synthetic_tenant);
DELETE FROM agent_capability_call         WHERE brokerage_id IN (SELECT brokerage_id FROM f3_synthetic_tenant);
DELETE FROM agent_run                     WHERE brokerage_id IN (SELECT brokerage_id FROM f3_synthetic_tenant);

DELETE FROM interaction_log_proposal       WHERE brokerage_id IN (SELECT brokerage_id FROM f3_synthetic_tenant);
DELETE FROM transcription_field_proposal   WHERE brokerage_id IN (SELECT brokerage_id FROM f3_synthetic_tenant);
DELETE FROM consultation_transcription_job WHERE brokerage_id IN (SELECT brokerage_id FROM f3_synthetic_tenant);
DELETE FROM ledger_draft                   WHERE brokerage_id IN (SELECT brokerage_id FROM f3_synthetic_tenant);

DELETE FROM client_interaction            WHERE brokerage_id IN (SELECT brokerage_id FROM f3_synthetic_tenant);
DELETE FROM property_requirement_complex  WHERE brokerage_id IN (SELECT brokerage_id FROM f3_synthetic_tenant);
DELETE FROM property_requirement          WHERE brokerage_id IN (SELECT brokerage_id FROM f3_synthetic_tenant);
DELETE FROM property_listing              WHERE brokerage_id IN (SELECT brokerage_id FROM f3_synthetic_tenant);
DELETE FROM property_unit_party_relation  WHERE brokerage_id IN (SELECT brokerage_id FROM f3_synthetic_tenant);
DELETE FROM property_unit                 WHERE brokerage_id IN (SELECT brokerage_id FROM f3_synthetic_tenant);
DELETE FROM property_complex              WHERE brokerage_id IN (SELECT brokerage_id FROM f3_synthetic_tenant);
DELETE FROM party_contact                 WHERE brokerage_id IN (SELECT brokerage_id FROM f3_synthetic_tenant);
DELETE FROM party                         WHERE brokerage_id IN (SELECT brokerage_id FROM f3_synthetic_tenant);

DELETE FROM user_session     WHERE brokerage_id IN (SELECT brokerage_id FROM f3_synthetic_tenant);
DELETE FROM ai_model_config  WHERE brokerage_id IN (SELECT brokerage_id FROM f3_synthetic_tenant);

-- brokerage 와 app_user 행은 **일부러 남긴다**.
--
-- 두 행을 지우면 다시 seed 할 때 새 ID 가 발급되고, 그때마다 backend/.env 의
-- AUTH_DEVELOPMENT_BROKERAGE_ID 를 고치고 API 서버를 재시작해야 한다. 반복 실행이 목적인
-- seed 에서 그 왕복은 그대로 마찰이 된다. 두 행의 내용은 어차피 바뀌지 않으므로 남겨 두면
-- brokerage_id 가 영구히 고정된다.
--
-- 사무소 행까지 완전히 폐기하려면 아래 두 문장을 직접 실행한다. 실행 후에는 .env 를
-- 반드시 새 ID 로 갱신한다.
--
--   DELETE FROM app_user  WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = 'F3_SYNTHETIC 합성중개사무소');
--   DELETE FROM brokerage WHERE name = 'F3_SYNTHETIC 합성중개사무소';

SELECT
    count(*) AS "초기화한 합성 사무소 수",
    coalesce(max(brokerage_id)::text, '(없음)') AS "brokerage_id"
FROM f3_synthetic_tenant;

COMMIT;
