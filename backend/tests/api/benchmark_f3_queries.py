"""Run with TEST_DB_URL and a synthetic seed. JSON output contains only timings.

Use the same interpreter, database and environment for both revisions. Add the
selected revision's backend/src, backend/tests and backend/tests/api to PYTHONPATH.
Example: python backend/tests/api/benchmark_f3_queries.py --output /tmp/f3-queries.json
"""

import argparse
import json
import math
import os
from pathlib import Path
from statistics import median
from time import perf_counter

from ledger_fixtures import ledger_client
from sqlalchemy import event, text
from sqlmodel import Session, create_engine
from test_f3_results import _queue_listing_run, _store_anchor_card, _store_completed_judgment

from conftest import config_values
from core.config import bind_config
from domain.agent_execution.repository import list_listing_candidates


def repeated(operation, count=30):
    operation()  # Warm statement compilation and connection establishment.
    durations = []
    for _ in range(count):
        started = perf_counter()
        operation()
        durations.append((perf_counter() - started) * 1000)
    return {
        "samples": count,
        "p50_ms": round(median(durations), 3),
        "p95_ms": round(sorted(durations)[math.ceil(0.95 * count) - 1], 3),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--snapshot-only", action="store_true")
    args = parser.parse_args()
    report = {}
    with ledger_client(bind_config(config_values())) as (client, db, b, user):
        run, listing = _queue_listing_run(client, db, b)
        anchor = _store_anchor_card(db, b, run["run_id"], listing["id"])
        _store_completed_judgment(db, b, user, run["run_id"], anchor)
        saved = db.execute(
            text("SELECT candidate_selection_snapshot FROM match_evaluation WHERE agent_run_id=:r"),
            {"r": run["run_id"]},
        ).scalar_one()
        saved["candidates"] += [
            {
                "candidate_id": 100000 + i,
                "rank": i + 3,
                "selected_for_cards": False,
                "score": "0.25",
                "price_amount": 3000000000,
                "received_at": "2026-09-01",
            }
            for i in range(7198)
        ]
        saved.update(total_count=7200, remaining_count=7199)
        db.execute(
            text(
                "UPDATE match_evaluation SET candidate_selection_snapshot=CAST(:s AS jsonb) "
                "WHERE agent_run_id=:r"
            ),
            {"s": json.dumps(saved), "r": run["run_id"]},
        )
        db.commit()
        report["snapshot_read"] = repeated(
            lambda: db.execute(
                text(
                    "SELECT candidate_selection_snapshot FROM match_evaluation "
                    "WHERE agent_run_id=:r"
                ),
                {"r": run["run_id"]},
            ).scalar_one()
        )
        report["snapshot_read"]["json_bytes"] = len(json.dumps(saved).encode())
        if args.snapshot_only:
            args.output.write_text(json.dumps(report, indent=2))
            return
        timings = []

        def before(_c, _cu, _s, _p, ctx, _m):
            ctx._benchmark_started = perf_counter()

        def after(_c, _cu, _s, _p, ctx, _m):
            timings.append((perf_counter() - ctx._benchmark_started) * 1000)

        bind = db.get_bind()
        event.listen(bind, "before_cursor_execute", before)
        event.listen(bind, "after_cursor_execute", after)
        try:
            for name, path in {
                "status": f"/api/v1/f3/runs/{run['run_id']}",
                "first_page": f"/api/v1/f3/runs/{run['run_id']}/result?limit=20",
                "unjudged_page": f"/api/v1/f3/runs/{run['run_id']}/result?limit=20&offset=200",
            }.items():
                counts, sql_ms = [], []

                def request(path=path, counts=counts, sql_ms=sql_ms):
                    timings.clear()
                    response = client.get(path)
                    assert response.status_code == 200
                    counts.append(len(timings))
                    sql_ms.append(sum(timings))

                report[name] = repeated(request)
                report[name].update(sql_count=counts[-1], sql_p50_ms=round(median(sql_ms[1:]), 3))
        finally:
            event.remove(bind, "before_cursor_execute", before)
            event.remove(bind, "after_cursor_execute", after)
    engine = create_engine(os.environ["TEST_DB_URL"])
    try:
        with Session(engine) as db:
            b = db.execute(
                text("SELECT id FROM brokerage WHERE name='F3_SYNTHETIC 합성중개사무소'")
            ).scalar_one()

            def search():
                db.expunge_all()
                return list_listing_candidates(
                    db,
                    b,
                    price_kind="SALE",
                    active_statuses=["RECEIVED"],
                    price_ceiling_amount=None,
                    complex_ids=[],
                )

            row_count = len(search())
            report["listing_search"] = repeated(search)
            report["listing_search"]["rows"] = row_count
    finally:
        engine.dispose()
    args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == "__main__":
    main()
