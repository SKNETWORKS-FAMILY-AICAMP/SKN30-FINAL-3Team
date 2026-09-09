-- depends: 020_CREATE_F3_AUTOMATION
-- Preserve rows, foreign keys, and trigger bindings while adopting matching domain names.
ALTER TABLE f3_source_revision RENAME TO match_source_revision;
ALTER TABLE match_source_revision RENAME CONSTRAINT f3_source_revision_pkey TO match_source_revision_pkey;
ALTER TABLE match_source_revision RENAME CONSTRAINT f3_source_revision_brokerage_id_fkey TO match_source_revision_brokerage_id_fkey;
ALTER TABLE f3_change_outbox RENAME TO match_change_outbox;
ALTER TABLE match_change_outbox RENAME CONSTRAINT f3_change_outbox_pkey TO match_change_outbox_pkey;
ALTER TABLE match_change_outbox RENAME CONSTRAINT f3_change_outbox_brokerage_id_fkey TO match_change_outbox_brokerage_id_fkey;
ALTER TABLE f3_target_state RENAME TO match_target_state;
ALTER TABLE match_target_state RENAME CONSTRAINT f3_target_state_pkey TO match_target_state_pkey;
ALTER TABLE match_target_state RENAME CONSTRAINT f3_target_state_brokerage_id_fkey TO match_target_state_brokerage_id_fkey;
ALTER TABLE match_target_state RENAME CONSTRAINT f3_target_state_anchor_type_check TO match_target_state_anchor_type_check;
ALTER TABLE match_target_state RENAME CONSTRAINT f3_target_state_brokerage_id_current_run_id_fkey TO match_target_state_brokerage_id_current_run_id_fkey;
ALTER TABLE match_target_state RENAME CONSTRAINT f3_target_state_brokerage_id_current_result_id_fkey TO match_target_state_brokerage_id_current_result_id_fkey;
ALTER INDEX idx_f3_target_due RENAME TO idx_match_target_due;
ALTER FUNCTION record_f3_source_change() RENAME TO record_match_source_change;

CREATE OR REPLACE FUNCTION record_match_source_change() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    record_data JSONB;
    old_data JSONB;
    new_data JSONB;
    tenant BIGINT;
    next_revision BIGINT;
    ignored TEXT[] := ARRAY['row_version','updated_at','created_at','updated_by','created_by',
        'assigned_user_id','memo','notes','retention_until','purged_at'];
BEGIN
    IF TG_OP = 'UPDATE' THEN
        old_data := to_jsonb(OLD) - ignored;
        new_data := to_jsonb(NEW) - ignored;
        IF old_data IS NOT DISTINCT FROM new_data THEN RETURN NEW; END IF;
    END IF;
    record_data := CASE WHEN TG_OP = 'DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
    tenant := (record_data->>'brokerage_id')::BIGINT;
    INSERT INTO match_source_revision(brokerage_id, revision) VALUES (tenant, 1)
    ON CONFLICT (brokerage_id) DO UPDATE
        SET revision=match_source_revision.revision+1, changed_at=now()
    RETURNING revision INTO next_revision;
    INSERT INTO match_change_outbox(brokerage_id, revision, source_table, source_id)
        VALUES (tenant, next_revision, TG_TABLE_NAME, (record_data->>'id')::BIGINT)
    ON CONFLICT (brokerage_id) DO UPDATE SET revision=EXCLUDED.revision,
        source_table=EXCLUDED.source_table, source_id=EXCLUDED.source_id, changed_at=now();
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$;
ALTER TRIGGER f3_change ON property_listing RENAME TO match_change;
ALTER TRIGGER f3_change ON property_requirement RENAME TO match_change;
ALTER TRIGGER f3_change ON property_unit RENAME TO match_change;
ALTER TRIGGER f3_change ON property_complex RENAME TO match_change;
ALTER TRIGGER f3_change ON party RENAME TO match_change;
ALTER TRIGGER f3_change ON property_unit_party_relation RENAME TO match_change;
ALTER TRIGGER f3_change ON property_requirement_complex RENAME TO match_change;
ALTER TRIGGER f3_change ON client_interaction RENAME TO match_change;
ALTER TRIGGER f3_change ON ai_model_config RENAME TO match_change;
COMMENT ON TABLE match_source_revision IS '원장 transaction과 원자적으로 증가하는 사무소 매칭 입력 변경 토큰.';
COMMENT ON TABLE match_target_state IS '재구축 가능한 매칭 대상별 최신 결과 포인터와 자동 검증 대기 상태.';
