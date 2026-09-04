-- PostgreSQL 15+
-- 캘린더 화면에서 사용자가 직접 추가하는 일정
-- depends: 017_ALTER_PROPERTY_LEDGER_AGENDA_INDEX


-- 일정·할 일 브리핑이 이미 조회하는 장부 파생 일정(임대차 만기, 재연락 기한 등)은 이 테이블에
-- 넣지 않는다. 그 값들은 여전히 property_unit / property_listing / property_requirement의
-- 날짜 컬럼에서 매번 계산해 읽는 조회 전용 값이다. 이 테이블은 오직 사용자가 캘린더 화면에서
-- 직접 만든 일정만 담는다. 장부 필드를 직접 고치지 않는다는 원칙을 지키려면 저장은 분리해야
-- 한다. 다만 "다가오는 일정" 목록은 두 출처를 함께 읽어 하나로 보여준다 — 저장이 분리된 것이지
-- 사용자에게 보이는 목록까지 나뉘는 것은 아니다.
--
-- 장부(세대·매물·손님)와 연결하는 컬럼은 아직 두지 않는다. 지금 요청 범위가 요구하지 않고,
-- 필요해지면 다음 번호의 ALTER migration으로 확장할 수 있다.
CREATE TABLE calendar_event (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id    BIGINT NOT NULL,
    title           VARCHAR(200) NOT NULL,
    category        VARCHAR(30) NOT NULL DEFAULT 'ETC',
    event_date      DATE NOT NULL,
    start_time      TIME,
    end_time        TIME,
    location        VARCHAR(200),
    memo            TEXT,
    created_by      BIGINT,
    row_version     BIGINT NOT NULL DEFAULT 1,
    is_deleted      BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_calendar_event_brokerage
        FOREIGN KEY (brokerage_id)
        REFERENCES brokerage (id),
    CONSTRAINT fk_calendar_event_created_by
        FOREIGN KEY (brokerage_id, created_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_calendar_event_tenant_id
        UNIQUE (brokerage_id, id),
    CONSTRAINT ck_calendar_event_time_range
        CHECK (
            start_time IS NULL
            OR end_time IS NULL
            OR end_time >= start_time
        )
);

-- 월간 뷰가 브로커리지 안에서 날짜 범위로 조회하는 유일한 경로.
CREATE INDEX idx_calendar_event_date
    ON calendar_event (brokerage_id, event_date)
    WHERE is_deleted = FALSE;


COMMENT ON TABLE calendar_event IS '캘린더 화면에서 사용자가 직접 추가·관리하는 일정. Time Keeper가 장부에서 계산해 읽는 일정과는 별개다.';
COMMENT ON COLUMN calendar_event.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN calendar_event.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN calendar_event.title IS '일정 제목.';
COMMENT ON COLUMN calendar_event.category IS '일정 종류. 고정 열거형이 아니며 화면이 모르는 값도 그대로 표시한다.';
COMMENT ON COLUMN calendar_event.event_date IS '일정 날짜.';
COMMENT ON COLUMN calendar_event.start_time IS '시작 시각. 종일 일정이면 NULL.';
COMMENT ON COLUMN calendar_event.end_time IS '종료 시각. start_time 이 있을 때만 의미가 있다.';
COMMENT ON COLUMN calendar_event.location IS '장소.';
COMMENT ON COLUMN calendar_event.memo IS '메모.';
COMMENT ON COLUMN calendar_event.created_by IS '일정을 만든 사용자. 탈퇴·비활성화된 사용자도 있을 수 있어 NULL을 허용한다.';
COMMENT ON COLUMN calendar_event.row_version IS '낙관적 잠금 버전.';
COMMENT ON COLUMN calendar_event.is_deleted IS '소프트 삭제 여부.';
COMMENT ON COLUMN calendar_event.deleted_at IS '소프트 삭제 시각.';
COMMENT ON COLUMN calendar_event.created_at IS '레코드 생성 시각.';
COMMENT ON COLUMN calendar_event.updated_at IS '레코드 마지막 수정 시각.';
