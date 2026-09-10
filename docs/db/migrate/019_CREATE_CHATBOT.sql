-- PostgreSQL 15+
-- F4 작성자 전용 대화·요청·메시지 저장
-- depends: 018_CREATE_CALENDAR

CREATE TABLE chat_conversation (
    id UUID PRIMARY KEY,
    brokerage_id BIGINT NOT NULL,
    owner_user_id BIGINT NOT NULL,
    active_filters JSONB NOT NULL DEFAULT '{}',
    state_version BIGINT NOT NULL DEFAULT 1 CHECK (state_version > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (brokerage_id, owner_user_id),
    UNIQUE (brokerage_id, id),
    FOREIGN KEY (brokerage_id, owner_user_id) REFERENCES app_user (brokerage_id, id)
);
CREATE TABLE chat_request (
    id UUID PRIMARY KEY,
    brokerage_id BIGINT NOT NULL,
    conversation_id UUID NOT NULL,
    client_request_id UUID NOT NULL,
    fingerprint VARCHAR(64) NOT NULL,
    status VARCHAR(20) NOT NULL CHECK (status IN ('ACCEPTED','RUNNING','COMPLETED','FAILED','CANCELLED','INTERRUPTED')),
    stage VARCHAR(30) NOT NULL DEFAULT 'accepted',
    revision BIGINT NOT NULL DEFAULT 1 CHECK (revision > 0),
    search_filters JSONB,
    diagnostics JSONB NOT NULL DEFAULT '{}',
    context_snapshot JSONB NOT NULL DEFAULT '{}',
    owner_instance_id UUID NOT NULL,
    heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deadline_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    failure_code VARCHAR(60),
    UNIQUE (brokerage_id, conversation_id, id),
    UNIQUE (conversation_id, client_request_id),
    FOREIGN KEY (brokerage_id, conversation_id) REFERENCES chat_conversation (brokerage_id, id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX uq_chat_request_active ON chat_request (conversation_id)
    WHERE status IN ('ACCEPTED','RUNNING');
CREATE INDEX idx_chat_request_recovery ON chat_request (heartbeat_at, deadline_at)
    WHERE status IN ('ACCEPTED','RUNNING');
CREATE TABLE chat_message (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id BIGINT NOT NULL,
    conversation_id UUID NOT NULL,
    request_id UUID NOT NULL,
    sequence_no BIGINT NOT NULL CHECK (sequence_no > 0),
    role VARCHAR(10) NOT NULL CHECK (role IN ('user','assistant')),
    content TEXT NOT NULL,
    payload_version INTEGER NOT NULL DEFAULT 1 CHECK (payload_version > 0),
    result_payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (conversation_id, sequence_no),
    UNIQUE (request_id, role),
    FOREIGN KEY (brokerage_id, conversation_id, request_id) REFERENCES chat_request (brokerage_id, conversation_id, id) ON DELETE CASCADE
);
COMMENT ON TABLE chat_conversation IS 'F4 사용자별 한 개의 대화. 작성자만 조회·전체 물리 삭제한다.';
COMMENT ON TABLE chat_request IS 'SSE 연결과 독립적인 챗봇 실행의 최종·현재 상태. 이벤트 재생 로그가 아니다.';
COMMENT ON TABLE chat_message IS '대화의 질문·검증된 최종 답변. 판정 감사 이력과 별도로 삭제한다.';
COMMENT ON COLUMN chat_conversation.id IS '고유 식별자.';
COMMENT ON COLUMN chat_conversation.brokerage_id IS '소유 중개사무소.';
COMMENT ON COLUMN chat_conversation.owner_user_id IS '대화 작성자.';
COMMENT ON COLUMN chat_conversation.active_filters IS '검증된 현재 검색 조건.';
COMMENT ON COLUMN chat_conversation.state_version IS '검색 조건 낙관적 잠금 버전.';
COMMENT ON COLUMN chat_conversation.created_at IS '생성 시각.';
COMMENT ON COLUMN chat_conversation.updated_at IS '변경 시각.';
COMMENT ON COLUMN chat_request.id IS '고유 식별자.';
COMMENT ON COLUMN chat_request.brokerage_id IS '소유 중개사무소.';
COMMENT ON COLUMN chat_request.conversation_id IS '소유 대화.';
COMMENT ON COLUMN chat_request.client_request_id IS '재전송 중복 방지 키.';
COMMENT ON COLUMN chat_request.fingerprint IS '접수 질문·참조·조건 버전 SHA-256.';
COMMENT ON COLUMN chat_request.status IS '실행 상태. 중단은 수동 재시도한다.';
COMMENT ON COLUMN chat_request.stage IS '안전한 공개 진행 단계.';
COMMENT ON COLUMN chat_request.revision IS 'snapshot 중복 제거 버전.';
COMMENT ON COLUMN chat_request.diagnostics IS '원문 없는 모델·프롬프트·워크플로 버전 및 사용량·지연 진단.';
COMMENT ON COLUMN chat_request.context_snapshot IS '현재 조건과 완료된 최근 두 턴의 최소 문맥.';
COMMENT ON COLUMN chat_request.owner_instance_id IS '실행 소유 서버 인스턴스.';
COMMENT ON COLUMN chat_request.heartbeat_at IS '최근 서버 생존 확인.';
COMMENT ON COLUMN chat_request.deadline_at IS '실행 종료 제한.';
COMMENT ON COLUMN chat_request.created_at IS '생성 시각.';
COMMENT ON COLUMN chat_request.started_at IS '실행 시작 시각.';
COMMENT ON COLUMN chat_request.completed_at IS '최종 상태 저장 시각.';
COMMENT ON COLUMN chat_request.failure_code IS '원문 없는 공개 실패 코드.';
COMMENT ON COLUMN chat_message.id IS '고유 식별자.';
COMMENT ON COLUMN chat_message.brokerage_id IS '소유 중개사무소.';
COMMENT ON COLUMN chat_message.conversation_id IS '소유 대화.';
COMMENT ON COLUMN chat_message.request_id IS '메시지 소유 실행.';
COMMENT ON COLUMN chat_message.sequence_no IS '대화 내 순서 및 페이지 커서.';
COMMENT ON COLUMN chat_message.role IS '질문 user 또는 답변 assistant.';
COMMENT ON COLUMN chat_message.content IS '사용자 질문 또는 검증된 답변.';
COMMENT ON COLUMN chat_message.payload_version IS '구조화 결과 버전.';
COMMENT ON COLUMN chat_message.result_payload IS '검증된 결과·조건·화면 이동 식별자. 질문은 NULL.';
COMMENT ON COLUMN chat_message.created_at IS '생성 시각.';
COMMENT ON COLUMN chat_request.search_filters IS '현재 검색 중인 Backend 검증 조건. 정규화 전에는 NULL.';
