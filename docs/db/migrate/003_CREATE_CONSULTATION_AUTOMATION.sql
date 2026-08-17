-- PostgreSQL 15+
-- 음성 전사, 필드 제안, 사용자 승인 전 임시 상태
-- depends: 002_CREATE_PROPERTY_LEDGER


CREATE TABLE ledger_draft (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id        BIGINT NOT NULL,
    ledger_type         VARCHAR(20) NOT NULL,
    status              VARCHAR(20) NOT NULL DEFAULT 'DRAFT',
    source_type         VARCHAR(20) NOT NULL DEFAULT 'HUMAN',
    target_unit_id      BIGINT,
    target_listing_id   BIGINT,
    target_requirement_id BIGINT,
    final_unit_id       BIGINT,
    final_listing_id    BIGINT,
    final_requirement_id BIGINT,
    draft_payload       JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by          BIGINT NOT NULL,
    last_saved_by       BIGINT,
    expires_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    row_version         BIGINT NOT NULL DEFAULT 1,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_ledger_draft_brokerage
        FOREIGN KEY (brokerage_id)
        REFERENCES brokerage (id),
    CONSTRAINT fk_ledger_draft_target_unit
        FOREIGN KEY (brokerage_id, target_unit_id)
        REFERENCES property_unit (brokerage_id, id),
    CONSTRAINT fk_ledger_draft_target_listing
        FOREIGN KEY (brokerage_id, target_listing_id)
        REFERENCES property_listing (brokerage_id, id),
    CONSTRAINT fk_ledger_draft_target_requirement
        FOREIGN KEY (brokerage_id, target_requirement_id)
        REFERENCES property_requirement (brokerage_id, id),
    CONSTRAINT fk_ledger_draft_final_unit
        FOREIGN KEY (brokerage_id, final_unit_id)
        REFERENCES property_unit (brokerage_id, id),
    CONSTRAINT fk_ledger_draft_final_listing
        FOREIGN KEY (brokerage_id, final_listing_id)
        REFERENCES property_listing (brokerage_id, id),
    CONSTRAINT fk_ledger_draft_final_requirement
        FOREIGN KEY (brokerage_id, final_requirement_id)
        REFERENCES property_requirement (brokerage_id, id),
    CONSTRAINT fk_ledger_draft_created_by
        FOREIGN KEY (brokerage_id, created_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT fk_ledger_draft_last_saved_by
        FOREIGN KEY (brokerage_id, last_saved_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_ledger_draft_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE INDEX idx_ledger_draft_user_status
    ON ledger_draft (brokerage_id, created_by, status, updated_at DESC);

CREATE TABLE consultation_transcription_job (
    id                          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id                BIGINT NOT NULL,
    request_id                  UUID NOT NULL,
    ledger_draft_id             BIGINT NOT NULL,
    input_mode                  VARCHAR(20) NOT NULL DEFAULT 'FILE_UPLOAD',
    audio_object_key            TEXT,
    audio_content_type          VARCHAR(120),
    audio_size_bytes            BIGINT,
    audio_sha256                VARCHAR(64),
    status                      VARCHAR(30) NOT NULL DEFAULT 'DRAFT',
    transcription_model_config_id BIGINT,
    analysis_model_config_id    BIGINT,
    transcription_model_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    analysis_model_snapshot     JSONB NOT NULL DEFAULT '{}'::jsonb,
    prompt_version              VARCHAR(100),
    parser_version              VARCHAR(100),
    transcribed_text            TEXT,
    consultation_type           VARCHAR(30),
    ledger_match_result         VARCHAR(20) NOT NULL DEFAULT 'UNKNOWN',
    analysis_summary            JSONB NOT NULL DEFAULT '{}'::jsonb,
    retry_count                 INTEGER NOT NULL DEFAULT 0,
    failed_stage                VARCHAR(40),
    failure_code                VARCHAR(80),
    failure_message             TEXT,
    started_at                  TIMESTAMPTZ,
    transcribed_at              TIMESTAMPTZ,
    analyzed_at                 TIMESTAMPTZ,
    approved_by                 BIGINT,
    approved_at                 TIMESTAMPTZ,
    ledger_saved_at             TIMESTAMPTZ,
    retention_until             TIMESTAMPTZ,
    audio_purged_at             TIMESTAMPTZ,
    transcribed_text_purged_at  TIMESTAMPTZ,
    created_by                  BIGINT NOT NULL,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_transcription_job_draft
        FOREIGN KEY (brokerage_id, ledger_draft_id)
        REFERENCES ledger_draft (brokerage_id, id),
    CONSTRAINT fk_transcription_job_stt_model
        FOREIGN KEY (brokerage_id, transcription_model_config_id)
        REFERENCES ai_model_config (brokerage_id, id),
    CONSTRAINT fk_transcription_job_analysis_model
        FOREIGN KEY (brokerage_id, analysis_model_config_id)
        REFERENCES ai_model_config (brokerage_id, id),
    CONSTRAINT fk_transcription_job_approved_by
        FOREIGN KEY (brokerage_id, approved_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT fk_transcription_job_created_by
        FOREIGN KEY (brokerage_id, created_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_transcription_job_request
        UNIQUE (brokerage_id, request_id),
    CONSTRAINT uq_transcription_job_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE INDEX idx_transcription_job_status
    ON consultation_transcription_job (
        brokerage_id,
        status,
        created_at DESC
    );

CREATE INDEX idx_transcription_job_draft
    ON consultation_transcription_job (
        brokerage_id,
        ledger_draft_id,
        created_at DESC
    );

CREATE TABLE transcription_field_proposal (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id            BIGINT NOT NULL,
    transcription_job_id    BIGINT NOT NULL,
    target_entity           VARCHAR(30) NOT NULL,
    field_name              VARCHAR(120) NOT NULL,
    current_value           JSONB,
    proposed_value          JSONB,
    final_value             JSONB,
    proposal_status         VARCHAR(20) NOT NULL,
    confidence              NUMERIC(6,5),
    evidence_text           TEXT,
    evidence_start_offset   INTEGER,
    evidence_end_offset     INTEGER,
    is_selected             BOOLEAN NOT NULL DEFAULT FALSE,
    applied_by              BIGINT,
    applied_at              TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_field_proposal_job
        FOREIGN KEY (brokerage_id, transcription_job_id)
        REFERENCES consultation_transcription_job (brokerage_id, id),
    CONSTRAINT fk_field_proposal_applied_by
        FOREIGN KEY (brokerage_id, applied_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_field_proposal
        UNIQUE (
            brokerage_id,
            transcription_job_id,
            target_entity,
            field_name
        ),
    CONSTRAINT uq_field_proposal_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE INDEX idx_field_proposal_job
    ON transcription_field_proposal (
        brokerage_id,
        transcription_job_id,
        proposal_status
    );

CREATE TABLE interaction_log_proposal (
    id                          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id                BIGINT NOT NULL,
    transcription_job_id        BIGINT NOT NULL,
    draft_interaction_content   TEXT NOT NULL,
    final_interaction_content   TEXT,
    proposal_status             VARCHAR(20) NOT NULL DEFAULT 'NEEDS_REVIEW',
    is_selected                 BOOLEAN NOT NULL DEFAULT TRUE,
    final_client_interaction_id BIGINT,
    approved_by                 BIGINT,
    approved_at                 TIMESTAMPTZ,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_interaction_log_proposal_job
        FOREIGN KEY (brokerage_id, transcription_job_id)
        REFERENCES consultation_transcription_job (brokerage_id, id),
    CONSTRAINT fk_interaction_log_proposal_interaction
        FOREIGN KEY (brokerage_id, final_client_interaction_id)
        REFERENCES client_interaction (brokerage_id, id),
    CONSTRAINT fk_interaction_log_proposal_approved_by
        FOREIGN KEY (brokerage_id, approved_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_interaction_log_proposal_job
        UNIQUE (brokerage_id, transcription_job_id),
    CONSTRAINT uq_interaction_log_proposal_tenant_id
        UNIQUE (brokerage_id, id)
);


COMMENT ON TABLE ledger_draft IS '사용자 입력과 AI 분석 전후의 미완성 값을 보존하는 임시 레코드. 핵심 원장의 NOT NULL 무결성을 훼손하지 않는다.';
COMMENT ON COLUMN ledger_draft.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN ledger_draft.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN ledger_draft.ledger_type IS '임시 작성 대상 장부 유형.';
COMMENT ON COLUMN ledger_draft.status IS '현재 상태 값. 상태 전이는 서버에서 관리한다.';
COMMENT ON COLUMN ledger_draft.source_type IS '데이터 생성 출처를 구분하는 값.';
COMMENT ON COLUMN ledger_draft.target_unit_id IS '기존 세대 수정 초안의 대상 세대 식별자.';
COMMENT ON COLUMN ledger_draft.target_listing_id IS '기존 매물 수정 초안의 대상 매물 식별자.';
COMMENT ON COLUMN ledger_draft.target_requirement_id IS '수정 대상인 기존 구입장 수요 식별자.';
COMMENT ON COLUMN ledger_draft.final_unit_id IS '확정 저장 후 생성 또는 연결된 세대 식별자.';
COMMENT ON COLUMN ledger_draft.final_listing_id IS '확정 저장 후 생성 또는 연결된 매물 식별자.';
COMMENT ON COLUMN ledger_draft.final_requirement_id IS '임시 저장 완료 후 확정된 구입장 수요 식별자.';
COMMENT ON COLUMN ledger_draft.draft_payload IS '작성 중인 입력값 JSON.';
COMMENT ON COLUMN ledger_draft.created_by IS '생성 사용자 식별자.';
COMMENT ON COLUMN ledger_draft.last_saved_by IS '마지막 임시 저장 사용자 식별자.';
COMMENT ON COLUMN ledger_draft.expires_at IS '임시 초안 만료 예정 시각.';
COMMENT ON COLUMN ledger_draft.completed_at IS '초안 처리 완료 시각.';
COMMENT ON COLUMN ledger_draft.row_version IS '낙관적 동시성 제어용 버전 값. 서버가 증가시킨다.';
COMMENT ON COLUMN ledger_draft.created_at IS '레코드 생성 시각.';
COMMENT ON COLUMN ledger_draft.updated_at IS '레코드 최종 수정 시각. 서버가 갱신한다.';

COMMENT ON TABLE consultation_transcription_job IS '상담 음성 업로드, 전사, 장부 분석, 사용자 검토, 원장 저장과 원문 파기 상태를 추적한다.';
COMMENT ON COLUMN consultation_transcription_job.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN consultation_transcription_job.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN consultation_transcription_job.request_id IS '요청 중복 방지 및 추적용 UUID.';
COMMENT ON COLUMN consultation_transcription_job.ledger_draft_id IS '상담 자동화가 채우는 임시 장부 초안 식별자.';
COMMENT ON COLUMN consultation_transcription_job.input_mode IS '마이크 녹음 또는 파일 업로드 입력 방식.';
COMMENT ON COLUMN consultation_transcription_job.audio_object_key IS '업로드된 상담 음성의 객체 저장소 키.';
COMMENT ON COLUMN consultation_transcription_job.audio_content_type IS '업로드된 상담 음성의 MIME 콘텐츠 유형.';
COMMENT ON COLUMN consultation_transcription_job.audio_size_bytes IS '업로드된 상담 음성의 바이트 크기.';
COMMENT ON COLUMN consultation_transcription_job.audio_sha256 IS '업로드된 상담 음성의 SHA-256 해시.';
COMMENT ON COLUMN consultation_transcription_job.status IS '현재 상태 값. 상태 전이는 서버에서 관리한다.';
COMMENT ON COLUMN consultation_transcription_job.transcription_model_config_id IS '사용한 STT 모델 설정 식별자.';
COMMENT ON COLUMN consultation_transcription_job.analysis_model_config_id IS '사용한 슬롯 필링 모델 설정 식별자.';
COMMENT ON COLUMN consultation_transcription_job.transcription_model_snapshot IS '전사 실행 시점의 모델 설정 스냅샷.';
COMMENT ON COLUMN consultation_transcription_job.analysis_model_snapshot IS '장부 분석 실행 시점의 모델 설정 스냅샷.';
COMMENT ON COLUMN consultation_transcription_job.prompt_version IS '장부 분석에 사용한 프롬프트 버전.';
COMMENT ON COLUMN consultation_transcription_job.parser_version IS '장부 분석 결과 파서 버전.';
COMMENT ON COLUMN consultation_transcription_job.transcribed_text IS 'STT 변환 결과 텍스트.';
COMMENT ON COLUMN consultation_transcription_job.consultation_type IS 'AI가 분류한 상담 유형.';
COMMENT ON COLUMN consultation_transcription_job.ledger_match_result IS '상담 유형과 현재 장부의 일치 판단 값.';
COMMENT ON COLUMN consultation_transcription_job.analysis_summary IS '장부 분석 요약 JSON.';
COMMENT ON COLUMN consultation_transcription_job.retry_count IS '재시도 횟수.';
COMMENT ON COLUMN consultation_transcription_job.failed_stage IS '실패가 발생한 처리 단계.';
COMMENT ON COLUMN consultation_transcription_job.failure_code IS '실패 분류 코드.';
COMMENT ON COLUMN consultation_transcription_job.failure_message IS '실패 상세 메시지.';
COMMENT ON COLUMN consultation_transcription_job.started_at IS '상담 자동화 처리 시작 시각.';
COMMENT ON COLUMN consultation_transcription_job.transcribed_at IS 'STT 완료 시각.';
COMMENT ON COLUMN consultation_transcription_job.analyzed_at IS 'LLM 분석 완료 시각.';
COMMENT ON COLUMN consultation_transcription_job.approved_by IS '승인을 수행한 사용자 식별자.';
COMMENT ON COLUMN consultation_transcription_job.approved_at IS '승인 처리 시각.';
COMMENT ON COLUMN consultation_transcription_job.ledger_saved_at IS '원장 저장 완료 시각.';
COMMENT ON COLUMN consultation_transcription_job.retention_until IS '보관 예정 만료 시각.';
COMMENT ON COLUMN consultation_transcription_job.audio_purged_at IS '상담 음성 원본을 파기한 시각.';
COMMENT ON COLUMN consultation_transcription_job.transcribed_text_purged_at IS '상담 전사 원문을 파기한 시각.';
COMMENT ON COLUMN consultation_transcription_job.created_by IS '생성 사용자 식별자.';
COMMENT ON COLUMN consultation_transcription_job.created_at IS '레코드 생성 시각.';
COMMENT ON COLUMN consultation_transcription_job.updated_at IS '레코드 최종 수정 시각. 서버가 갱신한다.';

COMMENT ON TABLE transcription_field_proposal IS '현재값·AI 제안값·사용자 최종값·근거 문장·충돌 상태를 필드 단위로 보존한다.';
COMMENT ON COLUMN transcription_field_proposal.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN transcription_field_proposal.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN transcription_field_proposal.transcription_job_id IS '소속 상담 전사 작업 식별자.';
COMMENT ON COLUMN transcription_field_proposal.target_entity IS '제안값 적용 대상 엔터티 유형.';
COMMENT ON COLUMN transcription_field_proposal.field_name IS '제안 대상 필드명.';
COMMENT ON COLUMN transcription_field_proposal.current_value IS '현재 장부 값 JSON.';
COMMENT ON COLUMN transcription_field_proposal.proposed_value IS 'AI 제안 값 JSON.';
COMMENT ON COLUMN transcription_field_proposal.final_value IS '사용자 최종 값 JSON.';
COMMENT ON COLUMN transcription_field_proposal.proposal_status IS '제안 처리 상태.';
COMMENT ON COLUMN transcription_field_proposal.confidence IS 'AI 제안 신뢰도.';
COMMENT ON COLUMN transcription_field_proposal.evidence_text IS '제안 근거 STT 문장.';
COMMENT ON COLUMN transcription_field_proposal.evidence_start_offset IS '전사 원문에서 필드 제안 근거가 시작하는 문자 오프셋.';
COMMENT ON COLUMN transcription_field_proposal.evidence_end_offset IS '전사 원문에서 필드 제안 근거가 끝나는 문자 오프셋.';
COMMENT ON COLUMN transcription_field_proposal.is_selected IS '사용자가 반영 대상으로 선택했는지 여부.';
COMMENT ON COLUMN transcription_field_proposal.applied_by IS '제안 반영 사용자 식별자.';
COMMENT ON COLUMN transcription_field_proposal.applied_at IS '제안 반영 시각.';
COMMENT ON COLUMN transcription_field_proposal.created_at IS '레코드 생성 시각.';
COMMENT ON COLUMN transcription_field_proposal.updated_at IS '레코드 최종 수정 시각. 서버가 갱신한다.';

COMMENT ON TABLE interaction_log_proposal IS 'AI가 생성한 상담 로그 초안. 승인된 경우 자동화 주체를 표시한 상담 로그와 연결한다.';
COMMENT ON COLUMN interaction_log_proposal.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN interaction_log_proposal.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN interaction_log_proposal.transcription_job_id IS '소속 상담 전사 작업 식별자.';
COMMENT ON COLUMN interaction_log_proposal.draft_interaction_content IS 'AI가 생성한 상담 로그 초안.';
COMMENT ON COLUMN interaction_log_proposal.final_interaction_content IS '사용자가 확정한 상담 로그 본문.';
COMMENT ON COLUMN interaction_log_proposal.proposal_status IS '로그 제안 처리 상태.';
COMMENT ON COLUMN interaction_log_proposal.is_selected IS '로그 반영 선택 여부.';
COMMENT ON COLUMN interaction_log_proposal.final_client_interaction_id IS '확정 후 생성된 상담 로그 식별자.';
COMMENT ON COLUMN interaction_log_proposal.approved_by IS '승인을 수행한 사용자 식별자.';
COMMENT ON COLUMN interaction_log_proposal.approved_at IS '승인 처리 시각.';
COMMENT ON COLUMN interaction_log_proposal.created_at IS '레코드 생성 시각.';
COMMENT ON COLUMN interaction_log_proposal.updated_at IS '레코드 최종 수정 시각. 서버가 갱신한다.';
