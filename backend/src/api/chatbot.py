from __future__ import annotations

import asyncio
import json
import time
from uuid import UUID

from brokerage_ai.chatbot import ChatResult
from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlmodel import Session

from core.errors import AuthenticationError, NotFoundError, ValidationError
from domain.authentication.models import CurrentUser
from domain.authentication.service import authenticate_session, validate_csrf
from domain.chatbot.errors import ChatUnavailable
from domain.chatbot.manager import ChatbotManager
from domain.chatbot.models import TERMINAL_STATUSES, now
from domain.chatbot.query import ChatLookup
from domain.chatbot.repository import ChatStore
from domain.chatbot.schemas import (
    ConversationView,
    CurrentConversation,
    HistoryView,
    RequestView,
    ResetFilters,
    SubmitQuestion,
)

router = APIRouter(prefix="/chatbot", tags=["chatbot"])


def chat_user(request: Request) -> CurrentUser:
    # This short session closes before StreamingResponse begins; SSE never holds a connection.
    config = request.app.state.config
    token = request.cookies.get(config.auth.session.cookie_name)
    if not token:
        raise AuthenticationError("UNAUTHENTICATED", "authentication is required")
    with Session(request.app.state.db_engine) as session:
        context = authenticate_session(session, config, token)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            validate_csrf(context, request.headers.get("X-CSRF-Token"))
        return context.user


def store(request: Request) -> ChatStore:
    return ChatStore(request.app.state.db_engine)


def manager(request: Request) -> ChatbotManager:
    result = getattr(request.app.state, "chatbot_manager", None)
    if result is None or not request.app.state.config.chatbot.enabled:
        raise ChatUnavailable()
    return result


def _private(response: Response):
    response.headers["Cache-Control"] = "no-store"


@router.get("/conversation", response_model=CurrentConversation)
def current(request: Request, response: Response, user: CurrentUser = Depends(chat_user)):
    _private(response)
    enabled = bool(
        request.app.state.config.chatbot.enabled
        and getattr(request.app.state, "chatbot_manager", None)
    )
    # Existing persisted history remains available when inference is intentionally disabled.
    return CurrentConversation(conversation=store(request).current(user), enabled=enabled)


@router.post("/conversations", response_model=ConversationView)
def create(request: Request, response: Response, user: CurrentUser = Depends(chat_user)):
    _private(response)
    manager(request)
    return store(request).create(user)


@router.get("/conversations/{conversation_id}/messages", response_model=HistoryView)
def history(
    conversation_id: UUID,
    request: Request,
    response: Response,
    before: int | None = Query(None, ge=1),
    limit: int = Query(30, ge=1, le=100),
    user: CurrentUser = Depends(chat_user),
):
    _private(response)
    return store(request).history(user, conversation_id, before, limit)


@router.post(
    "/conversations/{conversation_id}/requests", response_model=RequestView, status_code=202
)
async def submit(
    conversation_id: UUID,
    question: SubmitQuestion,
    request: Request,
    response: Response,
    user: CurrentUser = Depends(chat_user),
):
    _private(response)
    return await manager(request).submit(user, conversation_id, question)


@router.get("/requests/{request_id}", response_model=RequestView)
def get_request(
    request_id: UUID, request: Request, response: Response, user: CurrentUser = Depends(chat_user)
):
    _private(response)
    return store(request).get_request(user, request_id)


@router.post("/requests/{request_id}/cancel", response_model=RequestView)
async def cancel(
    request_id: UUID, request: Request, response: Response, user: CurrentUser = Depends(chat_user)
):
    _private(response)
    active = getattr(request.app.state, "chatbot_manager", None)
    if active:
        return await active.cancel(user, request_id)
    return await asyncio.to_thread(store(request).cancel, user, request_id)


@router.patch("/conversations/{conversation_id}/filters", response_model=ConversationView)
def reset(
    conversation_id: UUID,
    body: ResetFilters,
    request: Request,
    response: Response,
    user: CurrentUser = Depends(chat_user),
):
    _private(response)
    return store(request).reset(user, conversation_id, body.expected_version)


@router.delete("/conversations/{conversation_id}", status_code=204)
async def remove(conversation_id: UUID, request: Request, user: CurrentUser = Depends(chat_user)):
    active = getattr(request.app.state, "chatbot_manager", None)
    if active:
        await active.remove(user, conversation_id)
    else:
        await asyncio.to_thread(store(request).remove, user, conversation_id)
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@router.get("/requests/{request_id}/results", response_model=ChatResult)
def results(
    request_id: UUID,
    request: Request,
    response: Response,
    offset: int = Query(0, ge=0, le=100000),
    user: CurrentUser = Depends(chat_user),
):
    _private(response)
    item = store(request).get_request(user, request_id)
    payload = item.answer.result_payload if item.answer else None
    if (
        item.status != "COMPLETED"
        or payload is None
        or payload.kind not in ("properties", "buyers", "agenda")
    ):
        raise ValidationError("이 요청에는 조회 결과가 없어요.", "CHATBOT_NO_RESULTS")
    return ChatLookup(request.app.state.db_engine, user.brokerage_id).search(
        payload.filters, offset
    )


@router.get("/requests/{request_id}/events")
async def events(request_id: UUID, request: Request, user: CurrentUser = Depends(chat_user)):
    repository = store(request)
    initial = await asyncio.to_thread(repository.get_request, user, request_id)
    config = request.app.state.config.chatbot

    def encode(event_type: str, view: RequestView) -> str:
        event = {
            "schema_version": 1,
            "request_id": str(request_id),
            "revision": view.revision,
            "occurred_at": now().isoformat(),
            "type": event_type,
            "payload": view.model_dump(mode="json"),
        }
        return f"event: {event_type}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"

    async def stream():
        yield encode("snapshot", initial)
        if initial.status in TERMINAL_STATUSES:
            return
        revision, heartbeat_at = initial.revision, time.monotonic()
        while not await request.is_disconnected():
            await asyncio.sleep(config.poll_interval_seconds)
            if time.monotonic() - heartbeat_at >= config.heartbeat_seconds:
                try:
                    current_user = await asyncio.to_thread(chat_user, request)
                    if (current_user.id, current_user.brokerage_id) != (user.id, user.brokerage_id):
                        return
                except AuthenticationError:
                    return
                yield ": heartbeat\n\n"
                heartbeat_at = time.monotonic()
            try:
                view = await asyncio.to_thread(repository.get_request, user, request_id)
            except NotFoundError:
                return
            if view.revision > revision:
                event_type = view.status.lower() if view.status in TERMINAL_STATUSES else "progress"
                yield encode(event_type, view)
                revision = view.revision
            if view.status in TERMINAL_STATUSES:
                return

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
