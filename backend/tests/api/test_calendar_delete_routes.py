"""캘린더 일정 삭제·인증·CSRF 경로의 HTTP 계약 검증.

여기서 확인하는 것은 서비스 동작이 아니라 공개 계약이다. 경로, `row_version` 쿼리 입력,
인증·CSRF 적용, 201·204 응답, 404·409 오류 본문이 대상이다.
"""

from __future__ import annotations

from ledger_fixtures import ledger_client, requires_database
from sqlalchemy import text

from core.config import Config

CALENDAR_EVENTS = "/api/v1/calendar/events"
# HTTP 헤더 값은 ASCII만 담는다. 실제 발급 토큰도 ASCII다.
CSRF_TOKEN = "csrf-contract-test-token"
WRONG_CSRF_TOKEN = "csrf-some-other-token"


@requires_database
def test_event_is_created_and_then_deleted_through_http(config: Config) -> None:
    with ledger_client(config) as (client, _session, _brokerage_id, _user_id):
        created = client.post(
            CALENDAR_EVENTS, json={"title": "삭제 검증 일정", "event_date": "2026-09-20"}
        )

        assert created.status_code == 201, created.text
        body = created.json()
        event_id = body["id"]

        deleted = client.delete(
            f"{CALENDAR_EVENTS}/{event_id}", params={"row_version": body["row_version"]}
        )

        assert deleted.status_code == 204
        assert deleted.content == b""

        listed = client.get(
            CALENDAR_EVENTS, params={"from_date": "2026-09-01", "to_date": "2026-09-30"}
        ).json()
        assert all(item["id"] != event_id for item in listed["items"])
        assert (
            client.patch(
                f"{CALENDAR_EVENTS}/{event_id}", json={"row_version": body["row_version"]}
            ).status_code
            == 404
        )


@requires_database
def test_delete_rejects_a_stale_row_version(config: Config) -> None:
    with ledger_client(config) as (client, session, _brokerage_id, _user_id):
        created = client.post(
            CALENDAR_EVENTS, json={"title": "버전 삭제 검증", "event_date": "2026-09-21"}
        ).json()
        session.execute(
            text("UPDATE calendar_event SET row_version = row_version + 1 WHERE id = :i"),
            {"i": created["id"]},
        )
        session.commit()

        response = client.delete(
            f"{CALENDAR_EVENTS}/{created['id']}", params={"row_version": created["row_version"]}
        )

        assert response.status_code == 409
        assert response.json()["code"] == "ROW_VERSION_CONFLICT"


@requires_database
def test_delete_requires_the_row_version_query(config: Config) -> None:
    with ledger_client(config) as (client, _session, _brokerage_id, _user_id):
        created = client.post(
            CALENDAR_EVENTS, json={"title": "쿼리 검증 일정", "event_date": "2026-09-22"}
        ).json()

        assert client.delete(f"{CALENDAR_EVENTS}/{created['id']}").status_code == 422
        assert (
            client.delete(
                f"{CALENDAR_EVENTS}/{created['id']}", params={"row_version": 0}
            ).status_code
            == 422
        )


@requires_database
def test_delete_routes_reject_an_unauthenticated_caller(config: Config) -> None:
    with ledger_client(config, authenticate=False) as (client, _session, _brokerage_id, _user_id):
        response = client.delete(f"{CALENDAR_EVENTS}/1", params={"row_version": 1})

        assert response.status_code == 401
        assert response.json()["code"] == "UNAUTHENTICATED"


@requires_database
def test_write_routes_require_a_matching_csrf_token(config: Config) -> None:
    with ledger_client(config, csrf_token=CSRF_TOKEN) as (
        client,
        _session,
        _brokerage_id,
        _user_id,
    ):
        missing = client.post(
            CALENDAR_EVENTS, json={"title": "CSRF 일정", "event_date": "2026-09-23"}
        )
        assert missing.status_code == 403
        assert missing.json()["code"] == "INVALID_CSRF_TOKEN"

        wrong = client.post(
            CALENDAR_EVENTS,
            json={"title": "CSRF 일정", "event_date": "2026-09-23"},
            headers={"X-CSRF-Token": WRONG_CSRF_TOKEN},
        )
        assert wrong.status_code == 403

        accepted = client.post(
            CALENDAR_EVENTS,
            json={"title": "CSRF 일정", "event_date": "2026-09-23"},
            headers={"X-CSRF-Token": CSRF_TOKEN},
        )
        assert accepted.status_code == 201


@requires_database
def test_deleting_another_brokerage_event_is_reported_as_not_found(config: Config) -> None:
    with ledger_client(config) as (client, session, _brokerage_id, _user_id):
        other_brokerage_id = session.execute(
            text("INSERT INTO brokerage (name) VALUES ('남의 사무소') RETURNING id")
        ).scalar_one()
        other_event_id = session.execute(
            text(
                "INSERT INTO calendar_event (brokerage_id, title, event_date)"
                " VALUES (:b, '남의 일정', '2026-09-24') RETURNING id"
            ),
            {"b": other_brokerage_id},
        ).scalar_one()
        session.commit()

        response = client.delete(f"{CALENDAR_EVENTS}/{other_event_id}", params={"row_version": 1})

        assert response.status_code == 404
        assert response.json()["code"] == "NOT_FOUND"
