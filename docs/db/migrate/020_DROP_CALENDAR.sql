-- PostgreSQL 15+
-- 캘린더 기능 폐기에 따른 calendar_event 제거
-- depends: 019_CREATE_CHATBOT


-- 캘린더 화면(F4-CAL)을 통째로 제거하기로 하면서 이 테이블을 쓰는 코드(backend/src/domain/calendar,
-- backend/src/api/calendar.py, frontend/src/features/calendar)와 Time Keeper의 캘린더 갈래
-- 통합을 같은 변경에서 함께 제거했다. 읽기·쓰기 경로가 모두 사라진 뒤의 마지막 단계로 테이블을
-- 지운다. "다가오는 일정" 목록은 장부 파생 갈래만 남고 영향을 받지 않는다.
DROP INDEX IF EXISTS idx_calendar_event_date;
DROP TABLE IF EXISTS calendar_event;
