"""판정 read API의 실제 PostgreSQL·HTTP 경계와 업무 의미 회귀."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from ledger_fixtures import ledger_client, requires_database
from sqlalchemy import text
from test_f3_results import _queue_listing_run, _store_anchor_card, _store_completed_judgment

from core.config import Config
from domain.agent_execution.freshness import configuration_identity, current_revision


def _stored(client, session, b, u):
    run, listing = _queue_listing_run(client, session, b)
    card = _store_anchor_card(session, b, run["run_id"], listing["id"])
    candidate = _store_completed_judgment(session, b, u, run["run_id"], card)
    header = session.execute(
        text("SELECT id FROM match_evaluation WHERE agent_run_id=:r"), {"r": run["run_id"]}
    ).scalar_one()
    return run, listing, card, candidate, header


def _current(session, b, run, listing, header):
    session.execute(
        text("""INSERT INTO match_target_state
        (brokerage_id,anchor_type,anchor_id,current_run_id,current_result_id,
         verified_revision,verified_day,config_identity,verified_at,meaningful_changed_at)
        VALUES (:b,'LISTING',:l,:r,:h,:rev,:day,:cfg,now(),now())
        ON CONFLICT (brokerage_id,anchor_type,anchor_id) DO UPDATE SET
          current_run_id=:r,current_result_id=:h,verified_revision=:rev,
          verified_day=:day,config_identity=:cfg"""),
        {
            "b": b,
            "l": listing["id"],
            "r": run["run_id"],
            "h": header,
            "rev": current_revision(session, b),
            "day": datetime.now(UTC).date(),
            "cfg": configuration_identity(session, b),
        },
    )
    session.commit()


@requires_database
def test_queries_do_not_enqueue_or_expose_internal_fields(config: Config):
    with ledger_client(config) as (client, session, b, u):
        run, listing, _card, candidate, header = _stored(client, session, b, u)
        _current(session, b, run, listing, header)
        before = session.execute(text("SELECT count(*) FROM agent_run")).scalar_one()
        for _ in range(10):
            response = client.get("/api/v1/f3/judgment-results?anchor_type=LISTING")
            assert response.status_code == 200, response.text
            assert response.headers["cache-control"] == "no-store"
            body = response.json()
            assert body["counts"]["HAS_MATCH"] == 1
            assert body["items"][0]["freshness"] == "CURRENT"
            assert body["items"][0]["representative_candidates"][0]["candidate_id"] == candidate
        detail = client.get(f"/api/v1/f3/judgment-results/{header}?candidate_id={candidate}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["selected_candidate"]["target"]["anchor_id"] == candidate
        assert "diagnostics" not in detail.text and "private-model" not in detail.text
        assert "brokerage_id" not in detail.text and "redacted_input_snapshot" not in detail.text
        assert session.execute(text("SELECT count(*) FROM agent_run")).scalar_one() == before


@requires_database
def test_stale_and_unavailable_are_not_current_recommendations(config: Config):
    with ledger_client(config) as (client, session, b, u):
        run, listing, card, _candidate, header = _stored(client, session, b, u)
        _current(session, b, run, listing, header)
        session.execute(
            text("UPDATE property_listing SET sale_price=sale_price-100 WHERE id=:l"),
            {"l": listing["id"]},
        )
        session.commit()
        response = client.get("/api/v1/f3/judgment-results?anchor_type=LISTING")
        assert response.json()["items"] == []
        target = client.get(f"/api/v1/f3/judgment-targets/LISTING/{listing['id']}").json()
        assert target["freshness"] == "STALE"
        assert target["summary"]["strong_count"] == 1
        session.execute(
            text("UPDATE negotiation_position_analysis SET invalidated_at=now() WHERE id=:id"),
            {"id": card},
        )
        session.commit()
        blocked = client.get(f"/api/v1/f3/judgment-results/{header}")
        assert blocked.status_code == 200, blocked.text
        assert blocked.json()["content_availability"] == "UNAVAILABLE"
        assert blocked.json()["summary"] is None
        assert blocked.json()["candidates"] == []


@requires_database
def test_unjudged_filter_and_selected_candidate_outside_page(config: Config):
    with ledger_client(config) as (client, session, b, u):
        run, listing, _card, candidate, header = _stored(client, session, b, u)
        extra = session.execute(
            text("""INSERT INTO property_requirement
            (brokerage_id,party_id,demand_type,max_budget_amount)
            SELECT brokerage_id,party_id,demand_type,max_budget_amount
            FROM property_requirement WHERE id=:id RETURNING id"""),
            {"id": candidate},
        ).scalar_one()
        session.execute(
            text("""UPDATE match_evaluation SET candidate_selection_snapshot=
            jsonb_set(candidate_selection_snapshot,'{candidates,1,candidate_id}',
                      to_jsonb(CAST(:id AS bigint)))
            WHERE id=:h"""),
            {"id": extra, "h": header},
        )
        session.execute(
            text(
                "UPDATE match_candidate_evaluation SET match_grade='REJECTED' "
                "WHERE match_evaluation_id=:h"
            ),
            {"h": header},
        )
        session.commit()
        _current(session, b, run, listing, header)
        listing_response = client.get("/api/v1/f3/judgment-results?anchor_type=LISTING").json()
        assert listing_response["items"] == []
        assert listing_response["counts"]["HAS_UNJUDGED"] == 1
        pending = client.get(
            "/api/v1/f3/judgment-results?anchor_type=LISTING&filter=HAS_UNJUDGED"
        ).json()
        assert pending["items"][0]["summary"]["unjudged_count"] == 1
        response = client.get(f"/api/v1/f3/judgment-results/{header}?limit=1&candidate_id={extra}")
        assert response.status_code == 200, response.text
        selected = response.json()["selected_candidate"]
        assert selected["candidate_id"] == extra
        assert selected["judgment_id"] is None and selected["position_card"] is None
        assert response.json()["candidates"][0]["candidate_id"] == candidate
        assert (
            client.get(f"/api/v1/f3/judgment-results/{header}?candidate_id=987654321").status_code
            == 404
        )


@requires_database
def test_valid_uncreated_target_and_foreign_or_deleted_targets(config: Config):
    with ledger_client(config) as (client, session, b, u):
        run, listing = _queue_listing_run(client, session, b)
        response = client.get(f"/api/v1/f3/judgment-targets/LISTING/{listing['id']}")
        assert response.status_code == 200, response.text
        assert response.json()["summary"] is None and response.json()["freshness"] == "NONE"
        assert client.get("/api/v1/f3/judgment-targets/LISTING/987654321").status_code == 404
        session.execute(
            text("UPDATE property_unit SET is_deleted=true WHERE id=:id"),
            {"id": listing["unit_id"]},
        )
        session.commit()
        assert client.get(f"/api/v1/f3/judgment-targets/LISTING/{listing['id']}").status_code == 404
        assert (
            client.get("/api/v1/f3/judgment-results?anchor_type=LISTING&filter=ALL").json()["items"]
            == []
        )


@requires_database
def test_cursor_validation_and_bounds(config: Config):
    with ledger_client(config) as (client, _session, _b, _u):
        for query in ("cursor=invalid", "limit=101", "filter=OTHER", "anchor_type=OTHER"):
            response = client.get("/api/v1/f3/judgment-results?anchor_type=LISTING&" + query)
            assert response.status_code == 422, response.text


@requires_database
def test_read_requires_authentication(config: Config):
    with ledger_client(config, authenticate=False) as (client, *_):
        assert client.get("/api/v1/f3/judgment-results?anchor_type=LISTING").status_code == 401


@requires_database
def test_closed_anchor_exposes_status_without_judgment_content(config: Config):
    with ledger_client(config) as (client, session, b, u):
        run, listing, _card, _candidate, header = _stored(client, session, b, u)
        _current(session, b, run, listing, header)
        session.execute(
            text("UPDATE property_listing SET status='종료' WHERE id=:id"),
            {"id": listing["id"]},
        )
        session.commit()

        target = client.get(f"/api/v1/f3/judgment-targets/LISTING/{listing['id']}")
        assert target.status_code == 200, target.text
        assert target.json()["eligibility"] == "INELIGIBLE"
        assert target.json()["content_availability"] == "UNAVAILABLE"
        assert target.json()["summary"] is None
        assert target.json()["representative_candidates"] == []

        detail = client.get(f"/api/v1/f3/judgment-results/{header}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["anchor_card"] is None
        assert detail.json()["candidates"] == []
        assert detail.json()["selected_candidate"] is None
        assert detail.json()["summary"] is None
        assert "예산이 가깝다" not in detail.text

        page = client.get("/api/v1/f3/judgment-results?anchor_type=LISTING").json()
        assert page["items"] == [] and page["counts"]["HAS_MATCH"] == 0
        all_items = client.get("/api/v1/f3/judgment-results?anchor_type=LISTING&filter=ALL").json()[
            "items"
        ]
        assert len(all_items) == 1
        assert all_items[0]["content_availability"] == "UNAVAILABLE"


@requires_database
def test_closed_candidate_disappears_from_summary_detail_and_direct_selection(config: Config):
    with ledger_client(config) as (client, session, b, u):
        run, listing, _card, candidate, header = _stored(client, session, b, u)
        _current(session, b, run, listing, header)
        session.execute(
            text("UPDATE property_requirement SET status='종료' WHERE id=:id"),
            {"id": candidate},
        )
        session.commit()

        target = client.get(f"/api/v1/f3/judgment-targets/LISTING/{listing['id']}")
        assert target.status_code == 200, target.text
        assert target.json()["representative_candidates"] == []
        assert target.json()["summary"]["total_count"] == 0
        assert target.json()["summary"]["strong_count"] == 0
        detail = client.get(f"/api/v1/f3/judgment-results/{header}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["candidates"] == []
        assert detail.json()["selected_candidate"] is None
        assert "예산이 가깝다" not in detail.text
        selected = client.get(f"/api/v1/f3/judgment-results/{header}?candidate_id={candidate}")
        assert selected.status_code == 404, selected.text


@requires_database
@pytest.mark.parametrize("invalidate_old_card", [False, True])
def test_historical_result_keeps_its_own_freshness_and_candidate_scope(
    config: Config, invalidate_old_card: bool
):
    with ledger_client(config) as (client, session, b, u):
        _old_run, listing, old_card, old_candidate, old_header = _stored(client, session, b, u)
        next_response = client.post(
            "/api/v1/f3/runs",
            json={"anchor_type": "LISTING", "anchor_id": listing["id"]},
        )
        assert next_response.status_code == 202, next_response.text
        next_run = next_response.json()
        new_card = _store_anchor_card(session, b, next_run["run_id"], listing["id"])
        new_candidate = _store_completed_judgment(session, b, u, next_run["run_id"], new_card)
        new_header = session.execute(
            text("SELECT id FROM match_evaluation WHERE agent_run_id=:r"),
            {"r": next_run["run_id"]},
        ).scalar_one()
        _current(session, b, next_run, listing, new_header)
        if invalidate_old_card:
            session.execute(
                text("UPDATE negotiation_position_analysis SET invalidated_at=now() WHERE id=:id"),
                {"id": old_card},
            )
            session.commit()

        current = client.get(f"/api/v1/f3/judgment-targets/LISTING/{listing['id']}")
        assert current.status_code == 200, current.text
        assert current.json()["freshness"] == "CURRENT"
        assert current.json()["result_id"] == new_header
        historical = client.get(f"/api/v1/f3/judgment-results/{old_header}")
        assert historical.status_code == 200, historical.text
        body = historical.json()
        assert body["result_id"] == old_header and body["current_result_id"] == new_header
        assert body["freshness"] == "STALE"
        if invalidate_old_card:
            assert body["content_availability"] == "UNAVAILABLE"
            assert body["summary"] is None and body["candidates"] == []
            assert body["anchor_card"] is None
        else:
            assert body["content_availability"] == "AVAILABLE"
            assert [item["candidate_id"] for item in body["candidates"]] == [old_candidate]
            assert body["selected_candidate"]["candidate_id"] != new_candidate


@requires_database
@pytest.mark.parametrize(
    "deleted_parent",
    ["property_unit", "property_complex", "property_listing", "property_requirement", "party"],
)
def test_exact_interaction_and_general_history_hide_deleted_parents(
    config: Config, deleted_parent: str
):
    with ledger_client(config) as (client, session, b, u):
        _run, listing, _card, requirement_id, _header = _stored(client, session, b, u)
        party_id = session.execute(
            text("SELECT party_id FROM property_requirement WHERE id=:id"),
            {"id": requirement_id},
        ).scalar_one()
        complex_id = session.execute(
            text("SELECT complex_id FROM property_unit WHERE id=:id"),
            {"id": listing["unit_id"]},
        ).scalar_one()
        interaction_id = session.execute(
            text("""INSERT INTO client_interaction
                (brokerage_id,unit_id,listing_id,requirement_id,party_id,
                 interaction_at,interaction_content)
                VALUES (:b,:unit,:listing,:requirement,:party,now(),:content) RETURNING id"""),
            {
                "b": b,
                "unit": listing["unit_id"],
                "listing": listing["id"],
                "requirement": requirement_id,
                "party": party_id,
                "content": "SYNTHETIC_DELETED_PARENT_CONSULTATION",
            },
        ).scalar_one()
        session.commit()
        url = f"/api/v1/client-interactions?unit_id={listing['unit_id']}"
        before = client.get(f"{url}&interaction_id={interaction_id}")
        assert before.status_code == 200, before.text
        assert [item["id"] for item in before.json()["items"]] == [interaction_id]
        parent_ids = {
            "property_unit": listing["unit_id"],
            "property_complex": complex_id,
            "property_listing": listing["id"],
            "property_requirement": requirement_id,
            "party": party_id,
        }
        session.execute(
            text(f"UPDATE {deleted_parent} SET is_deleted=true WHERE id=:id"),
            {"id": parent_ids[deleted_parent]},
        )
        session.commit()
        for path in (url, f"{url}&interaction_id={interaction_id}"):
            response = client.get(path)
            assert response.status_code == 200, response.text
            assert response.json()["items"] == [] and response.json()["total"] == 0
            assert "SYNTHETIC_DELETED_PARENT_CONSULTATION" not in response.text


@requires_database
def test_fixture_provenance_is_explicit_without_exposing_internal_snapshot(config: Config):
    with ledger_client(config) as (client, session, b, u):
        run, listing, _card, _candidate, header = _stored(client, session, b, u)
        _current(session, b, run, listing, header)
        path = f"/api/v1/f3/judgment-targets/LISTING/{listing['id']}"
        assert client.get(path).json()["is_synthetic_fixture"] is False
        session.execute(
            text("""UPDATE agent_run SET redacted_output_snapshot=redacted_output_snapshot ||
            '{"synthetic_fixture":{"kind":"DETERMINISTIC_MATCH_SEED",
              "model_inference": false}}'::jsonb
            WHERE id=:run"""),
            {"run": run["run_id"]},
        )
        session.commit()
        for url in (path, f"/api/v1/f3/judgment-results/{header}"):
            response = client.get(url)
            assert response.status_code == 200
            assert response.json()["is_synthetic_fixture"] is True
            assert "redacted_output_snapshot" not in response.text
            assert "DETERMINISTIC_MATCH_SEED" not in response.text
        listing_response = client.get("/api/v1/f3/judgment-results?anchor_type=LISTING")
        assert listing_response.json()["items"][0]["is_synthetic_fixture"] is True
