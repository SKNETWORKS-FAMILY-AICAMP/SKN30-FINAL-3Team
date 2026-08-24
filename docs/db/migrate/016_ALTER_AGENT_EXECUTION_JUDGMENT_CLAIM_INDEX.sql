-- PostgreSQL 15+
-- 중개 판정 중 상태의 만료 lease도 효율적으로 회수하도록 선점 인덱스 확장
-- depends: 015_ALTER_AGENT_EXECUTION_CANDIDATE_CARD_CLAIM_INDEX


-- JUDGING은 종료가 아닌 중간 진행 상태다. Provider 호출 중 Worker가 중단되면
-- lease 만료 후 다른 Worker가 같은 판정 바인딩으로 실행을 재개해야 한다.
DROP INDEX idx_agent_run_claim_queue;

CREATE INDEX idx_agent_run_claim_queue
    ON agent_run (created_at, id)
    WHERE parent_run_id IS NULL
      AND run_type = 'CROSS_JUDGMENT'
      AND status IN (
          'QUEUED',
          'RUNNING',
          'ANCHOR_READY',
          'CANDIDATES_READY',
          'CANDIDATE_CARDS_READY',
          'JUDGING'
      );
