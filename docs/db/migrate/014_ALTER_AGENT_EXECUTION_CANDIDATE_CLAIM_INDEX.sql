-- PostgreSQL 15+
-- 후보 추출 완료 상태의 만료 lease도 효율적으로 회수하도록 선점 인덱스 확장
-- depends: 013_ALTER_AGENT_EXECUTION_CLAIM_INDEX


-- CANDIDATES_READY는 종료가 아닌 중간 진행 상태다. 후보 snapshot 저장 뒤 Worker가
-- 중단되면 lease 만료 후 다음 단계가 이 실행을 재선점해야 한다.
DROP INDEX idx_agent_run_claim_queue;

CREATE INDEX idx_agent_run_claim_queue
    ON agent_run (created_at, id)
    WHERE parent_run_id IS NULL
      AND run_type = 'CROSS_JUDGMENT'
      AND status IN ('QUEUED', 'RUNNING', 'ANCHOR_READY', 'CANDIDATES_READY');
