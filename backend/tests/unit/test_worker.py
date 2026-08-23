"""Worker 프로세스의 기동·polling·종료.

실제 Provider 도 DB 도 쓰지 않는다. handler 와 session 을 대역으로 바꿔 loop 자체만 본다.
단계 처리의 정확성은 통합 테스트가 따로 본다.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest

from core.errors import ConfigurationError
from worker import (
    WORKER_ID_MAX_LENGTH,
    build_worker_id,
    require_ai_provider,
    run_disabled_worker,
    run_worker_loop,
    worker_enabled,
)


def test_worker_enabled_rejects_invalid_value() -> None:
    with pytest.raises(ConfigurationError, match="WORKER_ENABLED"):
        worker_enabled({"WORKER_ENABLED": "sometimes"})


def test_worker_enabled_reads_both_spellings() -> None:
    assert worker_enabled({"WORKER_ENABLED": "true"}) is True
    assert worker_enabled({"WORKER_ENABLED": "1"}) is True
    assert worker_enabled({"WORKER_ENABLED": "off"}) is False
    assert worker_enabled({}) is False


def test_disabled_worker_checks_readiness_without_claiming(tmp_path: Path) -> None:
    ready_file = tmp_path / "worker-ready"
    stop_event = threading.Event()
    stop_event.set()
    probes: list[str] = []

    run_disabled_worker(
        stop_event=stop_event,
        ready_file=ready_file,
        readiness_probe=lambda: probes.append("ready"),
    )

    assert probes == ["ready"]
    assert not ready_file.exists()


# ── worker_id ──────────────────────────────────────────────────────────────────


def test_the_worker_id_fits_the_lease_owner_column() -> None:
    """`agent_run.lease_owner` 가 VARCHAR(64) 다. 넘치면 fencing 이 조용히 어긋난다."""
    assert len(build_worker_id({})) <= WORKER_ID_MAX_LENGTH


def test_two_worker_ids_differ() -> None:
    assert build_worker_id({}) != build_worker_id({})


def test_a_configured_worker_id_is_used_and_clipped() -> None:
    assert build_worker_id({"WORKER_ID": "fixed-worker"}) == "fixed-worker"
    assert len(build_worker_id({"WORKER_ID": "x" * 200})) == WORKER_ID_MAX_LENGTH


# ── 기동 설정 ──────────────────────────────────────────────────────────────────


def test_starting_without_any_llm_provider_is_refused() -> None:
    """실행을 집기 전에 거부한다. 집은 뒤에 알면 그 실행이 시도 횟수만 소모한다."""
    with pytest.raises(ConfigurationError, match="LLM provider"):
        require_ai_provider("test", {})


def test_a_configured_provider_passes_startup() -> None:
    config = require_ai_provider("test", {"AI_VLLM_LLM_BASE_URL": "http://localhost:8000/v1"})
    assert config.vllm.llm is not None


# ── polling loop ───────────────────────────────────────────────────────────────


class FakeSession:
    """`with` 로 열고 닫히는지만 본다."""

    def __init__(self) -> None:
        self.closed = False

    def __enter__(self) -> FakeSession:
        return self

    def __exit__(self, *_: object) -> None:
        self.closed = True


class FakeRun:
    def __init__(self, run_id: int) -> None:
        self.id = run_id


def loop_with(
    claims: list[Any],
    *,
    stop_event: threading.Event | None = None,
    on_handle=None,
) -> tuple[int, list[Any], FakeSession, list[float]]:
    """`claim_next_run` 이 정해진 순서로 돌려주도록 바꿔 loop 를 돌린다."""
    import worker

    session = FakeSession()
    handled: list[Any] = []
    waits: list[float] = []
    event = stop_event or threading.Event()
    remaining = list(claims)

    def claim(_session: object, _worker_id: str) -> Any:
        return remaining.pop(0) if remaining else None

    def handle(_session: object, run: Any) -> None:
        handled.append(run)
        if on_handle is not None:
            on_handle(run)

    class RecordingEvent:
        def is_set(self) -> bool:
            return event.is_set()

        def wait(self, timeout: float | None = None) -> bool:
            waits.append(timeout or 0.0)
            # 대기가 곧 종료다. 실제 시간을 쓰지 않는다.
            event.set()
            return True

    original = worker.service.claim_next_run
    worker.service.claim_next_run = claim  # type: ignore[assignment]
    try:
        count = run_worker_loop(
            stop_event=RecordingEvent(),  # type: ignore[arg-type]
            session_factory=lambda: session,  # type: ignore[arg-type,return-value]
            handle=handle,
            worker_id="worker-test",
            idle_wait_seconds=0.25,
        )
    finally:
        worker.service.claim_next_run = original  # type: ignore[assignment]
    return count, handled, session, waits


def test_an_empty_queue_waits_on_the_stop_event_instead_of_spinning() -> None:
    count, handled, session, waits = loop_with([])

    assert count == 0
    assert handled == []
    assert waits == [0.25], "busy loop 를 만들지 않고 timeout 으로 기다린다"
    assert session.closed


def test_a_claimed_run_is_handed_to_the_handler() -> None:
    first = FakeRun(11)
    count, handled, _, _ = loop_with([first])

    assert count == 1
    assert handled == [first]


def test_the_loop_drains_the_queue_before_waiting() -> None:
    runs = [FakeRun(1), FakeRun(2), FakeRun(3)]
    count, handled, _, waits = loop_with(runs)

    assert count == 3
    assert handled == runs
    assert waits == [0.25]


def test_a_stop_request_ends_the_loop_after_the_current_run() -> None:
    """처리 중인 한 실행은 안전한 단계까지 마치고 종료한다."""
    stop_event = threading.Event()
    runs = [FakeRun(1), FakeRun(2)]

    count, handled, _, _ = loop_with(
        runs, stop_event=stop_event, on_handle=lambda _run: stop_event.set()
    )

    assert count == 1
    assert [run.id for run in handled] == [1]


def test_a_stop_request_before_the_first_claim_handles_nothing() -> None:
    stop_event = threading.Event()
    stop_event.set()

    count, handled, session, _ = loop_with([FakeRun(1)], stop_event=stop_event)

    assert count == 0
    assert handled == []
    assert session.closed
