"""F1 저장 성공 후의 F3 교차 판정 자동 접수.

확인하는 것은 넷이다. 저장이 실행을 만드는가, 같은 입력이면 재사용하는가, 판정과 무관한
수정이 실행을 만들지 않는가, 그리고 F3 접수가 실패해도 F1 저장이 남는가.
"""

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


def runs(session: Session, brokerage_id: int) -> list[dict]:
    rows = session.execute(
        text(
            "SELECT id, status, trigger_type, target_listing_id, target_requirement_id,"
            " input_data_version, requested_by FROM agent_run WHERE brokerage_id = :b"
            " ORDER BY id"
        ),
        {"b": brokerage_id},
    ).mappings()
    return [dict(row) for row in rows]


def create_listing(client: TestClient, complex_id: int, **overrides: object) -> dict:
    unit = create_unit(client, complex_id, **overrides)
    response = client.post(
        f"/api/v1/property-units/{unit['unit']['id']}/listings",
        json={"is_sale_available": True, "sale_price": 2_880_000_000},
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_party(session: Session, brokerage_id: int, name: str, user_id: int) -> int:
    stored = session.execute(
        text(
            "INSERT INTO party (brokerage_id, party_type, name, privacy_consent_at,"
            " privacy_consent_by) VALUES (:b, 'PERSON', :n, now(), :u) RETURNING id"
        ),
        {"b": brokerage_id, "n": name, "u": user_id},
    ).scalar_one()
    session.commit()
    return stored


def create_requirement(client: TestClient, party_id: int) -> dict:
    response = client.post(
        "/api/v1/property-requirements",
        json={"party_id": party_id, "demand_type": "매수", "max_budget_amount": 2_900_000_000},
    )
    assert response.status_code == 201, response.text
    return response.json()["requirement"]


# ── 어떤 필드가 판정을 다시 돌리는가 ──────────────────────────────────────────


def test_row_version_alone_does_not_touch_the_judgment_input() -> None:
    """`row_version` 은 항상 실려 온다. 그것만 보고 판단하면 모든 수정이 대상이 된다."""
    assert not touches_judgment_input({"row_version"}, LISTING_TRIGGER_FIELDS)


def test_a_price_change_touches_the_judgment_input() -> None:
    assert touches_judgment_input({"row_version", "sale_price"}, LISTING_TRIGGER_FIELDS)


def test_a_memo_change_does_not_touch_the_judgment_input() -> None:
    assert not touches_judgment_input({"row_version", "memo"}, LISTING_TRIGGER_FIELDS)


def test_a_budget_change_touches_the_requirement_input() -> None:
    assert touches_judgment_input({"row_version", "max_budget_amount"}, REQUIREMENT_TRIGGER_FIELDS)


def test_an_assignee_change_does_not_touch_the_requirement_input() -> None:
    assert not touches_judgment_input(
        {"row_version", "assigned_user_id"}, REQUIREMENT_TRIGGER_FIELDS
    )


# ── 저장 이벤트 ────────────────────────────────────────────────────────────────


@requires_database
def test_a_new_listing_queues_a_run(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, user_id):
        complex_id = create_complex(client, session, brokerage_id, "자동단지")

        listing = create_listing(client, complex_id)

        stored = runs(session, brokerage_id)
        assert len(stored) == 1
        assert stored[0]["target_listing_id"] == listing["id"]
        assert stored[0]["status"] == "QUEUED"
        assert stored[0]["requested_by"] == user_id
        # 자동 실행은 화면에서 직접 누른 요청과 구분한다.
        assert stored[0]["trigger_type"] == triggers.LEDGER_SAVE_TRIGGER_TYPE


@requires_database
def test_a_price_change_queues_a_new_run(config: Config) -> None:
    """가격 변경이 저장 이벤트다. 예산이 모자라 빠졌던 손님이 다시 후보가 된다 (F3-CR-02)."""
    with ledger_client(config) as (client, session, brokerage_id, _user):
        complex_id = create_complex(client, session, brokerage_id, "가격단지")
        listing = create_listing(client, complex_id)

        response = client.patch(
            f"/api/v1/property-listings/{listing['id']}",
            json={"row_version": listing["row_version"], "sale_price": 2_650_000_000},
        )
        assert response.status_code == 200, response.text

        stored = runs(session, brokerage_id)
        assert len(stored) == 2
        assert stored[-1]["input_data_version"] == listing["row_version"] + 1


@requires_database
def test_an_unrelated_listing_change_queues_nothing(config: Config) -> None:
    """담당자 메모만 고친 저장이 판정을 다시 돌릴 이유는 없다."""
    with ledger_client(config) as (client, session, brokerage_id, _user):
        complex_id = create_complex(client, session, brokerage_id, "메모단지")
        listing = create_listing(client, complex_id)
        before = len(runs(session, brokerage_id))

        response = client.patch(
            f"/api/v1/property-listings/{listing['id']}",
            json={"row_version": listing["row_version"], "memo": "담당자 메모"},
        )
        assert response.status_code == 200, response.text

        assert len(runs(session, brokerage_id)) == before


@requires_database
def test_a_new_requirement_queues_a_run(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, user_id):
        party_id = create_party(session, brokerage_id, "자동 손님", user_id)

        requirement = create_requirement(client, party_id)

        stored = runs(session, brokerage_id)
        assert len(stored) == 1
        assert stored[0]["target_requirement_id"] == requirement["id"]
        assert stored[0]["target_listing_id"] is None
        assert stored[0]["trigger_type"] == triggers.LEDGER_SAVE_TRIGGER_TYPE


@requires_database
def test_a_condition_change_queues_a_new_run(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, user_id):
        party_id = create_party(session, brokerage_id, "조건 손님", user_id)
        requirement = create_requirement(client, party_id)

        response = client.patch(
            f"/api/v1/property-requirements/{requirement['id']}",
            json={
                "row_version": requirement["row_version"],
                "max_budget_amount": 3_100_000_000,
            },
        )
        assert response.status_code == 200, response.text

        stored = runs(session, brokerage_id)
        assert len(stored) == 2
        assert stored[-1]["input_data_version"] == requirement["row_version"] + 1


@requires_database
def test_an_unrelated_requirement_change_queues_nothing(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, user_id):
        party_id = create_party(session, brokerage_id, "무관 손님", user_id)
        requirement = create_requirement(client, party_id)
        before = len(runs(session, brokerage_id))

        response = client.patch(
            f"/api/v1/property-requirements/{requirement['id']}",
            json={"row_version": requirement["row_version"], "memo": "메모만"},
        )
        assert response.status_code == 200, response.text

        assert len(runs(session, brokerage_id)) == before


# ── 재사용과 격리 ──────────────────────────────────────────────────────────────


@requires_database
def test_the_screen_request_reuses_the_run_the_save_created(config: Config) -> None:
    """자동 접수와 화면 진입이 각각 실행을 만들면 같은 판정을 두 번 돌린다 (F3-CR-12)."""
    with ledger_client(config) as (client, session, brokerage_id, _user):
        complex_id = create_complex(client, session, brokerage_id, "재사용단지")
        listing = create_listing(client, complex_id)
        auto = runs(session, brokerage_id)[0]

        response = client.post(
            "/api/v1/f3/runs", json={"anchor_type": "LISTING", "anchor_id": listing["id"]}
        )

        assert response.status_code == 202, response.text
        assert response.json()["run_id"] == auto["id"]
        assert len(runs(session, brokerage_id)) == 1


@requires_database
def test_the_auto_run_belongs_to_the_saving_brokerage(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _user):
        complex_id = create_complex(client, session, brokerage_id, "격리단지")
        create_listing(client, complex_id)

        other = session.execute(
            text("SELECT count(*) FROM agent_run WHERE brokerage_id <> :b"), {"b": brokerage_id}
        ).scalar_one()
        mine = session.execute(
            text("SELECT count(*) FROM agent_run WHERE brokerage_id = :b"), {"b": brokerage_id}
        ).scalar_one()

        assert mine == 1
        # 이 테스트가 만든 저장은 다른 사무소에 실행을 만들지 않는다.
        assert other == 0


# ── 실패 격리 ──────────────────────────────────────────────────────────────────


@requires_database
def test_a_failed_intake_keeps_the_ledger_save(
    config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F3 접수 실패 때문에 성공한 F1 저장을 되돌리지 않는다 (F3-NF-07, F3-CM-06)."""

    def explode(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("intake is broken")

    monkeypatch.setattr(triggers.service, "queue_cross_judgment_run", explode)

    with ledger_client(config) as (client, session, brokerage_id, _user):
        complex_id = create_complex(client, session, brokerage_id, "실패격리단지")

        listing = create_listing(client, complex_id)

        assert listing["id"] > 0
        stored = session.execute(
            text("SELECT count(*) FROM property_listing WHERE id = :i"), {"i": listing["id"]}
        ).scalar_one()
        assert stored == 1, "F1 저장은 그대로 남는다"
        assert runs(session, brokerage_id) == []


@requires_database
def test_a_failed_intake_returns_none_without_raising(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, user_id):
        complex_id = create_complex(client, session, brokerage_id, "없는앵커단지")
        create_complex(client, session, brokerage_id, "보조단지")

        # 존재하지 않는 매물을 앵커로 준다. 예외가 밖으로 나오면 안 된다.
        queued = triggers.after_listing_saved(session, brokerage_id, user_id, 987_654_321)

        assert queued is None
        assert runs(session, brokerage_id) == []
        assert complex_id > 0
