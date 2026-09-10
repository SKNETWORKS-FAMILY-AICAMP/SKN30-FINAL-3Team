"""Worker 기동 설정, polling과 실행별 오류 격리."""

from __future__ import annotations

import asyncio
import os
import threading
from pathlib import Path
from typing import Any, cast

import pytest
from brokerage_ai.core.config import AiProfile
from brokerage_ai.runtime import AiRuntime
from sqlmodel import Session, create_engine

from conftest import config_values
from core.config import bind_config
from core.errors import ConfigurationError
from domain.agent_execution.anchor_card import GenerationBindingError
from domain.agent_execution.models import AgentRun
from worker import (
    WORKER_ID_MAX_LENGTH,
    build_worker_id,
    process_run,
    require_ai_provider,
    require_synthetic_prototype_opt_in,
    run_enabled_worker,
    run_worker_loop,
)


@pytest.mark.parametrize("allowed", ["", "false", "off"])
def test_enabled_worker_requires_explicit_synthetic_prototype_opt_in(allowed: str) -> None:
    config = bind_config(config_values(F3_ALLOW_SYNTHETIC_PROTOTYPE=allowed))
    with pytest.raises(ConfigurationError, match="F3_ALLOW_SYNTHETIC_PROTOTYPE=true"):
        require_synthetic_prototype_opt_in(config)


def test_enabled_worker_uses_resolved_opt_in() -> None:
    config = bind_config(config_values(F3_ALLOW_SYNTHETIC_PROTOTYPE="true"))
    require_synthetic_prototype_opt_in(config)


def test_enabled_worker_checks_privacy_gate_before_db_or_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import worker

    monkeypatch.setattr(
        worker,
        "database_is_ready",
        lambda *_args: pytest.fail("privacy gate must run before DB readiness"),
    )
    monkeypatch.setattr(
        worker,
        "require_ai_provider",
        lambda *_args: pytest.fail("privacy gate must run before Provider setup"),
    )

    with pytest.raises(ConfigurationError, match="F3_ALLOW_SYNTHETIC_PROTOTYPE=true"):
        run_enabled_worker(
            config=bind_config(config_values()),
            stop_event=threading.Event(),
            ready_file=tmp_path / "worker-ready",
            worker_id="worker-test",
            environ={},
        )


def test_worker_ids_are_unique_and_fit_the_lease_column() -> None:
    first = build_worker_id()
    second = build_worker_id()

    assert first != second
    assert len(first) <= WORKER_ID_MAX_LENGTH


def test_enabled_worker_requires_an_explicit_llm_provider() -> None:
    with pytest.raises(ConfigurationError, match="general LLM endpoint"):
        require_ai_provider("test", {})

    with pytest.raises(ConfigurationError, match="general LLM endpoint"):
        require_ai_provider(
            "test",
            {
                "AI_VLLM_SLLM_BASE_URL": "http://localhost:8000/v1",
                "AI_VLLM_STT_BASE_URL": "http://localhost:8002/v1",
            },
        )

    configured = require_ai_provider(
        "test",
        {
            "AI_GENERAL_PROVIDER": "llama_cpp",
            "AI_GENERAL_MODEL": "unsloth/Qwen3.8-27B-GGUF:UD-Q4_K_M",
            "AI_GENERAL_BASE_URL": "http://localhost:8080/v1",
            "AI_GENERAL_API_KEY": "secret",
        },
    )
    assert configured.llm_endpoints[0].alias == "general-dev-gpu"


def test_enabled_worker_accepts_dev_ai_profile_from_process_environment() -> None:
    configured = require_ai_provider(
        "dev",
        {
            "AI_VLLM_SLLM_BASE_URL": "https://pod-8001.proxy.runpod.net/v1",
            "AI_VLLM_STT_BASE_URL": "https://pod-8002.proxy.runpod.net/v1",
            "AI_GENERAL_API_KEY": "test-key",
        },
    )

    assert configured.profile is AiProfile.DEV
    assert configured.vllm.sllm is not None


class FakeSession:
    def __init__(self) -> None:
        self.closed = False

    def __enter__(self) -> FakeSession:
        return self

    def __exit__(self, *_args: object) -> None:
        self.closed = True


class RecordingStopEvent(threading.Event):
    def __init__(self) -> None:
        super().__init__()
        self.waits: list[float | None] = []

    def wait(self, timeout: float | None = None) -> bool:
        self.waits.append(timeout)
        self.set()
        return True


def test_empty_polling_waits_instead_of_spinning(monkeypatch: pytest.MonkeyPatch) -> None:
    import worker

    event = RecordingStopEvent()
    session = FakeSession()
    monkeypatch.setattr(worker.service, "claim_next_run", lambda *_args: None)

    handled = run_worker_loop(
        stop_event=event,
        session_factory=cast(Any, lambda: session),
        handle=lambda *_args: None,
        worker_id="worker-test",
        idle_wait_seconds=0.25,
    )

    assert handled == 0
    assert event.waits == [0.25]
    assert session.closed


def test_polling_drains_claimed_runs_and_stops_after_current_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import worker

    event = threading.Event()
    session = FakeSession()
    runs = [cast(AgentRun, object()), cast(AgentRun, object())]
    claimed = iter(runs)
    handled: list[AgentRun] = []
    monkeypatch.setattr(
        worker.service,
        "claim_next_run",
        lambda *_args: next(claimed, None),
    )

    def handle(_session: Session, run: AgentRun) -> None:
        handled.append(run)
        event.set()

    count = run_worker_loop(
        stop_event=event,
        session_factory=cast(Any, lambda: session),
        handle=handle,
        worker_id="worker-test",
        idle_wait_seconds=0,
    )

    assert count == 1
    assert handled == runs[:1]
    assert session.closed


def test_missing_model_config_fails_only_the_claimed_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import worker

    run = AgentRun(
        id=11,
        brokerage_id=3,
        run_group_id="018f7c9e-0f2f-7c1e-9a3b-2f7c9e0f2f7c",  # type: ignore[arg-type]
        run_type="CROSS_JUDGMENT",
        agent_type="BROKERAGE_WORKFLOW",
        trigger_type="USER_REQUEST",
        requested_by=4,
        attempt_count=1,
    )
    monkeypatch.setattr(
        worker.f3_runtime,
        "build_bindings",
        lambda *_args: (_ for _ in ()).throw(GenerationBindingError("missing config")),
    )
    recorded: list[int] = []
    monkeypatch.setattr(
        worker.pipeline,
        "record_failure",
        lambda _session, failed, _worker_id, _outcome: recorded.append(failed.id or 0) or True,
    )

    loop = asyncio.new_event_loop()
    try:
        outcome = process_run(
            Session(create_engine("postgresql+psycopg://unused")),
            run,
            "worker-test",
            cast(AiRuntime, object()),
            loop,
        )
    finally:
        loop.close()

    assert outcome is worker.pipeline.StepOutcome.FAILED_TERMINAL
    assert recorded == [11]


def test_internal_health_probe_rejects_stale_or_invalid_files(tmp_path, monkeypatch):
    from core import worker_health

    path = tmp_path / "ready"
    monkeypatch.setattr(worker_health, "READY_FILE", path)
    assert not worker_health.is_ready()
    for content in ("invalid", "0", "-1"):
        path.write_text(content)
        assert not worker_health.is_ready()
    path.write_text(str(os.getpid()))
    assert worker_health.is_ready()

    def missing_pid(_pid, _signal):
        raise ProcessLookupError

    monkeypatch.setattr(worker_health.os, "kill", missing_pid)
    assert not worker_health.is_ready()
