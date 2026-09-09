"""Thin HTTP/DB flow with a deterministic F2 provider boundary.

This verifies API composition and persistence, not browser field conversion,
model quality, or completion of the F3 worker pipeline.
"""

from typing import cast

from f2_fixtures import FakePipeline
from fastapi import FastAPI
from ledger_fixtures import create_complex, create_unit, ledger_client, requires_database
from sqlalchemy import text
from sqlmodel import Session

from api.f2 import get_f2_pipeline
from core.config import Config


def business_counts(session: Session, brokerage_id: int) -> tuple[int, ...]:
    return tuple(
        session.execute(
            text(f"SELECT count(*) FROM {table} WHERE brokerage_id = :b"),
            {"b": brokerage_id},
        ).scalar_one()
        for table in ("property_listing", "property_requirement", "client_interaction", "agent_run")
    )


@requires_database
def test_f2_analysis_waits_for_approved_ledger_save_before_f3_is_queued(config: Config) -> None:
    with ledger_client(config, csrf_token="flow-csrf") as (
        client,
        session,
        brokerage_id,
        user_id,
    ):
        client.headers["X-CSRF-Token"] = "flow-csrf"
        complex_id = create_complex(client, session, brokerage_id, "합성 흐름 검증 단지")
        unit_id = create_unit(client, complex_id)["unit"]["id"]
        pipeline = FakePipeline()
        cast(FastAPI, client.app).dependency_overrides[get_f2_pipeline] = lambda: pipeline
        before = business_counts(session, brokerage_id)

        analysis = client.post(
            "/api/v1/f2/analyses",
            files={"audio": ("synthetic.wav", b"synthetic-audio", "audio/wav")},
            data={"privacy_confirmed": "true", "current_ledger_type": "매물장"},
        )

        assert analysis.status_code == 200, analysis.text
        proposals = analysis.json()["proposals"]
        assert proposals[0]["field_name"] == "매매가"
        assert proposals[0]["proposed_value"] == "12억"
        assert business_counts(session, brokerage_id) == before
        assert pipeline.temp_path is not None and not pipeline.temp_path.exists()

        # The user accepts the proposed 12억; the HTTP money contract uses integer KRW.
        saved = client.post(
            f"/api/v1/property-units/{unit_id}/listings",
            json={"is_sale_available": True, "sale_price": 1_200_000_000},
        )
        assert saved.status_code == 201, saved.text
        listing = saved.json()
        stored_price = session.execute(
            text("SELECT sale_price FROM property_listing WHERE id = :id AND brokerage_id = :b"),
            {"id": listing["id"], "b": brokerage_id},
        ).scalar_one()
        assert stored_price == 1_200_000_000
        queued = (
            session.execute(
                text(
                    "SELECT id, trigger_type, requested_by FROM agent_run WHERE brokerage_id = :b"
                ),
                {"b": brokerage_id},
            )
            .mappings()
            .one()
        )
        assert queued["trigger_type"] == "LEDGER_SAVE"
        assert queued["requested_by"] == user_id

        requested = client.post(
            "/api/v1/f3/runs",
            json={"anchor_type": "LISTING", "anchor_id": listing["id"]},
        )
        assert requested.status_code == 202, requested.text
        assert requested.json()["run_id"] == queued["id"]
        assert requested.json()["input_data_version"] == listing["row_version"]
        active = (
            session.execute(
                text("SELECT id, trigger_type FROM agent_run WHERE brokerage_id = :b"),
                {"b": brokerage_id},
            )
            .mappings()
            .one()
        )
        assert active["id"] == queued["id"]
        assert active["trigger_type"] == "USER_REQUEST"
