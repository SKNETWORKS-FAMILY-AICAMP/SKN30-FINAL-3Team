"""Observe the public Provider port without inspecting requests or changing retries."""

import asyncio
from time import perf_counter
from weakref import WeakKeyDictionary

import structlog
from brokerage_ai.core.types import (
    ProviderKind,
    StructuredGenerationRequest,
    StructuredGenerationResult,
)
from brokerage_ai.providers.ports import LlmProvider
from pydantic import BaseModel

logger = structlog.get_logger()


class TimedProvider:
    def __init__(self, provider: LlmProvider, run_id: int, attempt: int, capability: str):
        self.provider = provider
        self.run_id = run_id
        self.attempt = attempt
        self.capability = capability
        self._tasks: WeakKeyDictionary[asyncio.Task, tuple[int, int]] = WeakKeyDictionary()
        self._next_request = 0

    @property
    def kind(self) -> ProviderKind:
        return self.provider.kind

    async def generate_structured[OutputT: BaseModel](
        self,
        request: StructuredGenerationRequest,
        output_schema: type[OutputT],
    ) -> StructuredGenerationResult[OutputT]:
        task = asyncio.current_task()
        previous = self._tasks.get(task) if task is not None else None
        if previous is None:
            self._next_request += 1
            ordinal, call = self._next_request, 1
        else:
            ordinal, count = previous
            call = count + 1
        if task is not None:
            self._tasks[task] = (ordinal, call)
        started = perf_counter()
        ok = False
        try:
            result = await self.provider.generate_structured(request, output_schema)
            ok = True
            return result
        finally:
            logger.info(
                "f3_model_call",
                run_id=self.run_id,
                attempt=self.attempt,
                capability=self.capability,
                generation_ordinal=ordinal,
                provider_attempt=call,
                ok=ok,
                wall_ms=round((perf_counter() - started) * 1000, 2),
            )
