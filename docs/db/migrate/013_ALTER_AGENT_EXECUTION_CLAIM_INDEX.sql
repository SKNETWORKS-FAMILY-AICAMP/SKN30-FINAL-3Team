-- PostgreSQL 15+
-- Worker가 중간 진행 상태의 만료 lease도 효율적으로 회수하도록 선점 인덱스 확장
-- depends: 012_CREATE_NEGOTIATION_POSITION_PRICE


-- 011의 인덱스는 QUEUED·RUNNING만 포함했다. ANCHOR_READY 저장 후 Worker가 중단되면
-- 해당 상태도 lease 만료 뒤 재선점하므로 같은 선점 쿼리의 부분 인덱스에 포함한다.
DROP INDEX idx_agent_run_claim_queue;

CREATE INDEX idx_agent_run_claim_queue
    ON agent_run (created_at, id)
    WHERE parent_run_id IS NULL
      AND run_type = 'CROSS_JUDGMENT'
      AND status IN ('QUEUED', 'RUNNING', 'ANCHOR_READY');
