"""F3-only timing samples; SQL text, parameters and model content are never logged."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from time import perf_counter

import structlog
from sqlalchemy import event
from sqlalchemy.engine import Engine

logger = structlog.get_logger()


@dataclass
class SqlSample:
    run_id: int | None = None
    count: int = 0
    elapsed_ms: float = 0


_sample: ContextVar[SqlSample | None] = ContextVar("f3_sql_sample", default=None)


@event.listens_for(Engine, "before_cursor_execute")
def _before(_connection, _cursor, _statement, _parameters, context, _executemany):
    sample = _sample.get()
    if sample is not None:
        sample.count += 1
        context._f3_sample = (sample, perf_counter())


@event.listens_for(Engine, "after_cursor_execute")
def _after(_connection, _cursor, _statement, _parameters, context, _executemany):
    measured = getattr(context, "_f3_sample", None)
    if measured is not None:
        sample, started = measured
        sample.elapsed_ms += (perf_counter() - started) * 1000
        del context._f3_sample


@contextmanager
def measure(operation: str, *, run_id: int | None = None) -> Iterator[SqlSample]:
    started = perf_counter()
    sample = SqlSample(run_id=run_id)
    token = _sample.set(sample)
    ok = False
    try:
        yield sample
        ok = True
    finally:
        _sample.reset(token)
        logger.info(
            "f3_timing",
            operation=operation,
            run_id=sample.run_id,
            ok=ok,
            wall_ms=round((perf_counter() - started) * 1000, 2),
            sql_count=sample.count,
            sql_ms=round(sample.elapsed_ms, 2),
        )
