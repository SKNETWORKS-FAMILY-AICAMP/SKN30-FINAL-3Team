"""Renew a claimed execution during a stage, using short independent transactions."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from sqlalchemy import text
from sqlmodel import Session

from domain.agent_execution import repository
from domain.agent_execution.models import LeaseNotHeldError
from domain.agent_execution.service import LEASE_DURATION_SECONDS

HEARTBEAT_INTERVAL_SECONDS = 30.0


def renew(
    session_factory: Callable[[], Session],
    run_id: int,
    brokerage_id: int,
    worker_id: str,
    attempt_count: int,
) -> bool:
    # A model call must never share its Session with the heartbeat thread.
    with session_factory() as session:
        session.execute(text("SET LOCAL lock_timeout = '2s'"))
        session.execute(text("SET LOCAL statement_timeout = '5s'"))
        changed = repository.renew_lease(
            session, run_id, brokerage_id, worker_id, attempt_count, LEASE_DURATION_SECONDS
        )
        session.commit()
        return changed == 1


async def protect[T](
    operation: Awaitable[T],
    renew_lease: Callable[[], bool],
    *,
    interval: float = HEARTBEAT_INTERVAL_SECONDS,
) -> T:
    """Stop the stage on failed renewal; drain both tasks before another claim."""
    stop = asyncio.Event()

    async def heartbeat() -> None:
        while True:
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
                return
            except TimeoutError:
                pass
            try:
                held = await asyncio.to_thread(renew_lease)
            except Exception as error:
                raise LeaseNotHeldError("lease renewal failed") from error
            if not held:
                raise LeaseNotHeldError("lease renewal lost ownership")

    task = asyncio.ensure_future(operation)
    pulse = asyncio.create_task(heartbeat())
    try:
        await asyncio.wait({task, pulse}, return_when=asyncio.FIRST_COMPLETED)
        if pulse.done():
            await pulse  # Propagate failed renewal before accepting the operation.
        return await task
    finally:
        stop.set()
        if not task.done():
            task.cancel()
        # Do not cancel to_thread: wait for its bounded DB operation to finish,
        # so a renewal cannot escape this stage and run after release/parking.
        await asyncio.gather(task, pulse, return_exceptions=True)
