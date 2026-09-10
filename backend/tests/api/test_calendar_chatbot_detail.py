from ledger_fixtures import ledger_client, requires_database
from sqlalchemy import text

from core.config import Config


@requires_database
def test_calendar_reference_is_resolved_independently_of_current_month(config: Config) -> None:
    with ledger_client(config) as (client, _, _, _user):
        created = client.post(
            "/api/v1/calendar/events", json={"title": "합성 미래 일정", "event_date": "2027-01-03"}
        )
        assert created.status_code == 201
        event = created.json()
        url = f"/api/v1/calendar/events/{event['id']}"
        assert client.get(url).json() == event
        assert client.delete(url, params={"row_version": event["row_version"]}).status_code == 204
        assert client.get(url).status_code == 404


@requires_database
def test_calendar_reference_does_not_expose_another_brokerage(config: Config) -> None:
    with ledger_client(config) as (client, session, _, _):
        other = session.execute(
            text("INSERT INTO brokerage(name) VALUES ('합성 다른 사무소') RETURNING id")
        ).scalar_one()
        target = session.execute(
            text(
                "INSERT INTO calendar_event(brokerage_id,title,event_date) VALUES "
                "(:b,'합성 타 사무소 일정','2027-01-03') RETURNING id"
            ),
            {"b": other},
        ).scalar_one()
        assert client.get(f"/api/v1/calendar/events/{target}").status_code == 404
