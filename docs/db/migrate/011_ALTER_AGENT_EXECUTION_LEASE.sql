-- PostgreSQL 15+
-- 에이전트 실행 Worker 선점을 위한 lease 소유자·만료 시각과 시도 횟수 보존
-- depends: 010_ALTER_PARTY_PRIVACY_CONSENT


-- CANDIDATE_CARDS_READY 가 21자라 기존 VARCHAR(20) 에 들어가지 않는다.
ALTER TABLE agent_run
    ALTER COLUMN status TYPE VARCHAR(30),
    ADD COLUMN lease_owner VARCHAR(64),
    ADD COLUMN lease_expires_at TIMESTAMPTZ,
    ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0,
    ADD CONSTRAINT ck_agent_run_attempt_count_not_negative
        CHECK (attempt_count >= 0);

-- 선점 대상은 사무소를 가리지 않고 오래된 순으로 고르므로 기존 brokerage_id 선두 인덱스를
-- 쓸 수 없다. 선점 쿼리의 필터와 정렬에만 맞춘 부분 인덱스를 둔다.
CREATE INDEX idx_agent_run_claim_queue
    ON agent_run (created_at, id)
    WHERE parent_run_id IS NULL
      AND run_type = 'CROSS_JUDGMENT'
      AND status IN ('QUEUED', 'RUNNING');


COMMENT ON COLUMN agent_run.lease_owner IS '실행을 선점한 Worker 인스턴스 식별자. NULL은 선점되지 않은 상태를 뜻한다.';
COMMENT ON COLUMN agent_run.lease_expires_at IS '현재 선점의 만료 시각. 이 시각을 지나면 다른 Worker가 재선점할 수 있다.';
COMMENT ON COLUMN agent_run.attempt_count IS '실행이 선점된 누적 횟수. 재선점 상한 판단에 사용한다.';
