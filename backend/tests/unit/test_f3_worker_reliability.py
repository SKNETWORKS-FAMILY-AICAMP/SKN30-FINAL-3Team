"""Lease renewals keep ownership fencing and stop after a lost lease or handler exit."""

import threading
import time
from unittest.mock import MagicMock
from uuid import UUID

from sqlalchemy import Engine

import f3_worker_reliability as reliability
from domain.agent_execution.models import AgentRun


def test_heartbeat_renews_same_attempt_and_stops_when_owner_lost(monkeypatch):
    observed = threading.Event()
    session = MagicMock()
    session.__enter__.return_value = session
    session.execute.return_value.rowcount = 0
    session.commit.side_effect = observed.set
    monkeypatch.setattr(reliability, "Session", lambda _: session)
    run = AgentRun(
        id=31,
        brokerage_id=4,
        lease_owner="worker-a",
        attempt_count=2,
        run_group_id=UUID("00000000-0000-0000-0000-000000000001"),
        run_type="CROSS_JUDGMENT",
        agent_type="BROKERAGE_WORKFLOW",
        trigger_type="AUTO_CHANGE",
        requested_by=8,
    )
    with reliability.renew_lease(MagicMock(spec=Engine), run, "worker-a", interval_seconds=0.005):
        assert observed.wait(1), "heartbeat did not execute"
        time.sleep(0.025)
    assert session.execute.call_count == 1
    params = session.execute.call_args.args[1]
    assert params == {"id": 31, "tenant": 4, "owner": "worker-a", "attempt": 2, "duration": 300}


def test_handler_exit_stops_heartbeat_before_next_interval(monkeypatch):
    session = MagicMock()
    session.__enter__.return_value = session
    monkeypatch.setattr(reliability, "Session", lambda _: session)
    run = MagicMock(spec=AgentRun, id=31, brokerage_id=4, attempt_count=2)
    with reliability.renew_lease(MagicMock(spec=Engine), run, "worker-a", interval_seconds=1):
        pass
    session.execute.assert_not_called()


def test_consumer_runs_independently_while_handler_is_busy(monkeypatch):
    from domain.agent_execution import automation

    observed = threading.Event()
    session = MagicMock()
    session.__enter__.return_value = session
    monkeypatch.setattr(reliability, "Session", lambda _: session)

    def tick(*_args, **_kwargs):
        observed.set()
        return 1

    monkeypatch.setattr(automation, "tick", tick)
    with reliability.maintain_automation(MagicMock(spec=Engine), threading.Event(), enabled=True):
        # The main Worker execution thread can wait for inference while consumption proceeds.
        assert observed.wait(1)
