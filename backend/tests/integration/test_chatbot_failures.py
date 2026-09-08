"""Provider failure classification and transactional final-write failure recovery."""

from __future__ import annotations

import asyncio
import os
from datetime import timedelta
from uuid import uuid4

import pytest
import test_chatbot as chatbot_fixtures
from brokerage_ai.chatbot import (
    ChatbotContextLimitError,
    ChatbotContractError,
    ChatExecution,
    ChatIntent,
)
from brokerage_ai.core.errors import (
    ProviderConfigurationError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlmodel import Session

from domain.chatbot.manager import ChatbotManager
from domain.chatbot.models import ChatRequest, now

chat_engine = chatbot_fixtures.chat_engine
user = chatbot_fixtures.user
question = chatbot_fixtures.question
result = chatbot_fixtures.result

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DB_URL"), reason="isolated TEST_DB_URL required"
)


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (ProviderRateLimitError(), "CHATBOT_BUSY"),
        (ProviderUnavailableError(), "CHATBOT_UNAVAILABLE"),
        (ProviderConfigurationError("private-configuration-detail"), "CHATBOT_UNAVAILABLE"),
        (ProviderTimeoutError(), "CHATBOT_TIMEOUT"),
        (ChatbotContextLimitError("private-context-detail"), "CHATBOT_CONTEXT_LIMIT"),
        (ChatbotContractError("private-output-detail"), "CHATBOT_INVALID_OUTPUT"),
    ],
)
def test_provider_errors_are_safe_terminal_failures(chat_engine, user, error, code, capsys):
    class FailedWorkflow:
        calls = 0

        async def run(self, context, *, capability, on_progress):
            self.calls += 1
            raise error

    async def scenario():
        workflow = FailedWorkflow()
        manager = ChatbotManager(chat_engine, workflow_factory=lambda _: workflow)
        await manager.start()
        try:
            conversation = manager.store.create(user)
            body = question()
            accepted = await manager.submit(user, conversation.id, body)
            await asyncio.gather(*list(manager.tasks.values()))
            failed = manager.store.get_request(user, accepted.id)
            assert failed.status == "FAILED" and failed.failure_code == code
            assert failed.answer is None
            assert len(manager.store.history(user, conversation.id, None, 30).items) == 1
            duplicate = await manager.submit(user, conversation.id, body)
            assert duplicate.id == accepted.id and duplicate.status == "FAILED"
            assert workflow.calls == 1 and not manager.tasks
        finally:
            await manager.close()

    asyncio.run(scenario())
    captured = capsys.readouterr()
    assert "private-" not in captured.out + captured.err


def test_final_answer_insert_failure_rolls_back_then_manual_retry_succeeds(
    chat_engine, user, capsys
):
    class Workflow:
        async def run(self, context, *, capability, on_progress):
            return ChatExecution(result=result(), intent=ChatIntent(tool="properties"))

    def fail_answer(_connection, _cursor, statement, parameters, _context, _executemany):
        if (
            statement.startswith("INSERT INTO chat_message")
            and parameters.get("role") == "assistant"
        ):
            raise OperationalError("private-db-detail", None, RuntimeError("private-answer-detail"))

    async def scenario():
        manager = ChatbotManager(chat_engine, workflow_factory=lambda _: Workflow())
        await manager.start()
        try:
            conversation = manager.store.create(user)
            event.listen(chat_engine, "before_cursor_execute", fail_answer)
            accepted = await manager.submit(user, conversation.id, question())
            await asyncio.gather(*list(manager.tasks.values()))
            event.remove(chat_engine, "before_cursor_execute", fail_answer)
            failed = manager.store.get_request(user, accepted.id)
            assert failed.status == "FAILED"
            assert failed.failure_code == "CHATBOT_PROCESSING_FAILED"
            assert failed.answer is None
            current = manager.store.current(user)
            assert (
                current is not None and current.state_version == 1 and current.active_filters == {}
            )
            assert len(manager.store.history(user, conversation.id, None, 30).items) == 1
            retry = await manager.submit(user, conversation.id, question())
            await asyncio.gather(*list(manager.tasks.values()))
            assert manager.store.get_request(user, retry.id).status == "COMPLETED"
            assert len(manager.store.history(user, conversation.id, None, 30).items) == 3
        finally:
            if event.contains(chat_engine, "before_cursor_execute", fail_answer):
                event.remove(chat_engine, "before_cursor_execute", fail_answer)
            await manager.close()

    asyncio.run(scenario())
    captured = capsys.readouterr()
    assert "private-" not in captured.out + captured.err


def test_database_outage_during_both_terminal_writes_recovers_as_interrupted(chat_engine, user):
    class Workflow:
        async def run(self, context, *, capability, on_progress):
            return ChatExecution(result=result(), intent=ChatIntent(tool="properties"))

    async def scenario():
        manager = ChatbotManager(chat_engine, workflow_factory=lambda _: Workflow())
        await manager.start()
        transition = manager.store.transition

        def fail_terminal(*args, **kwargs):
            if kwargs.get("status") in ("COMPLETED", "FAILED"):
                raise OperationalError("unavailable database", None, RuntimeError("private-detail"))
            return transition(*args, **kwargs)

        try:
            conversation = manager.store.create(user)
            manager.store.transition = fail_terminal
            accepted = await manager.submit(user, conversation.id, question())
            await asyncio.gather(*list(manager.tasks.values()))
            manager.store.transition = transition
            incomplete = manager.store.get_request(user, accepted.id)
            assert incomplete.status == "RUNNING" and incomplete.answer is None
            with Session(chat_engine) as session:
                request = session.get(ChatRequest, accepted.id)
                assert request is not None
                request.heartbeat_at = now() - timedelta(seconds=100)
                session.add(request)
                session.commit()
            assert accepted.id in manager.store.interrupt_stale(uuid4(), 30)
            assert manager.store.get_request(user, accepted.id).status == "INTERRUPTED"
            assert len(manager.store.history(user, conversation.id, None, 30).items) == 1
        finally:
            manager.store.transition = transition
            await manager.close()

    asyncio.run(scenario())
