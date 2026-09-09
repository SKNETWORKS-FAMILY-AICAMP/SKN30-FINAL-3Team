"""Cross-host F3 execution slot and lease renewal, independent of API process memory."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, cast

import structlog
from sqlalchemy import CursorResult, Engine, text
from sqlmodel import Session

from domain.agent_execution.models import AgentRun

logger = structlog.get_logger()
F3_EXECUTION_SLOT = 0x46330002


@contextmanager
def execution_slot(engine: Engine) -> Iterator[bool]:
    # Session advisory lock on a dedicated autocommit connection: no transaction or row
    # lock is kept open while waiting for a model. A dead process releases it automatically.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        acquired = bool(
            connection.execute(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": F3_EXECUTION_SLOT}
            ).scalar()
        )
        try:
            yield acquired
        finally:
            if acquired:
                connection.execute(
                    text("SELECT pg_advisory_unlock(:key)"), {"key": F3_EXECUTION_SLOT}
                )


@contextmanager
def renew_lease(
    engine: Engine,
    run: AgentRun,
    worker_id: str,
    *,
    interval_seconds: float = 30,
    lease_seconds: int = 300,
) -> Iterator[None]:
    stop = threading.Event()
    # Copy scalar fencing values before another session refreshes the SQLModel object.
    params = {
        "id": run.id,
        "tenant": run.brokerage_id,
        "owner": worker_id,
        "attempt": run.attempt_count,
        "duration": lease_seconds,
    }

    def heartbeat() -> None:
        while not stop.wait(interval_seconds):
            try:
                with Session(engine) as session:
                    changed = cast(
                        CursorResult[Any],
                        session.execute(
                            text("""UPDATE agent_run
                        SET lease_expires_at=now()+make_interval(secs => :duration)
                        WHERE id=:id AND brokerage_id=:tenant AND lease_owner=:owner
                          AND attempt_count=:attempt AND lease_expires_at>now()
                          AND status IN ('RUNNING','ANCHOR_READY','CANDIDATES_READY',
                              'CANDIDATE_CARDS_READY','JUDGING')"""),
                            params,
                        ),
                    ).rowcount
                    session.commit()
                    if changed != 1:
                        return
            except Exception as error:
                logger.warning(
                    "f3_heartbeat_failed", run_id=params["id"], error_type=type(error).__name__
                )
                # Existing lease fencing prevents a late write if recovery loses ownership.

    thread = threading.Thread(target=heartbeat, name="f3-lease-renewal", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=2)


@contextmanager
def maintain_automation(
    engine: Engine,
    stop_event: threading.Event,
    *,
    enabled: bool,
    debounce_seconds: int = 3,
    batch_size: int = 20,
) -> Iterator[None]:
    """Consume source events during slow inference using independent, short DB sessions."""
    from time import monotonic

    from domain.agent_execution import automation

    if not enabled:
        yield
        return
    done = threading.Event()

    def consume() -> None:
        last_sweep = 0.0
        while not stop_event.is_set() and not done.is_set():
            try:
                with Session(engine) as session:
                    sweep = monotonic() - last_sweep >= 60
                    automation.tick(
                        session,
                        debounce_seconds=debounce_seconds,
                        batch_size=batch_size,
                        sweep=sweep,
                    )
                    if sweep:
                        last_sweep = monotonic()
            except Exception as error:
                logger.warning("f3_consumer_retry", error_type=type(error).__name__)
            done.wait(2)

    thread = threading.Thread(target=consume, name="f3-event-consumer", daemon=True)
    thread.start()
    try:
        yield
    finally:
        done.set()
        thread.join(timeout=5)
        if thread.is_alive():
            logger.warning("f3_consumer_drain_pending")
