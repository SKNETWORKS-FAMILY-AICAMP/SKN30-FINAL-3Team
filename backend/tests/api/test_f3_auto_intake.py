"""F1 저장 뒤 F3 자동 접수, 실제 변경 감지와 장애 격리를 검증한다."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from ledger_fixtures import create_complex, create_unit, ledger_client, requires_database
from sqlalchemy import text
from sqlmodel import Session

from core.config import Config
from domain.agent_execution import triggers
from domain.agent_execution.triggers import (
    LISTING_TRIGGER_FIELDS,
    REQUIREMENT_TRIGGER_FIELDS,
    touches_judgment_input,
)


def stored_runs(session: Session, brokerage_id: int) -> list[dict]:
    rows = session.execute(
        text(
            "SELECT id, status, trigger_type, target_listing_id, target_requirement_id,"
            " input_data_version, requested_by FROM agent_run WHERE brokerage_id = :brokerage_id"
            " ORDER BY id"
        ),
        {"brokerage_id": brokerage_id},
    ).mappings()
    return [dict(row) for row in rows]


def create_listing(client: TestClient, complex_id: int) -> dict:
    unit = create_unit(client, complex_id)
    response = client.post(
        f"/api/v1/property-units/{unit['unit']['id']}/listings",
        json={"is_sale_available": True, "sale_price": 2_880_000_000},
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_party(session: Session, brokerage_id: int, user_id: int, name: str) -> int:
    party_id = session.execute(
        text(
            "INSERT INTO party (brokerage_id, party_type, name, privacy_consent_at,"
            " privacy_consent_by) VALUES (:brokerage_id, 'PERSON', :name, now(), :user_id)"
            " RETURNING id"
        ),
        {"brokerage_id": brokerage_id, "name": name, "user_id": user_id},
    ).scalar_one()
    session.commit()
    return int(party_id)


def create_requirement(client: TestClient, party_id: int, **extra: object) -> dict:
    response = client.post(
        "/api/v1/property-requirements",
        json={
            "party_id": party_id,
            "demand_type": "매수",
            "max_budget_amount": 2_900_000_000,
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["requirement"]


def test_only_actual_judgment_fields_trigger_follow_up() -> None:
    assert touches_judgment_input({"sale_price"}, LISTING_TRIGGER_FIELDS)
    assert not touches_judgment_input({"memo", "assigned_user_id"}, LISTING_TRIGGER_FIELDS)
    assert touches_judgment_input({"desired_complex_ids"}, REQUIREMENT_TRIGGER_FIELDS)
    assert not touches_judgment_input({"memo", "assigned_user_id"}, REQUIREMENT_TRIGGER_FIELDS)


@requires_database
def test_new_listing_and_requirement_queue_ledger_save_runs(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, user_id):
        complex_id = create_complex(client, session, brokerage_id, "자동접수단지")
        listing = create_listing(client, complex_id)
        party_id = create_party(session, brokerage_id, user_id, "자동접수 손님")
        requirement = create_requirement(client, party_id)

        runs = stored_runs(session, brokerage_id)
        assert len(runs) == 2
        assert runs[0]["target_listing_id"] == listing["id"]
        assert runs[1]["target_requirement_id"] == requirement["id"]
        assert {run["trigger_type"] for run in runs} == {triggers.LEDGER_SAVE_TRIGGER_TYPE}
        assert {run["requested_by"] for run in runs} == {user_id}


@requires_database
def test_judgment_input_changes_queue_new_input_versions(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, user_id):
        complex_id = create_complex(client, session, brokerage_id, "조건변경단지")
        listing = create_listing(client, complex_id)
        party_id = create_party(session, brokerage_id, user_id, "조건변경 손님")
        requirement = create_requirement(client, party_id)

        listing_response = client.patch(
            f"/api/v1/property-listings/{listing['id']}",
            json={"row_version": listing["row_version"], "sale_price": 2_650_000_000},
        )
        requirement_response = client.patch(
            f"/api/v1/property-requirements/{requirement['id']}",
            json={
                "row_version": requirement["row_version"],
                "max_budget_amount": 3_100_000_000,
            },
        )

        assert listing_response.status_code == 200, listing_response.text
        assert requirement_response.status_code == 200, requirement_response.text
        runs = stored_runs(session, brokerage_id)
        listing_versions = [
            run["input_data_version"] for run in runs if run["target_listing_id"] == listing["id"]
        ]
        requirement_versions = [
            run["input_data_version"]
            for run in runs
            if run["target_requirement_id"] == requirement["id"]
        ]
        assert listing_versions == [listing["row_version"], listing["row_version"] + 1]
        assert requirement_versions == [
            requirement["row_version"],
            requirement["row_version"] + 1,
        ]


@requires_database
def test_unrelated_and_same_value_updates_queue_nothing(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, user_id):
        complex_id = create_complex(client, session, brokerage_id, "무변경단지")
        listing = create_listing(client, complex_id)
        party_id = create_party(session, brokerage_id, user_id, "무변경 손님")
        requirement = create_requirement(client, party_id)
        before = len(stored_runs(session, brokerage_id))

        memo_response = client.patch(
            f"/api/v1/property-listings/{listing['id']}",
            json={"row_version": listing["row_version"], "memo": "운영 메모"},
        )
        same_budget = client.patch(
            f"/api/v1/property-requirements/{requirement['id']}",
            json={
                "row_version": requirement["row_version"],
                "max_budget_amount": requirement["max_budget_amount"],
            },
        )

        assert memo_response.status_code == 200, memo_response.text
        assert memo_response.json()["row_version"] == listing["row_version"] + 1
        assert same_budget.status_code == 200, same_budget.text
        assert same_budget.json()["requirement"]["row_version"] == requirement["row_version"]
        assert len(stored_runs(session, brokerage_id)) == before


@requires_database
def test_resaving_same_listing_value_keeps_row_version(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _user_id):
        complex_id = create_complex(client, session, brokerage_id, "동일가격단지")
        listing = create_listing(client, complex_id)
        before = len(stored_runs(session, brokerage_id))

        response = client.patch(
            f"/api/v1/property-listings/{listing['id']}",
            json={"row_version": listing["row_version"], "sale_price": listing["sale_price"]},
        )

        assert response.status_code == 200, response.text
        assert response.json()["row_version"] == listing["row_version"]
        assert len(stored_runs(session, brokerage_id)) == before


@requires_database
def test_desired_complex_membership_updates_version_and_reordering_is_noop(
    config: Config,
) -> None:
    with ledger_client(config) as (client, session, brokerage_id, user_id):
        first = create_complex(client, session, brokerage_id, "희망단지가")
        second = create_complex(client, session, brokerage_id, "희망단지나")
        party_id = create_party(session, brokerage_id, user_id, "희망단지 손님")
        requirement = create_requirement(client, party_id, desired_complex_ids=[first])

        changed = client.patch(
            f"/api/v1/property-requirements/{requirement['id']}",
            json={
                "row_version": requirement["row_version"],
                "desired_complex_ids": [first, second],
            },
        )
        assert changed.status_code == 200, changed.text
        changed_version = changed.json()["requirement"]["row_version"]
        assert changed_version == requirement["row_version"] + 1
        after_change = len(stored_runs(session, brokerage_id))

        reordered = client.patch(
            f"/api/v1/property-requirements/{requirement['id']}",
            json={"row_version": changed_version, "desired_complex_ids": [second, first]},
        )
        assert reordered.status_code == 200, reordered.text
        assert reordered.json()["requirement"]["row_version"] == changed_version
        assert len(stored_runs(session, brokerage_id)) == after_change


@requires_database
def test_same_value_with_stale_version_is_still_a_conflict(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _user_id):
        complex_id = create_complex(client, session, brokerage_id, "낡은버전단지")
        listing = create_listing(client, complex_id)
        updated = client.patch(
            f"/api/v1/property-listings/{listing['id']}",
            json={"row_version": listing["row_version"], "memo": "먼저 저장"},
        )
        assert updated.status_code == 200, updated.text

        stale = client.patch(
            f"/api/v1/property-listings/{listing['id']}",
            json={"row_version": listing["row_version"], "sale_price": listing["sale_price"]},
        )
        assert stale.status_code == 409, stale.text
        assert stale.json()["code"] == "ROW_VERSION_CONFLICT"


@requires_database
def test_screen_request_reuses_run_created_by_save(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _user_id):
        complex_id = create_complex(client, session, brokerage_id, "재사용단지")
        listing = create_listing(client, complex_id)
        automatic = stored_runs(session, brokerage_id)[0]

        response = client.post(
            "/api/v1/f3/runs",
            json={"anchor_type": "LISTING", "anchor_id": listing["id"]},
        )

        assert response.status_code == 202, response.text
        assert response.json()["run_id"] == automatic["id"]
        assert len(stored_runs(session, brokerage_id)) == 1


@requires_database
def test_failed_intake_does_not_rollback_ledger_create_or_update(
    config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_intake(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("intake unavailable")

    monkeypatch.setattr(triggers.service, "queue_cross_judgment_run", fail_intake)
    with ledger_client(config) as (client, session, brokerage_id, _user_id):
        complex_id = create_complex(client, session, brokerage_id, "격리단지")
        listing = create_listing(client, complex_id)
        assert stored_runs(session, brokerage_id) == []

        response = client.patch(
            f"/api/v1/property-listings/{listing['id']}",
            json={"row_version": listing["row_version"], "sale_price": 2_650_000_000},
        )

        assert response.status_code == 200, response.text
        stored_price = session.execute(
            text("SELECT sale_price FROM property_listing WHERE id = :listing_id"),
            {"listing_id": listing["id"]},
        ).scalar_one()
        assert stored_price == 2_650_000_000
        assert stored_runs(session, brokerage_id) == []
