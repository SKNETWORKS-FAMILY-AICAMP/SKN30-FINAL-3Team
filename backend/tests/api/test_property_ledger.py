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


@requires_database
def test_invalid_party_leaves_no_unit_behind(config: Config) -> None:
    """인물 검증이 실패하면 세대도 남지 않는다.

    인물 없는 세대 자체는 정상이다. 문제는 화면이 한 요청을 전부 아니면 전무로 보고
    성공했을 때만 서버 id를 기록한다는 점이다. 세대만 커밋되면 화면은 그것을 모른 채
    재시도해 같은 세대를 다시 만든다.
    """
    with ledger_client(config) as (client, session, brokerage_id, _):
        complex_id = create_complex(client, session, brokerage_id, "부분저장단지")

        response = client.post(
            "/api/v1/property-units",
            json={
                "complex_id": complex_id,
                "unit_number": "101",
                "parties": [
                    {"role": "LANDLORD", "role_index": 1, "name": "박이서"},
                    {"role": "LANDLORD", "role_index": 1, "name": "송경련"},
                ],
            },
        )

        assert response.status_code == 422, response.text
        assert client.get("/api/v1/property-units").json()["total"] == 0


@requires_database
def test_failed_party_save_leaves_the_row_version_retryable(config: Config) -> None:
    """인물 저장이 실패하면 세대 `row_version`도 오르지 않아 같은 요청을 다시 보낼 수 있다.

    세대를 먼저 커밋하면 버전만 오른 채 인물이 빠진다. 화면은 실패를 봤으므로 낡은 버전을
    그대로 들고 재시도하고, 그 재시도는 409가 되어 새로고침 말고는 빠져나갈 길이 없다.
    """
    with ledger_client(config) as (client, session, brokerage_id, _):
        complex_id = create_complex(client, session, brokerage_id, "재시도단지")
        created = create_unit(client, complex_id, unit_number="101")
        unit_id = created["unit"]["id"]
        row_version = created["unit"]["row_version"]

        rejected = client.patch(
            f"/api/v1/property-units/{unit_id}",
            json={
                "row_version": row_version,
                "orientation": "남향",
                "parties": [
                    {"role": "TENANT", "role_index": 1, "name": "김세입"},
                    {"role": "TENANT", "role_index": 1, "name": "이세입"},
                ],
            },
        )

        assert rejected.status_code == 422, rejected.text

        # 세대 필드도 함께 되돌아갔는지 본다. 인물만 롤백되고 방향이 남으면 부분 저장이다.
        assert client.get(f"/api/v1/property-units/{unit_id}").json()["unit"]["orientation"] is None

        retried = client.patch(
            f"/api/v1/property-units/{unit_id}",
            json={
                "row_version": row_version,
                "orientation": "남향",
                "parties": [{"role": "TENANT", "role_index": 1, "name": "김세입"}],
            },
        )

        assert retried.status_code == 200, retried.text
        body = retried.json()
        assert body["unit"]["orientation"] == "남향"
        assert [entry["party"]["name"] for entry in body["parties"]] == ["김세입"]
