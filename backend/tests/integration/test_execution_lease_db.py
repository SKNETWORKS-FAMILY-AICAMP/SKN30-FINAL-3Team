"""PostgreSQL owner/attempt fencing and recovery after missing heartbeats."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from test_agent_run_claim import WORKER_A, WORKER_B, claim_session, insert_run, requires_database

from domain.agent_execution import repository, service


@requires_database
@pytest.mark.parametrize(
    "field,value",
    [
        ("lease_owner", WORKER_B),
        ("attempt_count", 2),
        ("status", "COMPLETED"),
        ("status", "FAILED_TERMINAL"),
        ("status", "SUPERSEDED"),
        ("lease_expires_at", None),
        ("lease_expires_at", datetime.now(UTC) - timedelta(seconds=1)),
    ],
)
def test_renew_does_not_revive_lost_or_terminal_lease(field, value):
    with claim_session() as (session, brokerage_id, user_id):
        args: dict[str, Any] = dict(
            status="RUNNING",
            attempt_count=1,
            lease_owner=WORKER_A,
            lease_expires_at=datetime.now(UTC) + timedelta(seconds=60),
        )
        args[field] = value
        run_id = insert_run(session, brokerage_id, user_id, **args)
        assert repository.renew_lease(session, run_id, brokerage_id, WORKER_A, 1, 300) == 0


@requires_database
def test_long_execution_renewal_preserves_attempt_and_excludes_other_worker():
    with claim_session() as (session, brokerage_id, user_id):
        run_id = insert_run(
            session,
            brokerage_id,
            user_id,
            status="JUDGING",
            attempt_count=2,
            lease_owner=WORKER_A,
            started_at=datetime.now(UTC) - timedelta(seconds=360),
            lease_expires_at=datetime.now(UTC) + timedelta(seconds=1),
        )
        assert repository.renew_lease(session, run_id, brokerage_id + 1, WORKER_A, 2, 300) == 0
        assert repository.renew_lease(session, run_id, brokerage_id, WORKER_A, 2, 300) == 1
        assert service.claim_next_run(session, WORKER_B) is None
        row = session.execute(
            text(
                "SELECT attempt_count, extract(epoch from (lease_expires_at-now())) "
                "FROM agent_run WHERE id=:id"
            ),
            {"id": run_id},
        ).one()
        assert row[0] == 2
        assert 290 < row[1] <= 300
        session.execute(
            text("UPDATE agent_run SET lease_expires_at=now()-interval '1 second' WHERE id=:id"),
            {"id": run_id},
        )
        recovered = service.claim_next_run(session, WORKER_B)
        assert recovered is not None and recovered.id == run_id
        assert recovered.attempt_count == 3
        assert repository.renew_lease(session, run_id, brokerage_id, WORKER_A, 2, 300) == 0


@requires_database
def test_parked_anchor_and_released_retry_cannot_be_renewed():
    with claim_session() as (session, brokerage_id, user_id):
        run_id = insert_run(
            session,
            brokerage_id,
            user_id,
            status="ANCHOR_READY",
            attempt_count=1,
            trigger_type="LEDGER_SAVE",
            lease_owner=WORKER_A,
            lease_expires_at=datetime.now(UTC) + timedelta(seconds=60),
        )
        assert repository.park_ledger_save_run(session, run_id, brokerage_id, WORKER_A, 1) == 1
        assert repository.renew_lease(session, run_id, brokerage_id, WORKER_A, 1, 300) == 0
        retry_id = insert_run(
            session,
            brokerage_id,
            user_id,
            status="CANDIDATES_READY",
            attempt_count=1,
            lease_owner=WORKER_A,
            lease_expires_at=datetime.now(UTC) + timedelta(seconds=60),
        )
        assert repository.release_lease(session, retry_id, brokerage_id, WORKER_A, 1) == 1
        assert repository.renew_lease(session, retry_id, brokerage_id, WORKER_A, 1, 300) == 0


@requires_database
def test_independent_heartbeat_commits_without_sharing_work_session():
    import os

    from sqlmodel import Session, create_engine
    from test_agent_run_claim import committed_runs

    from domain.agent_execution.lease import renew

    engine = create_engine(os.environ["TEST_DB_URL"])
    try:
        with committed_runs(1) as run_ids, Session(engine) as work:
            claimed = service.claim_next_run(work, WORKER_A)
            assert claimed is not None and claimed.id is not None
            assert claimed.id == run_ids[0]
            run_id, b, attempt = claimed.id, claimed.brokerage_id, claimed.attempt_count
            work.rollback()
            assert not work.in_transaction()
            assert renew(lambda: Session(engine), run_id, b, WORKER_A, attempt)
            assert not work.in_transaction()
            with Session(engine) as observer:
                assert service.claim_next_run(observer, WORKER_B) is None
                assert repository.find_leased_run(observer, run_id, WORKER_A, attempt) is not None
    finally:
        engine.dispose()


@requires_database
def test_killed_generation_process_is_reclaimed_after_last_heartbeat_expires():
    import os
    import select
    import subprocess
    import sys
    from pathlib import Path

    from sqlmodel import Session, create_engine
    from test_agent_run_claim import committed_runs

    # A real child process holds an indefinitely waiting model double. Advance
    # only the persisted expiration after SIGKILL instead of sleeping 300 seconds.
    child_code = """
import asyncio, os, sys
from sqlmodel import Session, create_engine
from domain.agent_execution.lease import protect, renew
engine = create_engine(os.environ['TEST_DB_URL'])
run_id, brokerage_id, attempt = map(int, sys.argv[1:4])
def heartbeat():
    held = renew(lambda: Session(engine), run_id, brokerage_id, sys.argv[4], attempt)
    print('HEARTBEAT' if held else 'LOST', flush=True)
    return held
async def model():
    await asyncio.Event().wait()
asyncio.run(protect(model(), heartbeat, interval=0.02))
"""
    engine = create_engine(os.environ["TEST_DB_URL"])
    process = None
    try:
        with committed_runs(1) as run_ids, Session(engine) as work:
            claimed = service.claim_next_run(work, WORKER_A)
            assert claimed is not None and claimed.id is not None
            assert claimed.id == run_ids[0]
            run_id, b, attempt = claimed.id, claimed.brokerage_id, claimed.attempt_count
            work.rollback()
            env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2] / "src"))
            process = subprocess.Popen(
                [sys.executable, "-c", child_code, str(run_id), str(b), str(attempt), WORKER_A],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            assert process.stdout is not None
            assert select.select([process.stdout], [], [], 15)[0], "heartbeat did not start"
            assert process.stdout.readline().strip() == "HEARTBEAT"
            assert service.claim_next_run(work, WORKER_B) is None
            process.kill()
            process.wait(timeout=5)
            work.execute(
                text(
                    "UPDATE agent_run SET lease_expires_at=now()-interval '1 second' WHERE id=:id"
                ),
                {"id": run_id},
            )
            work.commit()
            recovered = service.claim_next_run(work, WORKER_B)
            assert recovered is not None and recovered.id == run_id
            assert recovered.attempt_count == attempt + 1
            assert repository.renew_lease(work, run_id, b, WORKER_A, attempt, 300) == 0
    finally:
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            if process.stdout is not None:
                process.stdout.close()
        engine.dispose()
