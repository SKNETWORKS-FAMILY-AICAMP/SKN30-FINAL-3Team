---
status: 결정
updated: 2026-09-08
---

# ADR-0032: 캘린더 기능(F4-CAL)을 전체 폐기한다

- 상태: 승인됨
- 결정일: 2026-09-08
- 승인 주체: 프로젝트 요청자
- 대체 범위: [ADR-0025](ADR-0025-calendar-storage-ownership.md)(캘린더 저장 소유권·Time Keeper
  통합)와 [Frontend ADR-008](../../../frontend/references/decisions/ADR-008-calendar-month-grid.md)
  (월간 그리드 구현)을 대체한다.
- 관련 요구사항: [F4 캘린더 (폐기)](../../../../../docs/requirements/f4/calendar.md),
  [F4 Time Keeper](../../../../../docs/requirements/f4/time-keeper.md)
- 관련 계약: [API 계약](../contracts/api.md)
- 관련 DB: `docs/db/migrate/019_DROP_CALENDAR.sql`

## 맥락

사용자가 캘린더(월간 그리드·일정 CRUD, F4-CAL-01~11) 기능 전체를 제거해 달라고 요청했다.
Time Keeper "다가오는 일정"은 그대로 유지하되, 캘린더 화면과 그 저장·API·Time Keeper 통합만
없애 달라는 요청이다. 제거 사유는 대화에서 별도로 확인되지 않았다.

## 결정

1. **화면·API·저장 제거**: `frontend/src/features/calendar/`, `backend/src/domain/calendar/`,
   `backend/src/api/calendar.py`·`schemas/calendar.py`와 관련 테스트를 모두 삭제한다.
   `calendar_event` 테이블은 `019_DROP_CALENDAR.sql`로 제거한다(마지막 단계로만 DROP한다는
   `docs/db/README.md` 규칙에 따라 018을 고치지 않고 새 migration을 추가했다).
2. **Time Keeper 통합 원복**: `GET /time-keeper/agenda`의 캘린더 union 갈래
   (`_calendar_event_members`)와 응답의 `event_id`·`event_row_version`·`title`·`location`
   필드를 뺀다. Time Keeper는 ADR-0025 이전처럼 장부 파생 갈래만 읽는 조회 전용 기능으로
   되돌아간다.
3. **문서 보존**: `docs/requirements/f4/calendar.md`와 ADR-0025는 지우지 않고 상태를
   `폐기`/`대체됨`으로 표시해 과거에 무엇이 구현됐는지 추적할 수 있게 남긴다.

## 결과

- F4가 가졌던 유일한 쓰기 테이블(`calendar_event`)이 사라져 F4-CM-06(F4는 F1 장부를 직접
  고치지 않는다)의 예외가 없어진다. F4는 다시 전 영역이 조회 전용이다.
- "다가오는 일정"의 카테고리 어휘는 장부에서 계산하는 다섯 가지 고정값만 남고, 사용자가 임의
  문자열을 넣는 경로가 없어진다.
- 상단바의 캘린더 진입점(달력 버튼, `F4-MOD-011`)이 사라진다. "다가오는 일정" 버튼만 남는다.
- F2 음성 인식 기반 자동 일정 추가처럼 캘린더 위에서 이어가려던 후속 아이디어는 근거를 잃는다.

## 고려한 대안

- **화면만 숨기고 코드·테이블 유지**: 되돌리기 쉽지만, 사용하지 않는 테이블·라우트·프론트엔드
  코드가 죽은 채로 남아 이후 읽는 사람이 "왜 있는지" 다시 조사해야 한다. 사용자가 명시적으로
  "삭제"를 요청했으므로 채택하지 않았다.
- **calendar_event 테이블은 남기고 코드만 제거**: 데이터가 참조 없이 남아 스키마와 실제 쓰임이
  어긋난다. `docs/db/README.md`의 DROP 규칙이 이런 경우를 위해 있다.
