-- depends: 019_CREATE_CHATBOT
-- F1 writes and invalidation are atomic; only identifiers are retained in the outbox.
CREATE TABLE f3_source_revision (
    brokerage_id BIGINT PRIMARY KEY REFERENCES brokerage(id),
    revision BIGINT NOT NULL DEFAULT 0,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE f3_change_outbox (
    brokerage_id BIGINT PRIMARY KEY REFERENCES brokerage(id),
    revision BIGINT NOT NULL,
    source_table VARCHAR(80) NOT NULL,
    source_id BIGINT,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE f3_target_state (
    brokerage_id BIGINT NOT NULL REFERENCES brokerage(id),
    anchor_type VARCHAR(20) NOT NULL CHECK (anchor_type IN ('LISTING', 'REQUIREMENT')),
    anchor_id BIGINT NOT NULL,
    desired_revision BIGINT NOT NULL DEFAULT 0,
    verified_revision BIGINT,
    verified_day DATE,
    config_identity VARCHAR(80),
    input_identity VARCHAR(80),
    anchor_identity VARCHAR(80),
    current_run_id BIGINT,
    current_result_id BIGINT,
    due_at TIMESTAMPTZ,
    verified_at TIMESTAMPTZ,
    meaningful_changed_at TIMESTAMPTZ,
    PRIMARY KEY (brokerage_id, anchor_type, anchor_id),
    FOREIGN KEY (brokerage_id, current_run_id) REFERENCES agent_run(brokerage_id, id),
    FOREIGN KEY (brokerage_id, current_result_id) REFERENCES match_evaluation(brokerage_id, id)
);
CREATE INDEX idx_f3_target_due ON f3_target_state(due_at) WHERE due_at IS NOT NULL;
ALTER TABLE agent_run ADD COLUMN next_attempt_at TIMESTAMPTZ;
ALTER TABLE agent_run ADD COLUMN priority INTEGER NOT NULL DEFAULT 0;
COMMENT ON TABLE f3_source_revision IS '원장 transaction과 원자적으로 증가하는 사무소 F3 입력 변경 토큰.';
COMMENT ON COLUMN f3_source_revision.brokerage_id IS '변경된 원천을 소유하는 사무소.';
COMMENT ON COLUMN f3_source_revision.revision IS '현재 원천 revision; 결과 게시 fencing에 사용한다.';
COMMENT ON COLUMN f3_source_revision.changed_at IS '마지막 의미 있는 원천 변경 시각.';
COMMENT ON TABLE f3_change_outbox IS '사무소별 병합된 내구성 변경 이벤트; 상담 원문을 저장하지 않는다.';
COMMENT ON COLUMN f3_change_outbox.brokerage_id IS '이벤트를 소유하는 사무소와 병합 키.';
COMMENT ON COLUMN f3_change_outbox.revision IS '이벤트가 대표하는 마지막 원천 revision.';
COMMENT ON COLUMN f3_change_outbox.source_table IS '마지막 변경 원천 종류.';
COMMENT ON COLUMN f3_change_outbox.source_id IS '마지막 변경 행 식별자; 복합 키 관계이면 NULL.';
COMMENT ON COLUMN f3_change_outbox.changed_at IS '병합 대기 시간을 계산하는 마지막 변경 시각.';
COMMENT ON TABLE f3_target_state IS '재구축 가능한 F3 대상별 최신 결과 포인터와 자동 검증 대기 상태.';
COMMENT ON COLUMN f3_target_state.brokerage_id IS '대상과 결과를 소유하는 사무소.';
COMMENT ON COLUMN f3_target_state.anchor_type IS '판정 기준 장부 종류.';
COMMENT ON COLUMN f3_target_state.anchor_id IS '판정 기준 원장 식별자; 삭제 이력을 위해 다형 참조.';
COMMENT ON COLUMN f3_target_state.desired_revision IS '자동 검증이 필요한 마지막 원천 revision.';
COMMENT ON COLUMN f3_target_state.verified_revision IS '현재 결과 입력을 검증한 원천 revision.';
COMMENT ON COLUMN f3_target_state.verified_day IS 'UTC 날짜 신호를 검증한 날짜.';
COMMENT ON COLUMN f3_target_state.config_identity IS '활성 모델과 공개 prompt/workflow 버전 지문.';
COMMENT ON COLUMN f3_target_state.input_identity IS '실제 앵커와 SQL 후보 집합 및 선택 후보 입력의 지문.';
COMMENT ON COLUMN f3_target_state.anchor_identity IS '실제 앵커 입력의 지문; 원문을 저장하지 않는다.';
COMMENT ON COLUMN f3_target_state.current_run_id IS '마지막으로 검증된 성공 실행.';
COMMENT ON COLUMN f3_target_state.current_result_id IS '마지막으로 검증된 불변 판정 결과.';
COMMENT ON COLUMN f3_target_state.due_at IS '자동 검증이 가능한 시각; NULL이면 미대기.';
COMMENT ON COLUMN f3_target_state.verified_at IS '모델 호출 또는 동일 입력 재검증 완료 시각.';
COMMENT ON COLUMN f3_target_state.meaningful_changed_at IS '새 결과를 게시한 시각; 동일 결과 재검증은 유지.';
COMMENT ON COLUMN agent_run.next_attempt_at IS '일시 실패 후 재선점 가능 시각.';
COMMENT ON COLUMN agent_run.priority IS '사용자 요청이 자동 작업보다 먼저 선점되는 서버 지정 우선순위.';

CREATE FUNCTION record_f3_source_change() RETURNS trigger LANGUAGE plpgsql AS $$
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
    INSERT INTO f3_source_revision(brokerage_id, revision) VALUES (tenant, 1)
    ON CONFLICT (brokerage_id) DO UPDATE
        SET revision=f3_source_revision.revision+1, changed_at=now()
    RETURNING revision INTO next_revision;
    INSERT INTO f3_change_outbox(brokerage_id, revision, source_table, source_id)
        VALUES (tenant, next_revision, TG_TABLE_NAME, (record_data->>'id')::BIGINT)
    ON CONFLICT (brokerage_id) DO UPDATE SET revision=EXCLUDED.revision,
        source_table=EXCLUDED.source_table, source_id=EXCLUDED.source_id, changed_at=now();
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER f3_change AFTER INSERT OR UPDATE OR DELETE ON property_listing FOR EACH ROW EXECUTE FUNCTION record_f3_source_change();
CREATE TRIGGER f3_change AFTER INSERT OR UPDATE OR DELETE ON property_requirement FOR EACH ROW EXECUTE FUNCTION record_f3_source_change();
CREATE TRIGGER f3_change AFTER INSERT OR UPDATE OR DELETE ON property_unit FOR EACH ROW EXECUTE FUNCTION record_f3_source_change();
CREATE TRIGGER f3_change AFTER INSERT OR UPDATE OR DELETE ON property_complex FOR EACH ROW EXECUTE FUNCTION record_f3_source_change();
CREATE TRIGGER f3_change AFTER INSERT OR UPDATE OR DELETE ON party FOR EACH ROW EXECUTE FUNCTION record_f3_source_change();
CREATE TRIGGER f3_change AFTER INSERT OR UPDATE OR DELETE ON property_unit_party_relation FOR EACH ROW EXECUTE FUNCTION record_f3_source_change();
CREATE TRIGGER f3_change AFTER INSERT OR UPDATE OR DELETE ON property_requirement_complex FOR EACH ROW EXECUTE FUNCTION record_f3_source_change();
CREATE TRIGGER f3_change AFTER INSERT OR UPDATE OR DELETE ON client_interaction FOR EACH ROW EXECUTE FUNCTION record_f3_source_change();
CREATE TRIGGER f3_change AFTER INSERT OR UPDATE OR DELETE ON ai_model_config FOR EACH ROW EXECUTE FUNCTION record_f3_source_change();
-- Existing datasets are lazily processed in bounded Worker batches after explicit auto opt-in.
INSERT INTO f3_source_revision(brokerage_id, revision) SELECT id, 1 FROM brokerage;
INSERT INTO f3_change_outbox(brokerage_id, revision, source_table)
    SELECT id, 1, 'BACKFILL' FROM brokerage;
