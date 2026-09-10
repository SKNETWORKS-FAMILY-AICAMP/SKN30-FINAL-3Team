"""사용자가 캘린더에서 만든 일정이 '다가오는 일정'(Time Keeper)에도 함께 뜨는지 확인한다.

캘린더 일정 저장은 F4가 소유하고 장부와는 별개 테이블(``calendar_event``)이지만, 사용자에게는
'다가오는 일정'과 캘린더가 하나로 이어진 목록으로 보여야 한다. 이 파일은 그 통합 지점, 즉
Time Keeper의 union이 캘린더 갈래를 실제로 포함하는지를 실제 PostgreSQL에서 검증한다.
"""

from __future__ import annotations

from datetime import timedelta

from ledger_fixtures import create_complex, create_unit, ledger_client, requires_database
from sqlalchemy import text

from core.config import Config
from domain.time_keeper.models import today_in_business_timezone

TODAY = today_in_business_timezone()
AGENDA = "/api/v1/time-keeper/agenda"
CALENDAR_EVENTS = "/api/v1/calendar/events"


def in_days(days: int) -> str:
    return (TODAY + timedelta(days=days)).isoformat()


@requires_database
def test_calendar_event_appears_in_the_agenda_with_its_own_category(config: Config) -> None:
    with ledger_client(config) as (client, _session, _brokerage_id, user_id):
        created = client.post(
            CALENDAR_EVENTS,
            json={
                "title": "임장 방문",
                "category": "임장",
                "event_date": in_days(15),
                "location": "행복아파트 101동",
            },
        ).json()

        body = client.get(AGENDA).json()

        matches = [item for item in body["items"] if item.get("event_id") == created["id"]]
        assert len(matches) == 1, body
        item = matches[0]
        assert item["category"] == "임장"
        assert item["title"] == "임장 방문"
        assert item["location"] == "행복아파트 101동"
        assert item["days_until_due"] == 15
        assert item["unit_id"] is None
        assert item["listing_id"] is None
        assert item["requirement_id"] is None
        assert item["contacts"] == []
        assert any(c["category"] == "임장" and c["total"] == 1 for c in body["categories"])
        assert item["assigned_user_id"] is None


@requires_database
def test_calendar_event_outside_the_window_is_not_returned(config: Config) -> None:
    with ledger_client(config) as (client, _session, _brokerage_id, _user_id):
        created = client.post(
            CALENDAR_EVENTS, json={"title": "먼 미래 일정", "event_date": in_days(500)}
        ).json()

        body = client.get(AGENDA, params={"within_days": 90}).json()

        assert all(item.get("event_id") != created["id"] for item in body["items"])


@requires_database
def test_calendar_event_sorts_alongside_ledger_dates_by_due_date(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _user_id):
        complex_id = create_complex(client, session, brokerage_id, "정렬단지")
        unit = create_unit(client, complex_id, unit_number="101", tenancy_expiry_date=in_days(20))
        unit_id = unit["unit"]["id"]
        event = client.post(
            CALENDAR_EVENTS, json={"title": "먼저 오는 일정", "event_date": in_days(5)}
        ).json()

        body = client.get(AGENDA).json()

        due_in_order = [item["due_date"] for item in body["items"]]
        event_index = next(
            index for index, item in enumerate(body["items"]) if item.get("event_id") == event["id"]
        )
        unit_index = next(
            index for index, item in enumerate(body["items"]) if item.get("unit_id") == unit_id
        )
        assert event_index < unit_index
        assert due_in_order == sorted(due_in_order)


@requires_database
def test_another_brokerage_calendar_event_is_not_returned(config: Config) -> None:
    with ledger_client(config) as (client, session, _brokerage_id, _user_id):
        other_brokerage_id = session.execute(
            text("INSERT INTO brokerage (name) VALUES ('남의 사무소') RETURNING id")
        ).scalar_one()
        session.execute(
            text(
                "INSERT INTO calendar_event (brokerage_id, title, event_date)"
                " VALUES (:b, '남의 일정', :d)"
            ),
            {"b": other_brokerage_id, "d": in_days(3)},
        )
        session.commit()

        body = client.get(AGENDA).json()

        assert all(item.get("title") != "남의 일정" for item in body["items"])
