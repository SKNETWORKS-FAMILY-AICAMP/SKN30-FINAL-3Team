"""Pages preserve valid-candidate order/count without materializing other pages."""

import json
from unittest.mock import patch

import pytest
from ledger_fixtures import ledger_client, requires_database
from sqlalchemy import text
from test_f3_results import _queue_listing_run, _store_anchor_card, _store_completed_judgment

from domain.agent_execution import results


@requires_database
@pytest.mark.parametrize("schema", ["candidate-selection:v2", "candidate-selection:v3"])
@pytest.mark.parametrize("count", [0, 5, 6, 7200])
def test_page_builds_only_requested_valid_entries(config, schema, count):
    with ledger_client(config) as (client, session, b, user):
        run, listing = _queue_listing_run(client, session, b)
        anchor = _store_anchor_card(session, b, run["run_id"], listing["id"])
        _store_completed_judgment(session, b, user, run["run_id"], anchor, selection_schema=schema)
        snapshot = session.execute(
            text("SELECT candidate_selection_snapshot FROM match_evaluation WHERE agent_run_id=:r"),
            {"r": run["run_id"]},
        ).scalar_one()
        entries = [
            {"candidate_id": 100000 + i, "rank": i + 1, "selected_for_cards": False}
            for i in range(count)
        ]
        # Invalid entries must not consume a position in a page or the total.
        entries.insert(0, {"candidate_id": "invalid"})
        snapshot.update(
            candidates=entries, candidate_cards=[], carded_count=0, remaining_count=count
        )
        snapshot.pop("total_count", None)  # exercise the historical fallback
        session.execute(
            text(
                "UPDATE match_evaluation SET candidate_selection_snapshot=CAST(:s AS jsonb) "
                "WHERE agent_run_id=:r"
            ),
            {"s": json.dumps(snapshot), "r": run["run_id"]},
        )
        session.commit()
        for offset in (0, 4, count, count + 1):
            expected = list(range(100000 + offset, 100000 + min(count, offset + 2)))
            with patch.object(results, "CandidateView", wraps=results.CandidateView) as constructor:
                response = client.get(
                    f"/api/v1/f3/runs/{run['run_id']}/result?limit=2&offset={offset}"
                )
                assert response.status_code == 200
                body = response.json()
                assert body["candidates_total"] == count
                assert body["candidate_selection"]["total_count"] == count
                assert [entry["candidate_id"] for entry in body["candidates"]] == expected
                assert constructor.call_count == len(expected)


@requires_database
def test_unjudged_page_does_not_fetch_other_pages_judgment_or_evidence(config):
    from sqlalchemy import event

    with ledger_client(config) as (client, session, b, user):
        run, listing = _queue_listing_run(client, session, b)
        anchor = _store_anchor_card(session, b, run["run_id"], listing["id"])
        _store_completed_judgment(session, b, user, run["run_id"], anchor)
        statements = []
        bind = session.get_bind()

        def collect(_c, _cu, statement, _p, _ctx, _many):
            statements.append(statement)

        event.listen(bind, "before_cursor_execute", collect)
        try:
            body = client.get(f"/api/v1/f3/runs/{run['run_id']}/result?limit=1&offset=1").json()
        finally:
            event.remove(bind, "before_cursor_execute", collect)
        assert body["candidates_total"] == 2
        assert body["candidates"][0]["judgment_id"] is None
        assert not any(
            "FROM match_candidate_evaluation" in s or "FROM match_candidate_evidence" in s
            for s in statements
        )
        first = client.get(f"/api/v1/f3/runs/{run['run_id']}/result?limit=1").json()
        assert first["candidates"][0]["judgment_id"] is not None
        assert first["candidates"][0]["evidence"]
