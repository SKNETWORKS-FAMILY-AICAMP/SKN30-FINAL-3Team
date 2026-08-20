from __future__ import annotations

import os
import signal
import threading
from collections.abc import Callable, Mapping
from pathlib import Path

import structlog
from sqlalchemy import text

from core.config import Config, get_config
from core.errors import ConfigurationError
from core.logging import configure_logging
from domain.engine import create_database_engine

logger = structlog.get_logger()
DEFAULT_READY_FILE = Path("/tmp/brokerage-worker-ready")


def worker_enabled(source: Mapping[str, str]) -> bool:
    raw = source.get("WORKER_ENABLED", "false").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    if raw in {"1", "true", "yes", "on"}:
        return True
    raise ConfigurationError("WORKER_ENABLED must be a boolean")


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


def main() -> None:
    config = get_config()
    configure_logging(config.log)
    if worker_enabled(os.environ):
        raise ConfigurationError(
            "WORKER_ENABLED=true is unavailable until the complete F3 handler is implemented"
        )

    stop_event = threading.Event()

    def request_stop(signum: int, _frame: object) -> None:
        logger.info("worker_stop_requested", signal=signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    ready_file = Path(os.getenv("WORKER_READY_FILE", str(DEFAULT_READY_FILE)))
    run_disabled_worker(
        stop_event=stop_event,
        ready_file=ready_file,
        readiness_probe=lambda: database_is_ready(config),
    )


if __name__ == "__main__":
    main()
