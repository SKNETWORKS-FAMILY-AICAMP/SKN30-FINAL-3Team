"""Heartbeat lifetime and cancellation, without real model calls or wall-clock leases."""

import asyncio

import pytest

from domain.agent_execution.lease import protect
from domain.agent_execution.models import LeaseNotHeldError


def test_renewal_keeps_long_model_alive_and_stops_after_completion():
    calls = []

    async def scenario():
        ready = asyncio.Event()
        loop = asyncio.get_running_loop()

        def renew():
            calls.append(True)
            if len(calls) == 3:
                loop.call_soon_threadsafe(ready.set)
            return True

        async def model():
            await ready.wait()
            return "stored"

        assert await asyncio.wait_for(protect(model(), renew, interval=0.005), 2) == "stored"
        before = len(calls)
        await asyncio.sleep(0.02)
        assert len(calls) == before

    asyncio.run(scenario())


@pytest.mark.parametrize("raises", [False, True])
def test_failed_renewal_cancels_generation_before_storage(raises):
    events = []

    def renew():
        if raises:
            raise ConnectionError("not logged")
        return False

    async def scenario():
        async def model():
            try:
                await asyncio.Event().wait()
                events.append("store")
            finally:
                events.append("closed")

        with pytest.raises(LeaseNotHeldError):
            await asyncio.wait_for(protect(model(), renew, interval=0.005), 2)

    asyncio.run(scenario())
    assert events == ["closed"]


def test_model_error_stops_heartbeat_and_preserves_error():
    async def scenario():
        async def model():
            raise ValueError("model failed")

        with pytest.raises(ValueError, match="model failed"):
            await protect(model(), lambda: pytest.fail("unneeded renewal"))
        assert not [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]

    asyncio.run(scenario())


def test_shutdown_cancels_model_and_drains_heartbeat():
    async def scenario():
        started = asyncio.Event()
        closed = asyncio.Event()

        async def model():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                closed.set()

        task = asyncio.create_task(protect(model(), lambda: True))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert closed.is_set()
        assert not [other for other in asyncio.all_tasks() if other is not asyncio.current_task()]

    asyncio.run(scenario())
