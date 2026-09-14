"""Server-owned tasks: disconnect never cancels execution; explicit cancel/delete do."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from uuid import UUID, uuid4

import structlog
from brokerage_ai.chatbot import ChatbotContextLimitError, ChatbotContractError
from brokerage_ai.core.errors import (
    ConfigurationError as AiConfigurationError,
)
from brokerage_ai.core.errors import (
    ProviderConfigurationError,
    ProviderOutputInvalidError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from sqlalchemy import Engine

from core.errors import ConfigurationError
from core.logging import exception_location
from domain.authentication.models import CurrentUser
from domain.chatbot.models import TERMINAL_STATUSES
from domain.chatbot.query import ChatLookup
from domain.chatbot.repository import ChatStore
from domain.chatbot.schemas import SubmitQuestion


class ChatbotManager:
    def __init__(
        self,
        engine: Engine,
        *,
        workflow_factory,
        request_timeout_seconds: float = 60,
        heartbeat_seconds=15,
        max_concurrent_requests=1,
    ):
        self.engine, self.workflow_factory = engine, workflow_factory
        self.store = ChatStore(engine)
        self.request_timeout_seconds = request_timeout_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.max_concurrent_requests = max_concurrent_requests
        self.instance_id = uuid4()
        self.tasks: dict[UUID, asyncio.Task] = {}
        self.users: dict[UUID, CurrentUser] = {}
        self.admission_lock = asyncio.Lock()
        self.maintenance_task: asyncio.Task | None = None
        self.closing = False

    async def start(self):
        await asyncio.to_thread(
            self.store.interrupt_stale, self.instance_id, self.heartbeat_seconds * 2
        )
        self.maintenance_task = asyncio.create_task(self._maintain(), name="chatbot-maintenance")

    async def close(self):
        self.closing = True
        if self.maintenance_task:
            self.maintenance_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.maintenance_task
        for request_id, task in list(self.tasks.items()):
            with suppress(Exception):
                await asyncio.to_thread(
                    self.store.transition,
                    self.users[request_id],
                    request_id,
                    status="INTERRUPTED",
                    failure_code="CHATBOT_INTERRUPTED",
                )
            task.cancel()
        if self.tasks:
            await asyncio.gather(*list(self.tasks.values()), return_exceptions=True)

    async def submit(self, user: CurrentUser, conversation_id: UUID, question: SubmitQuestion):
        from domain.chatbot.errors import ChatUnavailable

        async with self.admission_lock:
            if self.closing:
                raise ChatUnavailable()
            result, created = await asyncio.to_thread(
                self.store.accept,
                user,
                conversation_id,
                question,
                self.instance_id,
                self.request_timeout_seconds,
                can_accept=len(self.tasks) < self.max_concurrent_requests,
            )
            if created:
                self.users[result.id] = user
                task = asyncio.create_task(self._run(user, result.id), name=f"chatbot:{result.id}")
                self.tasks[result.id] = task
                task.add_done_callback(lambda completed, rid=result.id: self._done(rid, completed))
            return result

    def _done(self, request_id, task):
        # Consume unexpected exceptions; raw provider payloads are never logged.
        if not task.cancelled():
            task.exception()
        self.tasks.pop(request_id, None)
        self.users.pop(request_id, None)

    async def _run(self, user, request_id):
        try:
            async with asyncio.timeout(self.request_timeout_seconds):
                if not await asyncio.to_thread(
                    self.store.transition, user, request_id, status="RUNNING", stage="interpreting"
                ):
                    return
                context = await asyncio.to_thread(self.store.context, request_id)
                if context is None:
                    return
                workflow = await asyncio.to_thread(self.workflow_factory, user.brokerage_id)

                async def progress(stage):
                    if stage not in ("interpreting", "searching"):
                        return
                    if not await asyncio.to_thread(
                        self.store.transition, user, request_id, stage=stage
                    ):
                        raise asyncio.CancelledError

                async def searching(filters):
                    if not await asyncio.to_thread(
                        self.store.transition,
                        user,
                        request_id,
                        stage="searching",
                        search_filters=filters,
                    ):
                        raise asyncio.CancelledError

                execution = await workflow.run(
                    context,
                    capability=ChatLookup(self.engine, user.brokerage_id, on_search=searching),
                    on_progress=progress,
                )
                await asyncio.to_thread(
                    self.store.transition,
                    user,
                    request_id,
                    status="COMPLETED",
                    result=execution.result,
                    diagnostics={
                        "provider": execution.diagnostics.model_dump(mode="json")
                        if execution.diagnostics
                        else None,
                        "prompt_version": execution.prompt_version,
                        "workflow_version": execution.workflow_version,
                        "model_calls": execution.model_calls,
                    },
                )
        except asyncio.CancelledError:
            # Explicit cancel/delete are terminal. Shutdown marks INTERRUPTED first.
            with suppress(Exception):
                await asyncio.to_thread(
                    self.store.transition,
                    user,
                    request_id,
                    status="INTERRUPTED",
                    failure_code="CHATBOT_INTERRUPTED",
                )
            raise
        except Exception as error:
            if isinstance(error, (TimeoutError, ProviderTimeoutError)):
                code = "CHATBOT_TIMEOUT"
            elif isinstance(error, ChatbotContextLimitError):
                code = "CHATBOT_CONTEXT_LIMIT"
            elif isinstance(error, (ChatbotContractError, ProviderOutputInvalidError)):
                code = "CHATBOT_INVALID_OUTPUT"
            elif isinstance(error, ProviderRateLimitError):
                code = "CHATBOT_BUSY"
            elif isinstance(
                error,
                (
                    ProviderUnavailableError,
                    ProviderConfigurationError,
                    AiConfigurationError,
                    ConfigurationError,
                ),
            ):
                code = "CHATBOT_UNAVAILABLE"
            else:
                code = "CHATBOT_PROCESSING_FAILED"
            committed = False
            with suppress(Exception):
                committed = await asyncio.to_thread(
                    self.store.transition, user, request_id, status="FAILED", failure_code=code
                )
            if committed:
                structlog.get_logger(__name__).error(
                    "ai_terminal_failure",
                    source="chatbot",
                    request_id=str(request_id),
                    failure_code=code,
                    error_type=type(error).__name__,
                    location=exception_location(error),
                )

    async def _maintain(self):
        while True:
            await asyncio.sleep(min(self.heartbeat_seconds / 3, 5))
            for request_id, user in list(self.users.items()):
                try:
                    view = await asyncio.to_thread(self.store.get_request, user, request_id)
                    if view.status not in TERMINAL_STATUSES:
                        await asyncio.to_thread(self.store.transition, user, request_id)
                except Exception:
                    # A removed conversation has no heartbeat row. Keep provider work awaited:
                    # user cancellation cannot prove the remote server released its GPU slot.
                    pass

            with suppress(Exception):
                await asyncio.to_thread(
                    self.store.interrupt_stale, self.instance_id, self.heartbeat_seconds * 2
                )

    async def cancel(self, user, request_id):
        result = await asyncio.to_thread(self.store.cancel, user, request_id)
        return result

    async def remove(self, user, conversation_id):
        await asyncio.to_thread(self.store.remove, user, conversation_id)
        # Completion/progress sees the missing row and cannot recreate it. Keep the slot
        # until any in-flight provider/query returns or reaches the execution deadline.
