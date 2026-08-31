"""F3 상태 기반 실행 조율과 실패 분류의 단위 계약."""

from __future__ import annotations

import asyncio
from typing import Any, cast
from uuid import uuid4

import pytest
from brokerage_ai.core.errors import (
    ProviderOutputInvalidError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from brokerage_ai.f3 import BrokerageJudgmentContractError, PositionCardContractError
from sqlmodel import Session

from domain.agent_execution import pipeline
from domain.agent_execution.anchor_card import CachedCardUnavailableError, SourceChangedError
from domain.agent_execution.models import (
    SUPERSEDED_FAILURE_MESSAGE,
    AgentRun,
    InputVersionChangedError,
    LeaseNotHeldError,
)


def run_in(status: str = "RUNNING") -> AgentRun:
    return AgentRun(
        id=17,
        brokerage_id=3,
        run_group_id=uuid4(),
        run_type="CROSS_JUDGMENT",
        agent_type="BROKERAGE_WORKFLOW",
        status=status,
        trigger_type="USER_REQUEST",
        requested_by=4,
        attempt_count=2,
    )


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (LeaseNotHeldError("lost"), pipeline.StepOutcome.LEASE_LOST),
        (InputVersionChangedError("changed"), pipeline.StepOutcome.SUPERSEDED),
        (SourceChangedError("changed"), pipeline.StepOutcome.SUPERSEDED),
        (CachedCardUnavailableError("gone"), pipeline.StepOutcome.RETRY),
        (ProviderTimeoutError(), pipeline.StepOutcome.RETRY),
        (ProviderResponseError(), pipeline.StepOutcome.FAILED_TERMINAL),
        (PositionCardContractError("invalid"), pipeline.StepOutcome.FAILED_TERMINAL),
        (BrokerageJudgmentContractError("invalid"), pipeline.StepOutcome.FAILED_TERMINAL),
        (RuntimeError("unknown"), pipeline.StepOutcome.RETRY),
    ],
)
def test_errors_have_one_execution_outcome(
    error: BaseException,
    expected: pipeline.StepOutcome,
) -> None:
    assert pipeline.classify(error) is expected


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("RUNNING", pipeline.FailureStage.ANCHOR_CARD),
        ("ANCHOR_READY", pipeline.FailureStage.CANDIDATE_SELECTION),
        ("CANDIDATES_READY", pipeline.FailureStage.CANDIDATE_CARDS),
        ("CANDIDATE_CARDS_READY", pipeline.FailureStage.JUDGMENT),
        ("JUDGING", pipeline.FailureStage.JUDGMENT),
        ("QUEUED", pipeline.FailureStage.EXECUTION),
    ],
)
def test_saved_status_has_a_safe_failure_stage(
    status: str, expected: pipeline.FailureStage
) -> None:
    assert pipeline.failure_stage(status) is expected


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (LeaseNotHeldError("raw"), pipeline.FailureCategory.LEASE),
        (InputVersionChangedError("raw"), pipeline.FailureCategory.INPUT_CHANGED),
        (CachedCardUnavailableError("raw"), pipeline.FailureCategory.CACHE_INVALIDATED),
        (ProviderOutputInvalidError("raw"), pipeline.FailureCategory.OUTPUT_CONTRACT),
        (ProviderTimeoutError(), pipeline.FailureCategory.PROVIDER_TIMEOUT),
        (ProviderRateLimitError(), pipeline.FailureCategory.PROVIDER_RATE_LIMIT),
        (ProviderResponseError(), pipeline.FailureCategory.PROVIDER_RESPONSE),
        (PositionCardContractError("raw"), pipeline.FailureCategory.OUTPUT_CONTRACT),
        (RuntimeError("raw"), pipeline.FailureCategory.UNKNOWN),
    ],
)
def test_errors_have_a_safe_failure_category(
    error: BaseException, expected: pipeline.FailureCategory
) -> None:
    assert pipeline.failure_category(error) is expected


@pytest.mark.parametrize(
    ("status", "called", "expected"),
    [
        ("RUNNING", "anchor", pipeline.StepOutcome.ADVANCED),
        ("ANCHOR_READY", "candidates", pipeline.StepOutcome.ADVANCED),
        ("CANDIDATES_READY", "candidate_cards", pipeline.StepOutcome.ADVANCED),
        ("CANDIDATE_CARDS_READY", "judgment", pipeline.StepOutcome.COMPLETED),
        ("JUDGING", "judgment", pipeline.StepOutcome.COMPLETED),
        ("COMPLETED", None, pipeline.StepOutcome.SKIPPED),
    ],
)
def test_saved_status_selects_exactly_one_stage(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    called: str | None,
    expected: pipeline.StepOutcome,
) -> None:
    calls: list[str] = []

    async def anchor(*_args: Any, **_kwargs: Any) -> None:
        calls.append("anchor")

    def candidates(*_args: Any, **_kwargs: Any) -> None:
        calls.append("candidates")

    async def candidate_cards(*_args: Any, **_kwargs: Any) -> None:
        calls.append("candidate_cards")

    async def judgment(*_args: Any, **_kwargs: Any) -> None:
        calls.append("judgment")

    monkeypatch.setattr(pipeline, "generate_and_store_anchor_position_card", anchor)
    monkeypatch.setattr(pipeline, "store_candidate_selection", candidates)
    monkeypatch.setattr(pipeline, "generate_and_store_candidate_cards", candidate_cards)
    monkeypatch.setattr(pipeline, "judge_and_store", judgment)
    bindings = pipeline.ExecutionBindings(
        card=cast(Any, object()),
        judgment=cast(Any, object()),
    )

    result = asyncio.run(
        pipeline._advance(
            cast(Session, object()),
            run_in(status),
            "worker-test",
            bindings,
        )
    )

    assert result is expected
    assert calls == ([] if called is None else [called])


class RecordingSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def advance_with_error(
    monkeypatch: pytest.MonkeyPatch,
    error: BaseException,
    *,
    fail_count: int = 1,
    release_count: int = 1,
) -> tuple[pipeline.StepOutcome, RecordingSession, list[dict[str, object]]]:
    async def explode(*_args: Any, **_kwargs: Any) -> pipeline.StepOutcome:
        raise error

    session = RecordingSession()
    failure_calls: list[dict[str, object]] = []
    monkeypatch.setattr(pipeline, "_advance", explode)
    monkeypatch.setattr(
        pipeline.repository,
        "release_lease",
        lambda *_args, **_kwargs: release_count,
    )

    def fail(*_args: Any, **kwargs: object) -> int:
        failure_calls.append(kwargs)
        return fail_count

    monkeypatch.setattr(pipeline.repository, "fail_run", fail)
    loop = asyncio.new_event_loop()
    try:
        outcome = pipeline.advance_run(
            cast(Session, session),
            run_in(),
            "worker-test",
            cast(pipeline.ExecutionBindings, object()),
            loop,
        )
    finally:
        loop.close()
    return outcome, session, failure_calls


def test_retry_releases_the_lease_without_changing_the_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcome, session, failure_calls = advance_with_error(monkeypatch, ProviderTimeoutError())

    assert outcome is pipeline.StepOutcome.RETRY
    assert session.commits == 1
    assert failure_calls == []


def test_changed_input_stores_only_the_fixed_superseded_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_message = "customer phone 010-0000-0000"
    outcome, session, failure_calls = advance_with_error(
        monkeypatch, InputVersionChangedError(raw_message)
    )

    assert outcome is pipeline.StepOutcome.SUPERSEDED
    assert session.commits == 1
    assert failure_calls == [
        {
            "status": "SUPERSEDED",
            "failure_code": "INPUT_SUPERSEDED",
            "failure_message": SUPERSEDED_FAILURE_MESSAGE,
        }
    ]
    assert raw_message not in repr(failure_calls)


def test_contract_failure_stores_a_generic_terminal_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcome, _, failure_calls = advance_with_error(
        monkeypatch, PositionCardContractError("model output body")
    )

    assert outcome is pipeline.StepOutcome.FAILED_TERMINAL
    assert failure_calls[0]["failure_code"] == "EXECUTION_FAILED"
    assert "model output body" not in repr(failure_calls)


def test_failure_log_contains_only_safe_classification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_message = "customer phone 010-0000-0000"
    events: list[tuple[str, dict[str, object]]] = []

    class RecordingLogger:
        def warning(self, event: str, **values: object) -> None:
            events.append((event, values))

    monkeypatch.setattr(pipeline, "logger", RecordingLogger())
    outcome, _, _ = advance_with_error(
        monkeypatch, PositionCardContractError(raw_message)
    )

    assert outcome is pipeline.StepOutcome.FAILED_TERMINAL
    assert events == [
        (
            "f3_step_failed",
            {
                "run_id": 17,
                "status": "RUNNING",
                "failure_stage": "ANCHOR_CARD",
                "attempt": 2,
                "outcome": "FAILED_TERMINAL",
                "failure_category": "OUTPUT_CONTRACT",
                "error_type": "PositionCardContractError",
            },
        )
    ]
    assert raw_message not in repr(events)


@pytest.mark.parametrize("kind", ["retry", "failure"])
def test_late_worker_result_is_treated_as_a_lost_lease(
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    error: BaseException = (
        ProviderTimeoutError() if kind == "retry" else PositionCardContractError("invalid")
    )
    outcome, session, _ = advance_with_error(
        monkeypatch,
        error,
        release_count=0,
        fail_count=0,
    )

    assert outcome is pipeline.StepOutcome.LEASE_LOST
    assert session.rollbacks == 1
