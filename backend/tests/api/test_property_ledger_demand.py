from __future__ import annotations

import pytest
from ledger_fixtures import create_complex, create_unit, ledger_client, requires_database
from sqlalchemy import text
from sqlmodel import Session

from core.config import Config


def create_party(
    session: Session, brokerage_id: int, name: str, *, consented_by: int | None = None
) -> int:
    return session.execute(
        text(
            "INSERT INTO party (brokerage_id, party_type, name, privacy_consent_at,"
            " privacy_consent_by)"
            " VALUES (:b, 'PERSON', :n,"
            " CASE WHEN CAST(:u AS BIGINT) IS NULL THEN NULL ELSE now() END,"
            " CAST(:u AS BIGINT))"
            " RETURNING id"
        ),
        {"b": brokerage_id, "n": name, "u": consented_by},
    ).scalar_one()


@requires_database
def test_requirement_is_rejected_without_privacy_consent(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _user_id):
        party_id = create_party(session, brokerage_id, "미동의 손님")

        response = client.post(
            "/api/v1/property-requirements",
            json={"party_id": party_id, "demand_type": "매수"},
        )

        assert response.status_code == 422
        assert response.json()["code"] == "PRIVACY_CONSENT_REQUIRED"


@requires_database
def test_requirement_keeps_raw_text_multiple_pyeongs_and_desired_complexes(
    config: Config,
) -> None:
    with ledger_client(config) as (client, session, brokerage_id, user_id):
        party_id = create_party(session, brokerage_id, "인천사모님", consented_by=user_id)
        first = create_complex(client, session, brokerage_id, "1지망단지")
        second = create_complex(client, session, brokerage_id, "2지망단지")

        response = client.post(
            "/api/v1/property-requirements",
            json={
                "party_id": party_id,
                "demand_type": "매수",
                "desired_pyeongs": ["25", "33"],
                "desired_complex_ids": [first, second],
                "max_budget_amount": 2_880_000_000,
                "budget_raw_text": "28억선",
                "move_in_date_raw_text": "1월중",
            },
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["requirement"]["desired_pyeongs"] == ["25.00", "33.00"]
        assert body["requirement"]["max_budget_amount"] == 2_880_000_000
        assert body["requirement"]["budget_raw_text"] == "28억선"
        assert body["requirement"]["move_in_date_raw_text"] == "1월중"
        assert body["requirement"]["party"]["name"] == "인천사모님"
        assert [item["complex"]["id"] for item in body["desired_complexes"]] == [first, second]


@requires_database
def test_requirement_update_respects_row_version(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, user_id):
        party_id = create_party(session, brokerage_id, "수정 손님", consented_by=user_id)
        created = client.post(
            "/api/v1/property-requirements",
            json={"party_id": party_id, "demand_type": "매수"},
        ).json()["requirement"]

        accepted = client.patch(
            f"/api/v1/property-requirements/{created['id']}",
            json={"row_version": created["row_version"], "workflow_stage": "방문예정"},
        )
        assert accepted.status_code == 200
        assert accepted.json()["requirement"]["workflow_stage"] == "방문예정"

        stale = client.patch(
            f"/api/v1/property-requirements/{created['id']}",
            json={"row_version": created["row_version"], "workflow_stage": "덮어쓰기"},
        )
        assert stale.status_code == 409
        assert stale.json()["code"] == "ROW_VERSION_CONFLICT"


@requires_database
def test_requirement_list_is_sorted_by_last_contact(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, user_id):
        first_party = create_party(session, brokerage_id, "먼저 접수", consented_by=user_id)
        second_party = create_party(session, brokerage_id, "나중 접수", consented_by=user_id)
        first = client.post(
            "/api/v1/property-requirements",
            json={"party_id": first_party, "demand_type": "매수"},
        ).json()["requirement"]
        client.post(
            "/api/v1/property-requirements",
            json={"party_id": second_party, "demand_type": "전세"},
        )

        client.post(
            "/api/v1/client-interactions",
            json={"requirement_id": first["id"], "interaction_content": "예산 상향"},
        )

        body = client.get("/api/v1/property-requirements").json()

        assert body["items"][0]["id"] == first["id"]
        assert body["items"][0]["last_contact_at"] is not None


@requires_database
def test_interaction_requires_a_scope(config: Config) -> None:
    with ledger_client(config) as (client, _session, _brokerage_id, _user_id):
        response = client.get("/api/v1/client-interactions")

        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_FAILED"


@requires_database
def test_interaction_is_appended_and_updates_unit_last_contact(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _user_id):
        complex_id = create_complex(client, session, brokerage_id, "로그단지")
        unit_id = create_unit(client, complex_id)["unit"]["id"]

        created = client.post(
            "/api/v1/client-interactions",
            json={"unit_id": unit_id, "interaction_content": "임대인 통화, 만기 확인"},
        )
        assert created.status_code == 201, created.text
        assert created.json()["source_type"] == "HUMAN"
        assert created.json()["approval_status"] == "NOT_REQUIRED"

        listed = client.get("/api/v1/client-interactions", params={"unit_id": unit_id}).json()
        assert listed["total"] == 1
        assert listed["items"][0]["interaction_content"] == "임대인 통화, 만기 확인"

        detail = client.get(f"/api/v1/property-units/{unit_id}").json()
        assert detail["unit"]["last_contact_at"] is not None


@requires_database
def test_interaction_cannot_reference_another_brokerage_unit(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _user_id):
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

        response = client.post(
            "/api/v1/client-interactions",
            json={"unit_id": other_unit_id, "interaction_content": "교차 참조"},
        )

        assert response.status_code == 404
        assert response.json()["code"] == "NOT_FOUND"


@requires_database
def test_interaction_has_no_update_or_delete_route(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _user_id):
        complex_id = create_complex(client, session, brokerage_id, "추가전용단지")
        unit_id = create_unit(client, complex_id)["unit"]["id"]
        created = client.post(
            "/api/v1/client-interactions",
            json={"unit_id": unit_id, "interaction_content": "원본"},
        ).json()

        patched = client.patch(
            f"/api/v1/client-interactions/{created['id']}", json={"interaction_content": "수정"}
        )
        deleted = client.delete(f"/api/v1/client-interactions/{created['id']}")

        assert patched.status_code in {404, 405}
        assert deleted.status_code in {404, 405}


@requires_database
def test_requirement_column_values_include_the_empty_bucket(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, user_id):
        with_stage = create_party(session, brokerage_id, "단계 있음", consented_by=user_id)
        without_stage = create_party(session, brokerage_id, "단계 없음", consented_by=user_id)
        client.post(
            "/api/v1/property-requirements",
            json={"party_id": with_stage, "demand_type": "매수", "workflow_stage": "방문예정"},
        )
        client.post(
            "/api/v1/property-requirements",
            json={"party_id": without_stage, "demand_type": "매수"},
        )

        body = client.get(
            "/api/v1/property-requirements/column-values", params={"column": "workflow_stage"}
        ).json()

        assert {item["value"]: item["count"] for item in body["items"]} == {
            "__EMPTY__": 1,
            "방문예정": 1,
        }


@pytest.mark.parametrize(
    "path",
    ["/api/v1/property-units", "/api/v1/property-requirements", "/api/v1/client-interactions"],
)
def test_ledger_routes_are_published_in_the_openapi_contract(config: Config, path: str) -> None:
    from main import create_app

    app = create_app(config=config, readiness_probe=lambda request: True)

    assert path in app.openapi()["paths"]
