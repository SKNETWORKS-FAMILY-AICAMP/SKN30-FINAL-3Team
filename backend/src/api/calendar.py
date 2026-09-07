from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from api.schemas.calendar import (
    CalendarEventCreateRequest,
    CalendarEventListResponse,
    CalendarEventResponse,
    CalendarEventUpdateRequest,
)
from domain.authentication.dependencies import get_current_user, require_csrf
from domain.authentication.models import CurrentUser
from domain.calendar import service
from domain.session import get_db_session

router = APIRouter(prefix="/calendar", tags=["calendar"])


def changed_fields(payload: Any) -> dict[str, Any]:
    return payload.model_dump(exclude_unset=True)


@router.get("/events", response_model=CalendarEventListResponse)
def list_calendar_events(
    from_date: date = Query(),
    to_date: date = Query(),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> CalendarEventListResponse:
    """``from_date``와 ``to_date`` 사이(양끝 포함)의 사용자 일정을 날짜순으로 조회한다.

    Time Keeper가 장부에서 계산해 읽는 일정과는 별개다. 화면은 두 조회 결과를 합쳐서 보여준다.
    """
    events = service.list_events_in_range(db, user.brokerage_id, from_date, to_date)
    return CalendarEventListResponse(
        items=[CalendarEventResponse.from_domain(event) for event in events],
        from_date=from_date,
        to_date=to_date,
    )


@router.post("/events", response_model=CalendarEventResponse, status_code=201)
def create_calendar_event(
    payload: CalendarEventCreateRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db_session),
    _: None = Depends(require_csrf),
) -> CalendarEventResponse:
    event_id = service.create_calendar_event(
        db, user.brokerage_id, user.id, changed_fields(payload)
    )
    event = service.require_calendar_event(db, user.brokerage_id, event_id)
    return CalendarEventResponse.from_domain(event)


@router.patch("/events/{event_id}", response_model=CalendarEventResponse)
def update_calendar_event(
    event_id: int,
    payload: CalendarEventUpdateRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db_session),
    _: None = Depends(require_csrf),
) -> CalendarEventResponse:
    service.update_calendar_event(db, user.brokerage_id, event_id, changed_fields(payload))
    event = service.require_calendar_event(db, user.brokerage_id, event_id)
    return CalendarEventResponse.from_domain(event)


@router.delete("/events/{event_id}", status_code=204)
def delete_calendar_event(
    event_id: int,
    row_version: int = Query(ge=1),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db_session),
    _: None = Depends(require_csrf),
) -> None:
    service.delete_calendar_event(db, user.brokerage_id, event_id, row_version)
