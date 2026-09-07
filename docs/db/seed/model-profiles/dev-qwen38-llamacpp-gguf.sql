-- PostgreSQL 15+
-- F3 합성 seed의 dev llama.cpp 기본 POC 설정. GPU runtime 배포 전 공유 dev에 적용하지 않는다.

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
    'dev-qwen38-llamacpp-gguf',
    1,
    'llama_cpp',
    'unsloth/Qwen3.8-27B-GGUF:UD-Q4_K_M',
    '4ca720788d1e01f1bff70c033e0d0028fd02e502@sha256:322e194ff79741c7baa497c240f677f54b201b0efab44ca8e50f122b39123482',
    'general-dev-gpu',
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
