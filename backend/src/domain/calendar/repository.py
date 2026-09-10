from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, cast

from sqlalchemy import CursorResult, update
from sqlmodel import Session, col, select

from domain.calendar.models import CalendarEvent


def find_calendar_event(session: Session, brokerage_id: int, event_id: int) -> CalendarEvent | None:
    statement = select(CalendarEvent).where(
        col(CalendarEvent.brokerage_id) == brokerage_id,
        col(CalendarEvent.id) == event_id,
        col(CalendarEvent.is_deleted).is_(False),
    )
    return session.execute(statement).scalars().first()


def list_calendar_events_in_range(
    session: Session, brokerage_id: int, start: date, end: date
) -> list[CalendarEvent]:
    """``start``와 ``end`` 를 양끝 포함해 날짜순으로 돌려준다."""
    statement = (
        select(CalendarEvent)
        .where(
            col(CalendarEvent.brokerage_id) == brokerage_id,
            col(CalendarEvent.event_date) >= start,
            col(CalendarEvent.event_date) <= end,
            col(CalendarEvent.is_deleted).is_(False),
        )
        .order_by(
            col(CalendarEvent.event_date),
            col(CalendarEvent.start_time),
            col(CalendarEvent.id),
        )
    )
    return list(session.execute(statement).scalars().all())


def bump_row_version(
    session: Session,
    brokerage_id: int,
    event_id: int,
    expected_row_version: int,
    values: dict[str, Any],
) -> bool:
    """낙관적 잠금 갱신. 버전이 일치할 때만 1행을 수정하고 True를 돌려준다."""
    statement = (
        update(CalendarEvent)
        .where(
            col(CalendarEvent.brokerage_id) == brokerage_id,
            col(CalendarEvent.id) == event_id,
            col(CalendarEvent.row_version) == expected_row_version,
            col(CalendarEvent.is_deleted).is_(False),
        )
        .values(
            **values,
            row_version=CalendarEvent.row_version + 1,
            updated_at=datetime.now(UTC),
        )
    )
    result = cast(CursorResult[Any], session.execute(statement))
    return result.rowcount == 1
