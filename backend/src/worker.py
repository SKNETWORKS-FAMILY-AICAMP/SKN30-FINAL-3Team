"""F3 교차 판정 Worker 프로세스.

API 와 같은 image 를 쓰지만 역할은 분리한다. Worker 는 실행을 선점하고, 저장된 상태에 맞는
단계를 진행시키며, 결과와 실패를 저장한다.

`WORKER_ENABLED=false` 는 그대로 안전하게 대기한다. readiness 만 확인하고 실행을 하나도
claim 하지 않는다.

## 이벤트 loop

프로세스 수명 동안 **하나의** asyncio loop 를 쓴다. `AsyncOpenAI` client 는 만들어진 loop 에
묶이므로 단계마다 `asyncio.run()` 을 부르면 매번 새 loop 가 생겨 client 가 깨진다. 정지
신호는 그대로 `threading.Event` 로 받아 동기 loop 구조를 유지한다.

## 종료

SIGTERM·SIGINT 를 받으면 stop event 를 세운다. **처리 중인 실행은 지금 단계까지 마치고**
다음 실행을 집지 않는다. 단계 하나가 곧 transaction 하나라 중간에 끊겨도 저장된 상태가
정본으로 남고 다음 Worker 가 이어서 처리한다.
"""

from __future__ import annotations

import asyncio
import os
import signal
import socket
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from uuid import uuid4

import structlog
from brokerage_ai.core.config import AiConfig, load_ai_config
from brokerage_ai.core.types import ModelRoute, ProviderKind
from brokerage_ai.f3 import LlmBrokerageJudgmentGenerator, LlmPositionCardGenerator
from brokerage_ai.runtime import AiRuntime, create_ai_runtime
from sqlalchemy import text
from sqlmodel import Session

from core.config import Config, get_config
from core.errors import ConfigurationError
from core.logging import configure_logging
from domain.agent_execution import pipeline, repository, service
from domain.agent_execution.anchor_card import GenerationBinding
from domain.agent_execution.judgment import JudgmentBinding
from domain.agent_execution.models import (
    BROKERAGE_JUDGMENT_CAPABILITY,
    POSITION_CARD_CAPABILITY,
    AgentRun,
    AiModelConfig,
)
from domain.engine import create_database_engine

logger = structlog.get_logger()
DEFAULT_READY_FILE = Path("/tmp/brokerage-worker-ready")

# 큐가 비었을 때 다시 확인하기까지 기다리는 시간. busy loop 를 만들지 않는다.
IDLE_WAIT_SECONDS = 2.0

# `agent_run.lease_owner` 가 VARCHAR(64) 다. 넘치면 lease fencing 이 조용히 어긋난다.
WORKER_ID_MAX_LENGTH = 64


def worker_enabled(source: Mapping[str, str]) -> bool:
    raw = source.get("WORKER_ENABLED", "false").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    if raw in {"1", "true", "yes", "on"}:
        return True
    raise ConfigurationError("WORKER_ENABLED must be a boolean")


def build_worker_id(source: Mapping[str, str] | None = None) -> str:
    """이 Worker 인스턴스의 고유 식별자. 길이를 컬럼 상한 안으로 자른다.

    호스트와 PID 만으로는 재시작 후 같은 값이 나올 수 있어 무작위 접미사를 붙인다. lease
    소유권 판정이 이 값 하나에 걸려 있으므로 겹치면 남의 결과를 덮어쓴다.
    """
    configured = (source or os.environ).get("WORKER_ID", "").strip()
    if configured:
        return configured[:WORKER_ID_MAX_LENGTH]
    host = socket.gethostname().split(".")[0][:24]
    return f"{host}-{os.getpid()}-{uuid4().hex[:8]}"[:WORKER_ID_MAX_LENGTH]


def database_is_ready(config: Config) -> None:
    engine = create_database_engine(config)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    finally:
        engine.dispose()


def run_disabled_worker(
    *,
    stop_event: threading.Event,
    ready_file: Path,
    readiness_probe: Callable[[], None],
) -> None:
    readiness_probe()
    ready_file.parent.mkdir(parents=True, exist_ok=True)
    ready_file.write_text("disabled\n", encoding="utf-8")
    logger.info("worker_ready", enabled=False)
    try:
        stop_event.wait()
    finally:
        ready_file.unlink(missing_ok=True)
        logger.info("worker_stopped", enabled=False)


def require_ai_provider(profile: str, environ: Mapping[str, str] | None = None) -> AiConfig:
    """AI 설정을 읽고 LLM Provider 가 하나라도 있는지 확인한다.

    Provider 와 모델 ID 를 코드에서 고르지 않는다. 설정이 없으면 실행을 집기 전에 기동을
    거부한다. 실행을 집은 뒤에 알면 그 실행이 시도 횟수만 소모하고 실패한다.
    """
    config = load_ai_config(profile, environ)
    if config.openai is None and config.vllm.llm is None:
        raise ConfigurationError(
            "WORKER_ENABLED=true requires at least one configured LLM provider"
        )
    return config


def _route(config: AiModelConfig) -> ModelRoute:
    """DB 설정을 AI 모델 경로로 옮긴다. Provider 와 모델 이름은 설정 행에서 나온다."""
    try:
        provider = ProviderKind(config.provider)
    except ValueError as error:
        raise ConfigurationError("the configured AI provider is not supported") from error
    return ModelRoute(provider=provider, model=config.model_name)


def build_bindings(
    session: Session, runtime: AiRuntime, brokerage_id: int
) -> pipeline.ExecutionBindings:
    """이 실행의 사무소에 활성화된 두 모델 설정으로 생성기를 조립한다.

    대리와 판정은 서로 다른 capability 설정을 쓴다 (F3-NF-10). 어느 것이든 없으면 이 실행은
    진행할 수 없으므로 `ConfigurationError` 로 올린다.
    """
    card_config = repository.find_active_model_config(
        session, brokerage_id, POSITION_CARD_CAPABILITY
    )
    judgment_config = repository.find_active_model_config(
        session, brokerage_id, BROKERAGE_JUDGMENT_CAPABILITY
    )
    if card_config is None or judgment_config is None:
        raise ConfigurationError("the brokerage has no active AI model configuration")

    return pipeline.ExecutionBindings(
        card=GenerationBinding(
            generator=LlmPositionCardGenerator(
                provider=runtime.providers.get_llm(ProviderKind(card_config.provider)),
                route=_route(card_config),
            ),
            model_config_id=card_config.id or 0,
        ),
        judgment=JudgmentBinding(
            generator=LlmBrokerageJudgmentGenerator(
                provider=runtime.providers.get_llm(ProviderKind(judgment_config.provider)),
                route=_route(judgment_config),
            ),
            model_config_id=judgment_config.id or 0,
        ),
    )


def process_run(
    session: Session,
    run: AgentRun,
    worker_id: str,
    runtime: AiRuntime,
    loop: asyncio.AbstractEventLoop,
    should_stop: Callable[[], bool] | None = None,
) -> pipeline.StepOutcome:
    """선점한 실행 하나를 같은 lease 아래에서 진행시킨다. 예외를 밖으로 던지지 않는다."""
    try:
        bindings = build_bindings(session, runtime, run.brokerage_id)
    except ConfigurationError:
        # 설정 문제는 재시도해도 풀리지 않는다. 이 실행만 종료 처리하고 loop 는 계속 돈다.
        logger.warning("f3_model_config_missing", run_id=run.id, brokerage_id=run.brokerage_id)
        pipeline.record_failure(session, run, worker_id, pipeline.StepOutcome.FAILED_TERMINAL)
        return pipeline.StepOutcome.FAILED_TERMINAL
    return pipeline.drive_run(session, run, worker_id, bindings, loop, should_stop)


def run_worker_loop(
    *,
    stop_event: threading.Event,
    session_factory: Callable[[], Session],
    handle: Callable[[Session, AgentRun], None],
    worker_id: str,
    idle_wait_seconds: float = IDLE_WAIT_SECONDS,
) -> int:
    """실행이 없을 때까지 선점하고 처리한다. 처리한 실행 수를 돌려준다.

    작업이 없으면 `stop_event.wait(timeout)` 으로 기다린다. sleep 반복이나 busy loop 를
    만들지 않으며, 대기 중에 정지 신호가 오면 즉시 깨어난다.
    """
    handled = 0
    with session_factory() as session:
        while not stop_event.is_set():
            claimed = service.claim_next_run(session, worker_id)
            if claimed is None:
                # 큐가 비었다. 정지 신호가 오면 기다리지 않고 바로 깨어난다.
                stop_event.wait(idle_wait_seconds)
                continue
            handle(session, claimed)
            handled += 1
    return handled


def run_enabled_worker(
    *,
    config: Config,
    stop_event: threading.Event,
    ready_file: Path,
    worker_id: str,
    environ: Mapping[str, str] | None = None,
) -> None:
    """실제 F3 Worker. 기동 전에 DB 와 AI 설정을 모두 확인한다."""
    database_is_ready(config)
    # AI profile 값 어휘가 Backend 의 AppEnvironment 와 같아 그대로 넘긴다.
    ai_config = require_ai_provider(config.app.environment.value, environ)

    loop = asyncio.new_event_loop()
    runtime = create_ai_runtime(ai_config)
    engine = create_database_engine(config)
    ready_file.parent.mkdir(parents=True, exist_ok=True)
    ready_file.write_text("enabled\n", encoding="utf-8")
    logger.info("worker_ready", enabled=True, worker_id=worker_id)

    try:
        run_worker_loop(
            stop_event=stop_event,
            session_factory=lambda: Session(engine),
            handle=lambda session, run: logger.info(
                "f3_run_settled",
                run_id=run.id,
                outcome=process_run(
                    session, run, worker_id, runtime, loop, stop_event.is_set
                ).value,
            ),
            worker_id=worker_id,
        )
    finally:
        # AI runtime 자원과 DB 커넥션을 정리하고 readiness file 을 지운다.
        loop.run_until_complete(runtime.close())
        loop.close()
        engine.dispose()
        ready_file.unlink(missing_ok=True)
        logger.info("worker_stopped", enabled=True, worker_id=worker_id)


def main() -> None:
    config = get_config()
    configure_logging(config.log)
    enabled = worker_enabled(os.environ)

    stop_event = threading.Event()

    def request_stop(signum: int, _frame: object) -> None:
        logger.info("worker_stop_requested", signal=signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    ready_file = Path(os.getenv("WORKER_READY_FILE", str(DEFAULT_READY_FILE)))

    if not enabled:
        run_disabled_worker(
            stop_event=stop_event,
            ready_file=ready_file,
            readiness_probe=lambda: database_is_ready(config),
        )
        return

    run_enabled_worker(
        config=config,
        stop_event=stop_event,
        ready_file=ready_file,
        worker_id=build_worker_id(),
    )


if __name__ == "__main__":
    main()
