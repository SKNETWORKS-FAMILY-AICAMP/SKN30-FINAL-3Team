"""Worker 기동 설정, polling과 실행별 오류 격리."""

from __future__ import annotations

import asyncio
import os
import threading
from pathlib import Path
from typing import Any, cast

import pytest
from brokerage_ai.core.types import ProviderKind
from brokerage_ai.f3 import InputPrivacyMode
from brokerage_ai.providers.ports import LlmProvider
from brokerage_ai.runtime import AiRuntime
from sqlmodel import Session

from core.errors import ConfigurationError
from domain.agent_execution.anchor_card import GenerationBindingError
from domain.agent_execution.models import AgentRun, AiModelConfig
from worker import (
    WORKER_ID_MAX_LENGTH,
    build_bindings,
    build_worker_id,
    process_run,
    require_ai_provider,
    run_disabled_worker,
    run_worker_loop,
)


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


def test_worker_ids_are_unique_and_fit_the_lease_column() -> None:
    first = build_worker_id()
    second = build_worker_id()

    assert first != second
    assert len(first) <= WORKER_ID_MAX_LENGTH
    assert build_worker_id("x" * 200) == "x" * WORKER_ID_MAX_LENGTH


def test_enabled_worker_requires_an_explicit_llm_provider() -> None:
    with pytest.raises(ConfigurationError, match="LLM provider"):
        require_ai_provider("test", {})

    configured = require_ai_provider("test", {"AI_VLLM_LLM_BASE_URL": "http://localhost:8000/v1"})
    assert configured.vllm.llm is not None


def test_enabled_worker_merges_ai_local_files_without_mutating_process_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import brokerage_ai.core.config as ai_config_module

    (tmp_path / ".env.local").write_text(
        "AI_REQUEST_TIMEOUT_SECONDS=10\nAI_VLLM_LLM_BASE_URL=http://localhost:8000/v1\n",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "AI_VLLM_LLM_API_KEY=personal-secret\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(ai_config_module, "AI_ROOT", tmp_path)
    monkeypatch.delenv("AI_VLLM_LLM_API_KEY", raising=False)

    config = require_ai_provider(
        "local",
        {"AI_REQUEST_TIMEOUT_SECONDS": "30"},
    )

    assert config.request_timeout_seconds == 30
    assert config.vllm.llm is not None
    assert config.vllm.llm.api_key is not None
    assert config.vllm.llm.api_key.get_secret_value() == "personal-secret"
    assert "AI_VLLM_LLM_API_KEY" not in os.environ


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


class FakeProvider:
    kind = ProviderKind.VLLM


class FakeRegistry:
    def get_llm(self, kind: ProviderKind) -> LlmProvider:
        if kind is not ProviderKind.VLLM:
            raise AssertionError("unexpected provider")
        return cast(LlmProvider, FakeProvider())


class FakeRuntime:
    providers = FakeRegistry()


def _model_config(capability: str, config_id: int) -> AiModelConfig:
    return AiModelConfig(
        id=config_id,
        brokerage_id=1,
        capability=capability,
        config_key=f"{capability.lower()}-default",
        config_version=1,
        provider="vllm",
        model_name="prototype-model",
    )


def test_bindings_use_separate_capabilities_and_explicit_synthetic_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import worker

    configs = {
        "POSITION_CARD": _model_config("POSITION_CARD", 7),
        "BROKERAGE_JUDGMENT": _model_config("BROKERAGE_JUDGMENT", 9),
    }
    monkeypatch.setattr(
        worker.repository,
        "find_active_model_config",
        lambda _session, _brokerage_id, capability: configs[capability],
    )

    card_bindings = build_bindings(
        cast(Session, object()),
        cast(AiRuntime, FakeRuntime()),
        AgentRun(
            brokerage_id=1,
            run_group_id="018f7c9e-0f2f-7c1e-9a3b-2f7c9e0f2f7c",  # type: ignore[arg-type]
            run_type="CROSS_JUDGMENT",
            agent_type="BROKERAGE_WORKFLOW",
            status="RUNNING",
            trigger_type="USER_REQUEST",
            requested_by=1,
        ),
    )
    monkeypatch.setattr(worker, "_judgment_required", lambda *_args: True)
    judgment_bindings = build_bindings(
        cast(Session, object()),
        cast(AiRuntime, FakeRuntime()),
        AgentRun(
            brokerage_id=1,
            run_group_id="018f7c9e-0f2f-7c1e-9a3b-2f7c9e0f2f7c",  # type: ignore[arg-type]
            run_type="CROSS_JUDGMENT",
            agent_type="BROKERAGE_WORKFLOW",
            status="CANDIDATE_CARDS_READY",
            trigger_type="USER_REQUEST",
            requested_by=1,
        ),
    )

    assert card_bindings.card is not None
    assert card_bindings.card.model_config_id == 7
    assert card_bindings.judgment is None
    assert card_bindings.card.input_privacy_mode is InputPrivacyMode.SYNTHETIC_PROTOTYPE
    assert judgment_bindings.card is None
    assert judgment_bindings.judgment is not None
    assert judgment_bindings.judgment.model_config_id == 9
    assert judgment_bindings.judgment.input_privacy_mode is InputPrivacyMode.SYNTHETIC_PROTOTYPE


def test_zero_candidates_do_not_look_up_a_judgment_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import worker

    monkeypatch.setattr(worker, "_judgment_required", lambda *_args: False)
    monkeypatch.setattr(
        worker.repository,
        "find_active_model_config",
        lambda *_args: (_ for _ in ()).throw(AssertionError("model config must not be read")),
    )
    run = AgentRun(
        brokerage_id=1,
        run_group_id="018f7c9e-0f2f-7c1e-9a3b-2f7c9e0f2f7c",  # type: ignore[arg-type]
        run_type="CROSS_JUDGMENT",
        agent_type="BROKERAGE_WORKFLOW",
        status="CANDIDATE_CARDS_READY",
        trigger_type="USER_REQUEST",
        requested_by=1,
    )

    bindings = build_bindings(cast(Session, object()), cast(AiRuntime, FakeRuntime()), run)

    assert bindings.card is None
    assert bindings.judgment is None


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
        worker,
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
            cast(Session, object()),
            run,
            "worker-test",
            cast(AiRuntime, object()),
            loop,
        )
    finally:
        loop.close()

    assert outcome is worker.pipeline.StepOutcome.FAILED_TERMINAL
    assert recorded == [11]
