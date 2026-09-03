"""Time Keeper 일정·할 일 조회 API.

장부에 날짜가 적혀 있는 일정과 주기 규칙으로 만드는 할 일이 하나의 목록으로 합쳐지는지,
창 밖의 대상이 빠지는지, 연락할 인물이 행마다 실리는지를 실제 PostgreSQL에서 확인한다.
"""

from __future__ import annotations

from datetime import date, timedelta

from ledger_fixtures import create_complex, create_unit, ledger_client, requires_database
from sqlalchemy import text
from sqlmodel import Session

from core.config import Config
from domain.time_keeper.models import today_in_business_timezone

TODAY = today_in_business_timezone()
AGENDA = "/api/v1/time-keeper/agenda"


def in_days(days: int) -> str:
    return (TODAY + timedelta(days=days)).isoformat()


def create_consented_party(session: Session, brokerage_id: int, user_id: int, name: str) -> int:
    return session.execute(
        text(
            "INSERT INTO party (brokerage_id, party_type, name, privacy_consent_at,"
            " privacy_consent_by)"
            " VALUES (:b, 'PERSON', :n, now(), :u) RETURNING id"
        ),
        {"b": brokerage_id, "n": name, "u": user_id},
    ).scalar_one()


def create_requirement(client, party_id: int, **overrides: object) -> int:
    payload: dict[str, object] = {"party_id": party_id, "demand_type": "매수"}
    payload.update(overrides)
    response = client.post("/api/v1/property-requirements", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["requirement"]["id"]


def set_last_contact(session: Session, table: str, row_id: int, days_ago: int) -> None:
    """마지막 접촉 시각을 직접 옮긴다. 장부 API로는 과거 시각을 지정할 수 없다."""
    session.execute(
        text(f"UPDATE {table} SET last_contact_at = :moment WHERE id = :id"),  # noqa: S608
        {"moment": f"{(TODAY - timedelta(days=days_ago)).isoformat()} 12:00:00+09", "id": row_id},
    )


def categories(body: dict) -> list[str]:
    return [item["category"] for item in body["items"]]


@requires_database
def test_merges_stored_dates_and_rule_tasks_into_one_soonest_first_list(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, user_id):
        complex_id = create_complex(client, session, brokerage_id, "일정단지")
        create_unit(client, complex_id, unit_number="101", tenancy_expiry_date=in_days(40))
        party_id = create_consented_party(session, brokerage_id, user_id, "일정 손님")
        requirement_id = create_requirement(
            client,
            party_id,
            current_tenancy_expiry_date=in_days(10),
            request_expiry_date=in_days(80),
            desired_move_in_date=in_days(25),
        )
        # 20일 전 접촉 + 재연락 주기 30일 → 열흘 뒤가 재연락 기한이다.
        set_last_contact(session, "property_requirement", requirement_id, 20)

        body = client.get(AGENDA).json()

        assert body["total"] == 5
        assert categories(body) == [
            "CLIENT_RECONTACT",
            "CLIENT_TENANCY_EXPIRY",
            "MOVE_IN",
            "TENANCY_EXPIRY",
            "REQUEST_EXPIRY",
        ]
        assert [item["days_until_due"] for item in body["items"]] == [10, 10, 25, 40, 80]
        assert body["as_of"] == TODAY.isoformat()
        # 해당되는 종류만, 각 1건씩 실린다. 0건인 종류는 아예 나오지 않는다.
        assert body["categories"] == [
            {"category": "CLIENT_RECONTACT", "total": 1},
            {"category": "CLIENT_TENANCY_EXPIRY", "total": 1},
            {"category": "MOVE_IN", "total": 1},
            {"category": "REQUEST_EXPIRY", "total": 1},
            {"category": "TENANCY_EXPIRY", "total": 1},
        ]


@requires_database
def test_categories_only_list_kinds_that_actually_have_something(config: Config) -> None:
    """해당되는 내용이 없는 종류는 응답에 흔적을 남기지 않는다."""
    with ledger_client(config) as (client, session, brokerage_id, _user_id):
        complex_id = create_complex(client, session, brokerage_id, "단일단지")
        create_unit(client, complex_id, unit_number="101", tenancy_expiry_date=in_days(12))
        create_unit(client, complex_id, unit_number="102", tenancy_expiry_date=in_days(20))

        body = client.get(AGENDA).json()

        # 임대차 만기 2건뿐이므로 그 종류 하나만, 두 건 모두 실린다.
        assert body["categories"] == [{"category": "TENANCY_EXPIRY", "total": 2}]
        assert len(body["items"]) == 2
        assert {item["category"] for item in body["items"]} == {"TENANCY_EXPIRY"}


@requires_database
def test_empty_page_reports_no_categories_at_all(config: Config) -> None:
    with ledger_client(config) as (client, _session, _brokerage, _user):
        body = client.get(AGENDA).json()

        assert body["categories"] == []
        assert body["items"] == []


@requires_database
def test_one_busy_kind_does_not_push_the_others_out_of_the_briefing(config: Config) -> None:
    """종류별 상한이 없으면 임박한 한 종류가 지면을 다 먹는다."""
    with ledger_client(config) as (client, session, brokerage_id, user_id):
        complex_id = create_complex(client, session, brokerage_id, "혼잡단지")
        for index in range(5):
            create_unit(
                client,
                complex_id,
                unit_number=f"10{index}",
                tenancy_expiry_date=in_days(index + 1),
            )
        party_id = create_consented_party(session, brokerage_id, user_id, "밀린 손님")
        create_requirement(client, party_id, desired_move_in_date=in_days(60))

        body = client.get(AGENDA).json()

        # 전체로는 6건이지만 만기는 상한 3건까지만 실리고, 뒤에 있던 입주일도 자리를 얻는다.
        assert body["total"] == 6
        assert body["per_category_limit"] == 3
        assert categories(body) == [
            "TENANCY_EXPIRY",
            "TENANCY_EXPIRY",
            "TENANCY_EXPIRY",
            "MOVE_IN",
        ]
        # 잘린 나머지는 종류별 총계와 실린 건수의 차이로 드러난다.
        assert body["categories"] == [
            {"category": "MOVE_IN", "total": 1},
            {"category": "TENANCY_EXPIRY", "total": 5},
        ]


@requires_database
def test_recontact_is_derived_from_the_last_contact_and_the_configured_period(
    config: Config,
) -> None:
    with ledger_client(config) as (client, session, brokerage_id, user_id):
        party_id = create_consented_party(session, brokerage_id, user_id, "뜸한 손님")
        requirement_id = create_requirement(client, party_id)
        set_last_contact(session, "property_requirement", requirement_id, 28)

        # 기본 주기 30일이면 이틀 뒤가 기한이다.
        default_window = client.get(AGENDA).json()
        assert categories(default_window) == ["CLIENT_RECONTACT"]
        assert default_window["items"][0]["days_until_due"] == 2

        # 주기를 7일로 줄이면 21일 전에 기한이 지났으므로 되돌아보는 창(7일) 밖으로 나간다.
        shorter = client.get(AGENDA, params={"recontact_days": 7}).json()
        assert shorter["total"] == 0


@requires_database
def test_listing_revalidation_is_derived_from_the_received_date(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _user_id):
        complex_id = create_complex(client, session, brokerage_id, "재확인단지")
        unit = create_unit(client, complex_id, unit_number="101")
        unit_id = unit["unit"]["id"]
        response = client.post(
            f"/api/v1/property-units/{unit_id}/listings",
            json={"received_at": in_days(-20), "is_sale_available": True},
        )
        assert response.status_code == 201, response.text
        listing_id = response.json()["id"]

        body = client.get(AGENDA).json()

        assert categories(body) == ["LISTING_REVALIDATION"]
        item = body["items"][0]
        # 접수 20일 전 + 재확인 주기 30일 → 열흘 뒤
        assert item["days_until_due"] == 10
        assert item["listing_id"] == listing_id
        assert item["unit_id"] == unit_id
        assert item["complex_name"] == "재확인단지"


@requires_database
def test_excludes_targets_beyond_the_requested_window(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _user_id):
        complex_id = create_complex(client, session, brokerage_id, "창단지")
        create_unit(client, complex_id, unit_number="101", tenancy_expiry_date=in_days(30))
        create_unit(client, complex_id, unit_number="102", tenancy_expiry_date=in_days(200))
        # 날짜가 비어 있는 세대는 어떤 창에서도 나오지 않는다.
        create_unit(client, complex_id, unit_number="103")

        body = client.get(AGENDA, params={"within_days": 90}).json()

        assert body["total"] == 1
        assert body["items"][0]["unit_number"] == "101"
        assert body["within_days"] == 90


@requires_database
def test_window_boundary_day_is_included(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _user_id):
        complex_id = create_complex(client, session, brokerage_id, "경계단지")
        create_unit(client, complex_id, unit_number="101", tenancy_expiry_date=in_days(30))
        create_unit(client, complex_id, unit_number="102", tenancy_expiry_date=in_days(31))

        body = client.get(AGENDA, params={"within_days": 30}).json()

        assert [item["unit_number"] for item in body["items"]] == ["101"]


@requires_database
def test_recently_passed_due_date_stays_visible_with_negative_days(config: Config) -> None:
    """어제 지난 기한이 목록에서 사라지면 놓친 건을 다시 만날 자리가 없다."""
    with ledger_client(config) as (client, session, brokerage_id, _user_id):
        complex_id = create_complex(client, session, brokerage_id, "지난단지")
        create_unit(client, complex_id, unit_number="101", tenancy_expiry_date=in_days(-3))
        create_unit(client, complex_id, unit_number="102", tenancy_expiry_date=in_days(-30))

        body = client.get(AGENDA).json()

        assert [item["unit_number"] for item in body["items"]] == ["101"]
        assert body["items"][0]["days_until_due"] == -3
        assert body["overdue_days"] == 7

        without_overdue = client.get(AGENDA, params={"overdue_days": 0}).json()
        assert without_overdue["total"] == 0


@requires_database
def test_closed_requirements_and_withdrawn_listings_are_not_announced(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, user_id):
        active = create_consented_party(session, brokerage_id, user_id, "진행 손님")
        closed = create_consented_party(session, brokerage_id, user_id, "종료 손님")
        create_requirement(client, active, current_tenancy_expiry_date=in_days(20))
        create_requirement(client, closed, current_tenancy_expiry_date=in_days(21), status="CLOSED")

        complex_id = create_complex(client, session, brokerage_id, "종료단지")
        unit = create_unit(client, complex_id, unit_number="101")
        listing = client.post(
            f"/api/v1/property-units/{unit['unit']['id']}/listings",
            json={"received_at": in_days(-20), "status": "CLOSED"},
        )
        assert listing.status_code == 201, listing.text

        body = client.get(AGENDA).json()

        assert body["total"] == 1
        assert body["items"][0]["contacts"][0]["party"]["name"] == "진행 손님"
        assert body["items"][0]["requirement_status"] == "ACTIVE"


@requires_database
def test_unit_rows_carry_current_parties_and_requirement_rows_carry_the_client(
    config: Config,
) -> None:
    with ledger_client(config) as (client, session, brokerage_id, user_id):
        complex_id = create_complex(client, session, brokerage_id, "연락단지")
        create_unit(
            client,
            complex_id,
            unit_number="1503",
            building_number="101",
            tenancy_expiry_date=in_days(15),
            parties=[
                {"role": "LANDLORD", "role_index": 1, "name": "김임대", "phone": "010-1111-2222"},
                {"role": "TENANT", "role_index": 1, "name": "박임차", "phone": "010-3333-4444"},
            ],
        )
        party_id = create_consented_party(session, brokerage_id, user_id, "이손님")
        create_requirement(client, party_id, current_tenancy_expiry_date=in_days(20))

        items = client.get(AGENDA).json()["items"]
        unit_row, requirement_row = items[0], items[1]

        assert unit_row["complex_name"] == "연락단지"
        assert unit_row["building_number"] == "101"
        assert unit_row["unit_number"] == "1503"
        assert unit_row["requirement_id"] is None
        assert [
            (contact["role"], contact["party"]["name"]) for contact in unit_row["contacts"]
        ] == [("LANDLORD", "김임대"), ("TENANT", "박임차")]
        assert unit_row["contacts"][0]["party"]["contacts"][0]["contact_value"] == "010-1111-2222"

        assert requirement_row["unit_id"] is None
        assert requirement_row["demand_type"] == "매수"
        assert requirement_row["contacts"][0]["role"] is None
        assert requirement_row["contacts"][0]["party"]["name"] == "이손님"


@requires_database
def test_pagination_reports_the_total_across_every_source(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, user_id):
        complex_id = create_complex(client, session, brokerage_id, "페이지단지")
        create_unit(client, complex_id, unit_number="101", tenancy_expiry_date=in_days(5))
        create_unit(client, complex_id, unit_number="102", tenancy_expiry_date=in_days(6))
        party_id = create_consented_party(session, brokerage_id, user_id, "페이지 손님")
        create_requirement(client, party_id, current_tenancy_expiry_date=in_days(7))

        first = client.get(AGENDA, params={"limit": 2}).json()
        second = client.get(AGENDA, params={"limit": 2, "offset": 2}).json()

        assert first["total"] == 3
        assert [item["unit_number"] for item in first["items"]] == ["101", "102"]
        assert second["total"] == 3
        assert len(second["items"]) == 1
        assert second["items"][0]["category"] == "CLIENT_TENANCY_EXPIRY"


@requires_database
def test_another_brokerage_agenda_is_not_returned(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _user_id):
        other_brokerage = session.execute(
            text("INSERT INTO brokerage (name) VALUES ('다른 사무소') RETURNING id")
        ).scalar_one()
        other_complex = session.execute(
            text("INSERT INTO property_complex (brokerage_id, name) VALUES (:b, :n) RETURNING id"),
            {"b": other_brokerage, "n": "남의단지"},
        ).scalar_one()
        session.execute(
            text(
                "INSERT INTO property_unit (brokerage_id, complex_id, unit_number,"
                " tenancy_expiry_date) VALUES (:b, :c, '101', :d)"
            ),
            {"b": other_brokerage, "c": other_complex, "d": in_days(10)},
        )

        assert client.get(AGENDA).json()["total"] == 0


@requires_database
def test_agenda_requires_a_session(config: Config) -> None:
    with ledger_client(config, authenticate=False) as (client, _session, _brokerage, _user):
        assert client.get(AGENDA).status_code == 401


@requires_database
def test_arguments_outside_the_supported_range_are_rejected(config: Config) -> None:
    with ledger_client(config) as (client, _session, _brokerage, _user):
        for params in [
            {"within_days": 0},
            {"overdue_days": -1},
            {"recontact_days": 0},
            {"per_category_limit": 0},
        ]:
            assert client.get(AGENDA, params=params).status_code == 422, params


@requires_database
def test_empty_brokerage_returns_an_empty_page(config: Config) -> None:
    with ledger_client(config) as (client, _session, _brokerage, _user):
        body = client.get(AGENDA).json()

        assert body == {
            "items": [],
            "categories": [],
            "total": 0,
            "limit": 50,
            "offset": 0,
            "as_of": TODAY.isoformat(),
            "within_days": 90,
            "overdue_days": 7,
            "per_category_limit": 3,
        }


@requires_database
def test_due_date_is_returned_as_the_stored_calendar_date(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _user_id):
        complex_id = create_complex(client, session, brokerage_id, "날짜단지")
        expiry: date = TODAY + timedelta(days=45)
        create_unit(client, complex_id, unit_number="101", tenancy_expiry_date=expiry.isoformat())

        body = client.get(AGENDA).json()

        assert body["items"][0]["due_date"] == expiry.isoformat()
        assert body["items"][0]["days_until_due"] == 45
