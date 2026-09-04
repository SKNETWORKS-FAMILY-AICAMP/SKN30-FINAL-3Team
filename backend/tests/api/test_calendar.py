"""캘린더 일정 CRUD와 범위 조회 검증.

일정 저장은 F4가 소유한다. Time Keeper가 장부에서 계산해 읽는 일정과는 저장소가 다르므로
여기서는 `calendar_event` 테이블에 대한 쓰기와 날짜 범위 조회만 다룬다.
"""

from __future__ import annotations

from ledger_fixtures import ledger_client, requires_database
from sqlalchemy import text

from core.config import Config

CALENDAR_EVENTS = "/api/v1/calendar/events"


@requires_database
def test_event_is_created_and_appears_in_range(config: Config) -> None:
    with ledger_client(config) as (client, _session, _brokerage_id, user_id):
        created = client.post(
            CALENDAR_EVENTS,
            json={"title": "임장 방문", "category": "임장", "event_date": "2026-09-10"},
        )

        assert created.status_code == 201, created.text
        body = created.json()
        assert body["title"] == "임장 방문"
        assert body["category"] == "임장"
        assert body["event_date"] == "2026-09-10"
        assert body["created_by"] == user_id
        assert body["row_version"] == 1

        listed = client.get(
            CALENDAR_EVENTS, params={"from_date": "2026-09-01", "to_date": "2026-09-30"}
        )
        assert listed.status_code == 200
        page = listed.json()
        assert page["from_date"] == "2026-09-01"
        assert page["to_date"] == "2026-09-30"
        assert any(item["id"] == body["id"] for item in page["items"])


@requires_database
def test_event_outside_the_range_is_not_returned(config: Config) -> None:
    with ledger_client(config) as (client, _session, _brokerage_id, _user_id):
        created = client.post(
            CALENDAR_EVENTS, json={"title": "다음 달 일정", "event_date": "2026-10-15"}
        ).json()

        listed = client.get(
            CALENDAR_EVENTS, params={"from_date": "2026-09-01", "to_date": "2026-09-30"}
        ).json()

        assert all(item["id"] != created["id"] for item in listed["items"])


@requires_database
def test_default_category_is_etc(config: Config) -> None:
    with ledger_client(config) as (client, _session, _brokerage_id, _user_id):
        created = client.post(
            CALENDAR_EVENTS, json={"title": "종류 없는 일정", "event_date": "2026-09-11"}
        )

        assert created.status_code == 201, created.text
        assert created.json()["category"] == "ETC"


@requires_database
def test_end_time_before_start_time_is_rejected(config: Config) -> None:
    with ledger_client(config) as (client, _session, _brokerage_id, _user_id):
        response = client.post(
            CALENDAR_EVENTS,
            json={
                "title": "시간 역전 일정",
                "event_date": "2026-09-11",
                "start_time": "14:00:00",
                "end_time": "13:00:00",
            },
        )

        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_FAILED"


@requires_database
def test_range_query_rejects_to_before_from(config: Config) -> None:
    with ledger_client(config) as (client, _session, _brokerage_id, _user_id):
        response = client.get(
            CALENDAR_EVENTS, params={"from_date": "2026-09-30", "to_date": "2026-09-01"}
        )

        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_FAILED"


@requires_database
def test_update_changes_only_the_given_fields(config: Config) -> None:
    with ledger_client(config) as (client, _session, _brokerage_id, _user_id):
        created = client.post(
            CALENDAR_EVENTS,
            json={"title": "원래 제목", "event_date": "2026-09-12", "location": "본사"},
        ).json()

        patched = client.patch(
            f"{CALENDAR_EVENTS}/{created['id']}",
            json={"row_version": created["row_version"], "title": "바뀐 제목"},
        )

        assert patched.status_code == 200, patched.text
        body = patched.json()
        assert body["title"] == "바뀐 제목"
        assert body["location"] == "본사"
        assert body["row_version"] == 2


@requires_database
def test_update_with_no_actual_change_does_not_bump_row_version(config: Config) -> None:
    with ledger_client(config) as (client, _session, _brokerage_id, _user_id):
        created = client.post(
            CALENDAR_EVENTS, json={"title": "그대로", "event_date": "2026-09-12"}
        ).json()

        patched = client.patch(
            f"{CALENDAR_EVENTS}/{created['id']}",
            json={"row_version": created["row_version"], "title": "그대로"},
        )

        assert patched.status_code == 200, patched.text
        assert patched.json()["row_version"] == created["row_version"]


@requires_database
def test_update_rejects_a_stale_row_version(config: Config) -> None:
    with ledger_client(config) as (client, session, _brokerage_id, _user_id):
        created = client.post(
            CALENDAR_EVENTS, json={"title": "버전 검증", "event_date": "2026-09-12"}
        ).json()
        session.execute(
            text("UPDATE calendar_event SET row_version = row_version + 1 WHERE id = :i"),
            {"i": created["id"]},
        )
        session.commit()

        response = client.patch(
            f"{CALENDAR_EVENTS}/{created['id']}",
            json={"row_version": created["row_version"], "title": "낡은 버전으로 수정"},
        )

        assert response.status_code == 409
        assert response.json()["code"] == "ROW_VERSION_CONFLICT"


@requires_database
def test_another_brokerage_event_is_not_returned(config: Config) -> None:
    with ledger_client(config) as (client, session, _brokerage_id, _user_id):
        other_brokerage_id = session.execute(
            text("INSERT INTO brokerage (name) VALUES ('남의 사무소') RETURNING id")
        ).scalar_one()
        session.execute(
            text(
                "INSERT INTO calendar_event (brokerage_id, title, event_date)"
                " VALUES (:b, '남의 일정', '2026-09-15')"
            ),
            {"b": other_brokerage_id},
        )
        session.commit()

        listed = client.get(
            CALENDAR_EVENTS, params={"from_date": "2026-09-01", "to_date": "2026-09-30"}
        ).json()

        assert all(item["title"] != "남의 일정" for item in listed["items"])
