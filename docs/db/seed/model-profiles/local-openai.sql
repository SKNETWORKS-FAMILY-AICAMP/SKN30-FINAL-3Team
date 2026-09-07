-- PostgreSQL 15+
-- F3 합성 seed의 로컬 OpenAI 모델 설정. migration 이 아니며 prod 에 적용하지 않는다.

\set ON_ERROR_STOP on

BEGIN;

INSERT INTO ai_model_config (
    brokerage_id, capability, config_key, config_version,
    provider, model_name, model_version, endpoint_alias,
    parameters, is_active, created_by
)
SELECT
    t.brokerage_id,
    s.capability,
    'local-openai',
    1,
    'openai',
    'gpt-5.6-luna',
    NULL,
    NULL,
    '{}'::jsonb,
    TRUE,
    t.user_id
FROM (
    SELECT b.id AS brokerage_id, u.id AS user_id
    FROM brokerage b
    JOIN app_user u ON u.brokerage_id = b.id AND u.login_id = 'f3_synthetic_dev'
    WHERE b.name = 'F3_SYNTHETIC 합성중개사무소'
) t
CROSS JOIN (VALUES ('POSITION_CARD'), ('BROKERAGE_JUDGMENT')) AS s(capability);

COMMIT;
