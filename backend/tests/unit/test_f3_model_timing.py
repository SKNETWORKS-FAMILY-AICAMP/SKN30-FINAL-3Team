import asyncio
from typing import cast

import pytest
from brokerage_ai.core.types import ProviderKind, StructuredGenerationRequest
from brokerage_ai.providers.ports import LlmProvider
from pydantic import BaseModel

from domain.agent_execution import model_timing


class Output(BaseModel):
    value: int


def test_provider_wrapper_forwards_unchanged_and_counts_repair_per_task(monkeypatch):
    events = []
    request = cast(StructuredGenerationRequest, object())
    result = object()

    class Provider:
        kind = ProviderKind.OPENAI

        async def generate_structured(self, actual, schema):
            assert actual is request
            assert schema is Output
            return result

    class Logger:
        def info(self, event, **values):
            events.append(values)

    monkeypatch.setattr(model_timing, "logger", Logger())
    measured = model_timing.TimedProvider(cast(LlmProvider, Provider()), 3, 1, "POSITION_CARD")

    async def logical_call():
        assert await measured.generate_structured(request, Output) is result
        assert await measured.generate_structured(request, Output) is result

    async def scenario():
        await asyncio.gather(logical_call(), logical_call())

    asyncio.run(scenario())
    assert measured.kind is ProviderKind.OPENAI
    assert [(e["generation_ordinal"], e["provider_attempt"]) for e in events] == [
        (1, 1),
        (1, 2),
        (2, 1),
        (2, 2),
    ]
    assert all(
        set(e)
        == {
            "run_id",
            "attempt",
            "capability",
            "generation_ordinal",
            "provider_attempt",
            "ok",
            "wall_ms",
        }
        for e in events
    )


def test_provider_failure_is_not_retried_or_rewritten(monkeypatch):
    error = RuntimeError("synthetic private response")

    class Provider:
        kind = ProviderKind.OPENAI
        calls = 0

        async def generate_structured(self, *_args):
            self.calls += 1
            raise error

    provider = Provider()
    events = []

    class Logger:
        def info(self, _event, **values):
            events.append(values)

    monkeypatch.setattr(model_timing, "logger", Logger())
    measured = model_timing.TimedProvider(cast(LlmProvider, provider), 3, 1, "BROKERAGE_JUDGMENT")
    with pytest.raises(RuntimeError) as caught:
        asyncio.run(
            measured.generate_structured(cast(StructuredGenerationRequest, object()), Output)
        )
    assert caught.value is error and provider.calls == 1
    assert events[0]["ok"] is False
    assert "synthetic private" not in str(events)
