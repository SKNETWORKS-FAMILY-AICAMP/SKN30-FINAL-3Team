from __future__ import annotations

import logging

import structlog

from core.config import LogConfig


def exception_location(error: BaseException) -> str | None:
    """Return the deepest traceback location without exposing values or source paths."""
    traceback = error.__traceback__
    if traceback is None:
        return None
    while traceback.tb_next is not None:
        traceback = traceback.tb_next

    module = traceback.tb_frame.f_globals.get("__name__")
    safe_module = module if isinstance(module, str) and module else "<unknown>"
    function = traceback.tb_frame.f_code.co_name
    return f"{safe_module}:{function}:{traceback.tb_lineno}"


def configure_logging(config: LogConfig) -> None:
    logging.basicConfig(level=config.level, format="%(message)s")
    renderer = (
        structlog.processors.JSONRenderer()
        if config.format == "json"
        else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping().get(config.level, logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
