from __future__ import annotations

from ledger_fixtures import create_complex, create_unit, ledger_client, requires_database
from sqlalchemy import text

from core.config import Config


@requires_database
def test_list_returns_units_without_any_listing(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _):
        complex_id = create_complex(client, session, brokerage_id, "전수단지")
        create_unit(client, complex_id, unit_number="101")
        create_unit(client, complex_id, unit_number="102")

        response = client.get("/api/v1/property-units")

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        assert [item["unit_number"] for item in body["items"]] == ["101", "102"]
        assert all(item["current_listing"] is None for item in body["items"])


@requires_database
def test_list_attaches_only_the_most_recently_received_listing(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _):
        complex_id = create_complex(client, session, brokerage_id, "이력단지")
        unit = create_unit(client, complex_id)
        unit_id = unit["unit"]["id"]

        client.post(
            f"/api/v1/property-units/{unit_id}/listings",
            json={"received_at": "2023-05-01", "is_jeonse_available": True},
        )
        client.post(
            f"/api/v1/property-units/{unit_id}/listings",
            json={
                "received_at": "2025-09-01",
                "is_sale_available": True,
                "sale_price": 2_880_000_000,
            },
        )

        body = client.get("/api/v1/property-units").json()
        current = body["items"][0]["current_listing"]

        assert current["received_at"] == "2025-09-01"
        assert current["sale_price"] == 2_880_000_000
        assert body["items"][0]["id"] == unit_id

        detail = client.get(f"/api/v1/property-units/{unit_id}").json()
        assert [listing["received_at"] for listing in detail["listings"]] == [
            "2025-09-01",
            "2023-05-01",
        ]


@requires_database
def test_repeated_filter_values_combine_with_or_and_empty_selects_blank_rows(
    config: Config,
) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _):
        complex_id = create_complex(client, session, brokerage_id, "필터단지")
        create_unit(client, complex_id, unit_number="101", tenancy_status="입주")
        create_unit(client, complex_id, unit_number="102", tenancy_status="경신")
        create_unit(client, complex_id, unit_number="103")

        both = client.get(
            "/api/v1/property-units",
            params=[("tenancy_status", "입주"), ("tenancy_status", "경신")],
        ).json()
        assert both["total"] == 2

        blank = client.get("/api/v1/property-units", params={"tenancy_status": "__EMPTY__"}).json()
        assert blank["total"] == 1
        assert blank["items"][0]["unit_number"] == "103"

        mixed = client.get(
            "/api/v1/property-units",
            params=[("tenancy_status", "입주"), ("tenancy_status", "__EMPTY__")],
        ).json()
        assert mixed["total"] == 2


@requires_database
def test_blank_filter_parameter_is_ignored(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _):
        complex_id = create_complex(client, session, brokerage_id, "빈값단지")
        create_unit(client, complex_id, unit_number="101", tenancy_status="입주")
        create_unit(client, complex_id, unit_number="102")

        response = client.get("/api/v1/property-units", params={"tenancy_status": ""})

        assert response.json()["total"] == 2


@requires_database
def test_column_values_report_counts_including_the_empty_bucket(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _):
        complex_id = create_complex(client, session, brokerage_id, "값목록단지")
        create_unit(client, complex_id, unit_number="101", tenancy_status="입주")
        create_unit(client, complex_id, unit_number="102", tenancy_status="입주")
        create_unit(client, complex_id, unit_number="103")

        body = client.get(
            "/api/v1/property-units/column-values", params={"column": "tenancy_status"}
        ).json()

        assert body["column"] == "tenancy_status"
        assert {item["value"]: item["count"] for item in body["items"]} == {
            "__EMPTY__": 1,
            "입주": 2,
        }


@requires_database
def test_unknown_column_is_rejected(config: Config) -> None:
    with ledger_client(config) as (client, _session, _brokerage_id, _):
        response = client.get("/api/v1/property-units/column-values", params={"column": "memo"})

        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_FAILED"


@requires_database
def test_pagination_reports_total_and_keeps_rows_stable(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _):
        complex_id = create_complex(client, session, brokerage_id, "페이지단지")
        for number in range(1, 6):
            create_unit(client, complex_id, unit_number=f"10{number}")

        first = client.get("/api/v1/property-units", params={"limit": 2, "offset": 0}).json()
        second = client.get("/api/v1/property-units", params={"limit": 2, "offset": 2}).json()

        assert first["total"] == second["total"] == 5
        assert first["limit"] == 2
        assert second["offset"] == 2
        assert [item["unit_number"] for item in first["items"]] == ["101", "102"]
        assert [item["unit_number"] for item in second["items"]] == ["103", "104"]


@requires_database
def test_update_requires_matching_row_version(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _):
        complex_id = create_complex(client, session, brokerage_id, "충돌단지")
        unit = create_unit(client, complex_id)
        unit_id = unit["unit"]["id"]
        row_version = unit["unit"]["row_version"]

        accepted = client.patch(
            f"/api/v1/property-units/{unit_id}",
            json={"row_version": row_version, "memo": "첫 수정"},
        )
        assert accepted.status_code == 200
        assert accepted.json()["unit"]["memo"] == "첫 수정"
        assert accepted.json()["unit"]["row_version"] == row_version + 1

        stale = client.patch(
            f"/api/v1/property-units/{unit_id}",
            json={"row_version": row_version, "memo": "덮어쓰기 시도"},
        )
        assert stale.status_code == 409
        assert stale.json()["code"] == "ROW_VERSION_CONFLICT"

        assert client.get(f"/api/v1/property-units/{unit_id}").json()["unit"]["memo"] == "첫 수정"


@requires_database
def test_unit_of_another_brokerage_is_reported_as_not_found(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _):
        other_brokerage_id = session.execute(
            text("INSERT INTO brokerage (name) VALUES ('다른 사무소') RETURNING id")
        ).scalar_one()
        other_complex_id = create_complex(client, session, other_brokerage_id, "남의단지")
        other_unit_id = session.execute(
            text(
                "INSERT INTO property_unit (brokerage_id, complex_id, unit_number)"
                " VALUES (:b, :c, '999') RETURNING id"
            ),
            {"b": other_brokerage_id, "c": other_complex_id},
        ).scalar_one()

        response = client.get(f"/api/v1/property-units/{other_unit_id}")

        assert response.status_code == 404
        assert response.json()["code"] == "NOT_FOUND"


@requires_database
def test_creating_a_unit_in_another_brokerage_complex_is_rejected(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _):
        other_brokerage_id = session.execute(
            text("INSERT INTO brokerage (name) VALUES ('남의 사무소') RETURNING id")
        ).scalar_one()
        other_complex_id = create_complex(client, session, other_brokerage_id, "남의단지")

        response = client.post(
            "/api/v1/property-units",
            json={"complex_id": other_complex_id, "unit_number": "101"},
        )

        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_FAILED"


@requires_database
def test_integer_filters_accept_numeric_query_values(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, user_id):
        wanted = create_complex(client, session, brokerage_id, "대상단지")
        other = create_complex(client, session, brokerage_id, "제외단지")
        create_unit(client, wanted, unit_number="101", assigned_user_id=user_id)
        create_unit(client, wanted, unit_number="102")
        create_unit(client, other, unit_number="201")

        by_complex = client.get("/api/v1/property-units", params={"complex_id": wanted})
        assert by_complex.status_code == 200, by_complex.text
        assert by_complex.json()["total"] == 2

        by_user = client.get("/api/v1/property-units", params={"assigned_user_id": user_id})
        assert by_user.json()["total"] == 1

        unassigned = client.get("/api/v1/property-units", params={"assigned_user_id": "__EMPTY__"})
        assert unassigned.json()["total"] == 2

        both = client.get(
            "/api/v1/property-units",
            params=[("complex_id", wanted), ("complex_id", other)],
        )
        assert both.json()["total"] == 3


@requires_database
def test_non_numeric_value_for_an_integer_filter_is_rejected(config: Config) -> None:
    with ledger_client(config) as (client, _session, _brokerage_id, _user_id):
        response = client.get("/api/v1/property-units", params={"complex_id": "abc"})

        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_FAILED"


@requires_database
def test_list_carries_the_current_parties_of_each_row(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _):
        complex_id = create_complex(client, session, brokerage_id, "인물단지")
        create_unit(
            client,
            complex_id,
            unit_number="101",
            parties=[
                {"role": "LANDLORD", "role_index": 2, "name": "송경련", "is_co_owner": True},
                {
                    "role": "LANDLORD",
                    "role_index": 1,
                    "name": "박이서",
                    "phone": "010-1111-2222",
                    "is_co_owner": True,
                },
                {"role": "TENANT", "role_index": 1, "name": "김세입", "phone": "010-3333-4444"},
            ],
        )

        response = client.get("/api/v1/property-units")

        assert response.status_code == 200, response.text
        parties = response.json()["items"][0]["parties"]
        assert [(entry["role"], entry["role_index"]) for entry in parties] == [
            ("LANDLORD", 1),
            ("LANDLORD", 2),
            ("TENANT", 1),
        ]
        assert [entry["party"]["name"] for entry in parties] == ["박이서", "송경련", "김세입"]
        assert [entry["is_co_owner"] for entry in parties] == [True, True, False]
        assert [contact["contact_value"] for contact in parties[0]["party"]["contacts"]] == [
            "010-1111-2222"
        ]


@requires_database
def test_list_and_detail_assemble_parties_the_same_way(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _):
        complex_id = create_complex(client, session, brokerage_id, "동일조립단지")
        created = create_unit(
            client,
            complex_id,
            unit_number="102",
            parties=[
                {"role": "LANDLORD", "role_index": 1, "name": "박이서", "phone": "010-1111-2222"},
                {"role": "TENANT", "role_index": 1, "name": "김세입"},
            ],
        )
        unit_id = created["unit"]["id"]

        listed = client.get("/api/v1/property-units").json()["items"][0]["parties"]
        detailed = client.get(f"/api/v1/property-units/{unit_id}").json()["parties"]

        assert listed == detailed


@requires_database
def test_list_drops_a_party_slot_that_the_last_write_left_out(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _):
        complex_id = create_complex(client, session, brokerage_id, "관계종료단지")
        created = create_unit(
            client,
            complex_id,
            unit_number="103",
            parties=[
                {"role": "LANDLORD", "role_index": 1, "name": "박이서"},
                {"role": "TENANT", "role_index": 1, "name": "김세입"},
            ],
        )
        unit = created["unit"]

        patched = client.patch(
            f"/api/v1/property-units/{unit['id']}",
            json={
                "row_version": unit["row_version"],
                "parties": [{"role": "LANDLORD", "role_index": 1, "name": "박이서"}],
            },
        )
        assert patched.status_code == 200, patched.text

        listed = client.get("/api/v1/property-units").json()["items"][0]["parties"]
        assert [entry["party"]["name"] for entry in listed] == ["박이서"]


@requires_database
def test_list_party_summary_carries_only_the_fields_the_grid_draws(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _):
        complex_id = create_complex(client, session, brokerage_id, "노출범위단지")
        create_unit(
            client,
            complex_id,
            unit_number="104",
            parties=[{"role": "LANDLORD", "role_index": 1, "name": "박이서"}],
        )

        party = client.get("/api/v1/property-units").json()["items"][0]["parties"][0]["party"]

        assert set(party) == {
            "id",
            "party_type",
            "name",
            "alternate_name",
            "privacy_consent_at",
            "contacts",
        }


@requires_database
def test_list_does_not_carry_the_parties_of_another_brokerage(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _):
        complex_id = create_complex(client, session, brokerage_id, "우리단지")
        create_unit(
            client,
            complex_id,
            unit_number="105",
            parties=[{"role": "LANDLORD", "role_index": 1, "name": "우리임대인"}],
        )

        other_brokerage_id = session.execute(
            text("INSERT INTO brokerage (name) VALUES ('남의 사무소') RETURNING id")
        ).scalar_one()
        other_complex_id = create_complex(client, session, other_brokerage_id, "남의단지")
        other_unit_id = session.execute(
            text(
                "INSERT INTO property_unit (brokerage_id, complex_id, unit_number)"
                " VALUES (:b, :c, '999') RETURNING id"
            ),
            {"b": other_brokerage_id, "c": other_complex_id},
        ).scalar_one()
        other_party_id = session.execute(
            text(
                "INSERT INTO party (brokerage_id, party_type, name)"
                " VALUES (:b, 'PERSON', '남의임대인') RETURNING id"
            ),
            {"b": other_brokerage_id},
        ).scalar_one()
        session.execute(
            text(
                "INSERT INTO property_unit_party_relation"
                " (brokerage_id, unit_id, party_id, role, role_index)"
                " VALUES (:b, :u, :p, 'LANDLORD', 1)"
            ),
            {"b": other_brokerage_id, "u": other_unit_id, "p": other_party_id},
        )

        items = client.get("/api/v1/property-units").json()["items"]

        assert [item["unit_number"] for item in items] == ["105"]
        assert [entry["party"]["name"] for item in items for entry in item["parties"]] == [
            "우리임대인"
        ]
