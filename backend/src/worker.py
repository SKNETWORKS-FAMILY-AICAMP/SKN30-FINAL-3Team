"""F3 교차 판정 Worker 프로세스.

API와 같은 image를 사용하지만 실행 역할은 분리한다. 활성 Worker는 RDS에서 실행을 선점하고
저장된 상태에 해당하는 application 유스케이스를 호출한다. 비활성 Worker는 기존처럼 DB
readiness만 확인하고 어떤 실행도 선점하지 않는다.

프로세스 수명 동안 하나의 asyncio event loop를 사용한다. SIGTERM·SIGINT가 오면 처리 중인
단계까지만 마치고 다음 실행을 선점하지 않는다.
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
from brokerage_ai.core.errors import ProviderConfigurationError
from brokerage_ai.core.types import ModelRoute, ProviderKind
from brokerage_ai.f3 import (
    InputPrivacyMode,
    LlmBrokerageJudgmentGenerator,
    LlmPositionCardGenerator,
)
from brokerage_ai.providers.ports import LlmProvider
from brokerage_ai.runtime import AiRuntime, create_ai_runtime
from pydantic import ValidationError
from sqlalchemy import text
from sqlmodel import Session

from core.config import Config, get_config
from core.errors import ConfigurationError
from core.logging import configure_logging
from domain.agent_execution import pipeline, repository, service
from domain.agent_execution.anchor_card import GenerationBinding, GenerationBindingError
from domain.agent_execution.judgment import JudgmentBinding
from domain.agent_execution.models import (
    BROKERAGE_JUDGMENT_CAPABILITY,
    CANDIDATE_CARDS_READY_STATUS,
    CANDIDATES_READY_STATUS,
    JUDGING_STATUS,
    POSITION_CARD_CAPABILITY,
    RUNNING_STATUS,
    AgentRun,
    AiModelConfig,
)
from domain.engine import create_database_engine

logger = structlog.get_logger()
IDLE_WAIT_SECONDS = 2.0
WORKER_ID_MAX_LENGTH = 64
SYNTHETIC_PROTOTYPE_SETTING = "F3_ALLOW_SYNTHETIC_PROTOTYPE"


def boolean_setting(source: Mapping[str, str], name: str, *, default: bool = False) -> bool:
    raw = source.get(name, str(default)).strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    if raw in {"1", "true", "yes", "on"}:
        return True
    raise ConfigurationError(f"{name} must be a boolean")


def worker_enabled(source: Mapping[str, str]) -> bool:
    return boolean_setting(source, "WORKER_ENABLED")


def require_synthetic_prototype_opt_in(source: Mapping[str, str]) -> None:
    """활성 Worker가 합성 데이터임을 운영자가 명시하지 않으면 기동을 막는다.

    코드만으로 DB 행이 실제 인물과 무관한 합성 데이터인지 증명할 수 없다. 따라서 현재 유일하게
    구현된 ``SYNTHETIC_PROTOTYPE`` 경로는 배포 환경의 별도 opt-in을 요구한다. 실사용 데이터용
    ``MASKED`` 조립이 구현되기 전까지 이 설정을 켜지 않은 Worker는 어떤 실행도 claim하지 않는다.
    """
    if not boolean_setting(source, SYNTHETIC_PROTOTYPE_SETTING):
        raise ConfigurationError(
            "WORKER_ENABLED=true requires F3_ALLOW_SYNTHETIC_PROTOTYPE=true "
            "for a reviewed synthetic-only dataset"
        )


def build_worker_id(configured: str | None = None) -> str:
    """재시작과 병렬 인스턴스 사이에 겹치지 않는 64자 이하 lease owner를 만든다."""
    if configured and configured.strip():
        return configured.strip()[:WORKER_ID_MAX_LENGTH]
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
    """실행을 선점하기 전에 LLM Provider 설정이 하나 이상 있는지 확인한다."""
    config = load_ai_config(profile, environ)
    if config.openai is None and config.vllm.llm is None:
        raise ConfigurationError(
            "WORKER_ENABLED=true requires at least one configured LLM provider"
        )
    return config


def _route(config: AiModelConfig) -> ModelRoute:
    """DB의 안전한 모델 설정을 Provider 중립 AI route로 옮긴다."""
    try:
        provider = ProviderKind(config.provider)
    except ValueError as error:
        raise ConfigurationError("the configured AI provider is not supported") from error
    try:
        return ModelRoute(provider=provider, model=config.model_name)
    except ValidationError as error:
        raise ConfigurationError("the configured AI model route is invalid") from error


def _generator_inputs(runtime: AiRuntime, config: AiModelConfig) -> tuple[LlmProvider, ModelRoute]:
    route = _route(config)
    try:
        provider = runtime.providers.get_llm(route.provider)
    except ProviderConfigurationError as error:
        raise ConfigurationError("the configured AI provider is not available") from error
    return provider, route


def _card_model_config(session: Session, run: AgentRun) -> AiModelConfig | None:
    if run.model_config_id is not None:
        return repository.find_position_card_model_config(
            session, run.brokerage_id, run.model_config_id
        )
    return repository.find_active_model_config(session, run.brokerage_id, POSITION_CARD_CAPABILITY)


def _judgment_model_config(session: Session, run: AgentRun) -> AiModelConfig | None:
    recorded = run.redacted_output_snapshot.get("judgment")
    recorded_id = recorded.get("model_config_id") if isinstance(recorded, dict) else None
    if isinstance(recorded_id, int):
        return repository.find_brokerage_judgment_model_config(
            session, run.brokerage_id, recorded_id
        )
    return repository.find_active_model_config(
        session, run.brokerage_id, BROKERAGE_JUDGMENT_CAPABILITY
    )


def _judgment_required(session: Session, run: AgentRun) -> bool:
    """후보 카드가 없으면 판정 설정과 Provider를 조회하지 않는다."""
    header = repository.find_match_evaluation_for_run(session, run.brokerage_id, run.id or 0)
    if header is None:
        return False
    entries = header.candidate_selection_snapshot.get("candidate_cards")
    return isinstance(entries, list) and bool(entries)


def build_bindings(
    session: Session,
    runtime: AiRuntime,
    run: AgentRun,
) -> pipeline.ExecutionBindings:
    """현재 저장 상태에서 실제로 필요한 capability만 조립한다."""
    privacy_mode = InputPrivacyMode.SYNTHETIC_PROTOTYPE
    card: GenerationBinding | None = None
    judgment: JudgmentBinding | None = None

    if run.status in {RUNNING_STATUS, CANDIDATES_READY_STATUS}:
        card_config = _card_model_config(session, run)
        if card_config is None:
            raise GenerationBindingError("the position card model configuration is unavailable")
        try:
            card_provider, card_route = _generator_inputs(runtime, card_config)
        except ConfigurationError as error:
            raise GenerationBindingError("the position card provider is unavailable") from error
        card = GenerationBinding(
            generator=LlmPositionCardGenerator(
                provider=card_provider,
                route=card_route,
                allow_synthetic_prototype=True,
            ),
            model_config_id=card_config.id or 0,
            input_privacy_mode=privacy_mode,
        )

    if run.status in {CANDIDATE_CARDS_READY_STATUS, JUDGING_STATUS} and _judgment_required(
        session, run
    ):
        judgment_config = _judgment_model_config(session, run)
        if judgment_config is None:
            raise GenerationBindingError("the judgment model configuration is unavailable")
        try:
            judgment_provider, judgment_route = _generator_inputs(runtime, judgment_config)
        except ConfigurationError as error:
            raise GenerationBindingError("the judgment provider is unavailable") from error
        judgment = JudgmentBinding(
            generator=LlmBrokerageJudgmentGenerator(
                provider=judgment_provider,
                route=judgment_route,
                allow_synthetic_prototype=True,
            ),
            model_config_id=judgment_config.id or 0,
            input_privacy_mode=privacy_mode,
        )

    return pipeline.ExecutionBindings(card=card, judgment=judgment)


def process_run(
    session: Session,
    run: AgentRun,
    worker_id: str,
    runtime: AiRuntime,
    loop: asyncio.AbstractEventLoop,
    should_stop: Callable[[], bool] | None = None,
) -> pipeline.StepOutcome:
    """선점한 실행 하나의 설정 오류와 단계 오류를 다른 실행에서 격리한다."""
    return pipeline.drive_run(
        session,
        run,
        worker_id,
        lambda current: build_bindings(session, runtime, current),
        loop,
        should_stop,
    )


def run_worker_loop(
    *,
    stop_event: threading.Event,
    session_factory: Callable[[], Session],
    handle: Callable[[Session, AgentRun], None],
    worker_id: str,
    idle_wait_seconds: float = IDLE_WAIT_SECONDS,
) -> int:
    """RDS polling으로 실행을 선점한다. 빈 큐에서는 stop event를 timeout과 함께 기다린다."""
    handled = 0
    with session_factory() as session:
        while not stop_event.is_set():
            claimed = service.claim_next_run(session, worker_id)
            if claimed is None:
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
    """개인정보 모드, DB와 AI 설정을 검증한 뒤 실제 polling을 시작한다."""
    values = os.environ if environ is None else environ
    # DB나 Provider에 접근하기 전에 막는다. 이 검증을 뒤로 보내면 잘못 구성된 Worker가
    # readiness를 통과한 뒤 실행을 claim하거나 외부 client를 조립할 여지가 생긴다.
    require_synthetic_prototype_opt_in(values)
    database_is_ready(config)
    ai_config = require_ai_provider(config.app.environment.value, values)

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
                    session,
                    run,
                    worker_id,
                    runtime,
                    loop,
                    stop_event.is_set,
                ).value,
            ),
            worker_id=worker_id,
        )
    finally:
        loop.run_until_complete(runtime.close())
        loop.close()
        engine.dispose()
        ready_file.unlink(missing_ok=True)
        logger.info("worker_stopped", enabled=True, worker_id=worker_id)


def main() -> None:
    config = get_config()
    configure_logging(config.log)
    stop_event = threading.Event()

    def request_stop(signum: int, _frame: object) -> None:
        logger.info("worker_stop_requested", signal=signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    if not config.worker.enabled:
        run_disabled_worker(
            stop_event=stop_event,
            ready_file=config.worker.ready_file,
            readiness_probe=lambda: database_is_ready(config),
        )
        return

    run_enabled_worker(
        config=config,
        stop_event=stop_event,
        ready_file=config.worker.ready_file,
        worker_id=build_worker_id(config.worker.worker_id),
    )


if __name__ == "__main__":
    main()
