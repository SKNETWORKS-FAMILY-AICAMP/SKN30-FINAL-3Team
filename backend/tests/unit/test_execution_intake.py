from __future__ import annotations

from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from domain.agent_execution import service
from domain.agent_execution.models import AgentRun, AnchorType


class IntakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def refresh(self, _run: AgentRun) -> None:
        pass


@pytest.mark.parametrize("status", ["QUEUED", "RUNNING", "ANCHOR_READY"])
def test_user_request_promotes_ledger_save_run_in_every_handoff_state(
    monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    """버튼을 누른 시점과 무관하게 같은 자동 접수 실행이 사용자 요청을 기억한다."""
    existing = AgentRun(
        id=17,
        brokerage_id=3,
        run_group_id=uuid4(),
        run_type="CROSS_JUDGMENT",
        agent_type="BROKERAGE_WORKFLOW",
        status=status,
        trigger_type="LEDGER_SAVE",
        requested_by=4,
        target_listing_id=9,
        input_data_version=2,
    )
    resumed: list[tuple[int, int, str]] = []

    monkeypatch.setattr(service.repository, "lock_run_intake", lambda *_args: None)
    monkeypatch.setattr(
        service,
        "resolve_anchor",
        lambda *_args: service.ResolvedAnchor(
            anchor_type=AnchorType.LISTING,
            anchor_id=9,
            input_data_version=2,
            target_listing_id=9,
            target_unit_id=None,
            target_requirement_id=None,
        ),
    )
    monkeypatch.setattr(service.repository, "find_reusable_active_run", lambda *_args: existing)

    def resume(_session: Session, run_id: int, brokerage_id: int, trigger_type: str) -> int:
        resumed.append((run_id, brokerage_id, trigger_type))
        existing.trigger_type = trigger_type
        return 1

    monkeypatch.setattr(service.repository, "resume_ledger_save_run", resume)
    session = IntakeSession()

    result = service.queue_cross_judgment_run(
        cast(Session, session),
        brokerage_id=3,
        requested_by=8,
        anchor_type=AnchorType.LISTING,
        anchor_id=9,
    )

    assert result is existing
    assert resumed == [(17, 3, "USER_REQUEST")]
    assert result.trigger_type == "USER_REQUEST"
    assert result.requested_by == 4
    assert session.commits == 1
    assert session.rollbacks == 0


def test_attempt_exhaustion_emits_one_terminal_event_after_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = IntakeSession()
    events: list[tuple[str, dict[str, object], int]] = []

    class RecordingLogger:
        def error(self, event: str, **values: object) -> None:
            events.append((event, values, session.commits))

    monkeypatch.setattr(service, "logger", RecordingLogger())
    monkeypatch.setattr(
        service.repository,
        "fail_runs_over_attempt_limit",
        lambda *_args: 2,
    )
    monkeypatch.setattr(service.repository, "lock_claimable_run", lambda *_args: None)

    claimed = service.claim_next_run(cast(Session, session), "worker-test")

    assert claimed is None
    assert events == [
        (
            "ai_terminal_failure",
            {
                "component": "ai",
                "source": "f3",
                "status": "FAILED_TERMINAL",
                "failure_stage": "EXECUTION",
                "attempt": service.MAX_CLAIM_ATTEMPTS,
                "failure_category": "LEASE",
                "error_code": "LEASE_EXPIRED_MAX_ATTEMPTS",
                "error_type": "AttemptLimitExceeded",
                "terminal_count": 2,
            },
            1,
        )
    ]


def test_attempt_exhaustion_does_not_log_when_commit_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingSession(IntakeSession):
        def commit(self) -> None:
            raise SQLAlchemyError("commit failed")

    events: list[str] = []

    class RecordingLogger:
        def error(self, event: str, **_values: object) -> None:
            events.append(event)

    session = FailingSession()
    monkeypatch.setattr(service, "logger", RecordingLogger())
    monkeypatch.setattr(
        service.repository,
        "fail_runs_over_attempt_limit",
        lambda *_args: 1,
    )
    monkeypatch.setattr(service.repository, "lock_claimable_run", lambda *_args: None)

    with pytest.raises(SQLAlchemyError, match="commit failed"):
        service.claim_next_run(cast(Session, session), "worker-test")

    assert session.rollbacks == 1
    assert events == []
