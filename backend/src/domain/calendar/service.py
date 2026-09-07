from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlmodel import Session

from core.errors import NotFoundError, RowVersionConflictError, ValidationError
from domain.calendar import repository
from domain.calendar.models import CalendarEvent

#: 한 번에 조회할 수 있는 최대 날짜 범위. 월간 뷰가 실수로 몇 년 치를 한 번에 부르지 못하게 막는다.
MAX_RANGE_DAYS = 366


def require_calendar_event(session: Session, brokerage_id: int, event_id: int) -> CalendarEvent:
    found = repository.find_calendar_event(session, brokerage_id, event_id)
    if found is None:
        raise NotFoundError("calendar event is not found")
    return found


def list_events_in_range(
    session: Session, brokerage_id: int, start: date, end: date
) -> list[CalendarEvent]:
    if end < start:
        raise ValidationError("to must not be before from")
    if (end - start).days > MAX_RANGE_DAYS:
        raise ValidationError(f"range must not exceed {MAX_RANGE_DAYS} days")
    return repository.list_calendar_events_in_range(session, brokerage_id, start, end)


def validate_time_range(start_time: Any, end_time: Any) -> None:
    if start_time is not None and end_time is not None and end_time < start_time:
        raise ValidationError("end_time must not be before start_time")


def create_calendar_event(
    session: Session, brokerage_id: int, created_by: int, payload: dict[str, Any]
) -> int:
    validate_time_range(payload.get("start_time"), payload.get("end_time"))
    event = CalendarEvent(brokerage_id=brokerage_id, created_by=created_by, **payload)
    session.add(event)
    session.flush()
    session.commit()
    return event.id or 0


def changed_columns(current: Any, payload: dict[str, Any]) -> set[str]:
    """부분 수정 요청 중 저장된 값과 실제로 다른 컬럼 이름만 돌려준다."""
    return {key for key, value in payload.items() if getattr(current, key) != value}


def update_calendar_event(
    session: Session, brokerage_id: int, event_id: int, payload: dict[str, Any]
) -> frozenset[str]:
    """일정을 수정하고 실제 변경 필드를 반환한다.

    같은 값을 다시 저장하면 쓰기와 ``row_version`` 증가를 생략한다. 값이 같더라도 요청
    버전이 낡았으면 낙관적 잠금 계약에 따라 충돌로 처리한다.
    """
    expected_row_version = int(payload.pop("row_version"))
    current = repository.find_calendar_event(session, brokerage_id, event_id)
    if current is None:
        raise NotFoundError("calendar event is not found")
    if current.row_version != expected_row_version:
        session.rollback()
        raise RowVersionConflictError()

    start_time = payload.get("start_time", current.start_time)
    end_time = payload.get("end_time", current.end_time)
    validate_time_range(start_time, end_time)

    changed = changed_columns(current, payload)
    if not changed:
        session.commit()
        return frozenset()

    updated = repository.bump_row_version(
        session, brokerage_id, event_id, expected_row_version, payload
    )
    if not updated:
        session.rollback()
        raise RowVersionConflictError()
    session.commit()
    return frozenset(changed)


def delete_calendar_event(
    session: Session, brokerage_id: int, event_id: int, expected_row_version: int
) -> None:
    require_calendar_event(session, brokerage_id, event_id)
    updated = repository.bump_row_version(
        session,
        brokerage_id,
        event_id,
        expected_row_version,
        {"is_deleted": True, "deleted_at": datetime.now(UTC)},
    )
    if not updated:
        session.rollback()
        raise RowVersionConflictError()
    session.commit()
