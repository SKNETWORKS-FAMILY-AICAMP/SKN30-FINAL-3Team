from __future__ import annotations

from datetime import date, time

from pydantic import BaseModel, Field

from domain.calendar.models import CalendarEvent

MAX_PAGE_SIZE = 500


class CalendarEventResponse(BaseModel):
    id: int
    title: str
    category: str
    event_date: date
    start_time: time | None
    end_time: time | None
    location: str | None
    memo: str | None
    created_by: int | None
    row_version: int

    @classmethod
    def from_domain(cls, row: CalendarEvent) -> CalendarEventResponse:
        return cls(
            id=row.id or 0,
            title=row.title,
            category=row.category,
            event_date=row.event_date,
            start_time=row.start_time,
            end_time=row.end_time,
            location=row.location,
            memo=row.memo,
            created_by=row.created_by,
            row_version=row.row_version,
        )


class CalendarEventCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    category: str = Field(default="ETC", max_length=30)
    event_date: date
    start_time: time | None = None
    end_time: time | None = None
    location: str | None = Field(default=None, max_length=200)
    memo: str | None = None


class CalendarEventUpdateRequest(BaseModel):
    row_version: int
    title: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = Field(default=None, max_length=30)
    event_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    location: str | None = Field(default=None, max_length=200)
    memo: str | None = None


class CalendarEventListResponse(BaseModel):
    items: list[CalendarEventResponse]
    from_date: date
    to_date: date
