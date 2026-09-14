"""Short transactions. Conversation locks serialize submit, terminal writes and deletion."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from uuid import UUID

from brokerage_ai.chatbot import ChatInput, ChatResult, CompletedTurn, ResultReference
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, col

from core.errors import NotFoundError, ValidationError
from domain.authentication.models import Brokerage, CurrentUser, UserRole
from domain.chatbot.errors import ChatBusy, ChatConflict
from domain.chatbot.models import ACTIVE_STATUSES, ChatRequest, Conversation, Message, now
from domain.chatbot.schemas import (
    ConversationView,
    HistoryView,
    MessageView,
    RequestView,
    SubmitQuestion,
)
from domain.time_keeper.models import today_in_business_timezone


def owned(
    session: Session, user: CurrentUser, conversation_id: UUID, *, lock=False
) -> Conversation:
    query = select(Conversation).where(
        col(Conversation.id) == conversation_id,
        col(Conversation.brokerage_id) == user.brokerage_id,
        col(Conversation.owner_user_id) == user.id,
    )
    if lock:
        query = query.with_for_update()
    item = session.execute(query).scalar_one_or_none()
    if item is None:
        raise NotFoundError()
    return item


def request_view(session: Session, item: ChatRequest) -> RequestView:
    answer = session.execute(
        select(Message).where(col(Message.request_id) == item.id, col(Message.role) == "assistant")
    ).scalar_one_or_none()
    return RequestView.model_validate(
        {
            "id": item.id,
            "conversation_id": item.conversation_id,
            "status": item.status,
            "stage": item.stage,
            "revision": item.revision,
            "failure_code": item.failure_code,
            "search_filters": item.search_filters,
            "answer": MessageView.model_validate(answer) if answer else None,
            "created_at": item.created_at,
            "completed_at": item.completed_at,
        }
    )


def conversation_view(session: Session, item: Conversation) -> ConversationView:
    active = session.execute(
        select(ChatRequest).where(
            col(ChatRequest.conversation_id) == item.id,
            col(ChatRequest.status).in_(ACTIVE_STATUSES),
        )
    ).scalar_one_or_none()
    return ConversationView(
        id=item.id,
        state_version=item.state_version,
        active_filters=item.active_filters,
        active_request=request_view(session, active) if active else None,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def next_sequence(session: Session, conversation_id: UUID) -> int:
    return (
        int(
            session.execute(
                select(func.coalesce(func.max(col(Message.sequence_no)), 0)).where(
                    col(Message.conversation_id) == conversation_id
                )
            ).scalar_one()
        )
        + 1
    )


class ChatStore:
    def __init__(self, engine: Engine):
        self.engine = engine

    def current(self, user: CurrentUser) -> ConversationView | None:
        with Session(self.engine) as session:
            item = session.execute(
                select(Conversation).where(
                    col(Conversation.brokerage_id) == user.brokerage_id,
                    col(Conversation.owner_user_id) == user.id,
                )
            ).scalar_one_or_none()
            return conversation_view(session, item) if item else None

    def create(self, user: CurrentUser) -> ConversationView:
        with Session(self.engine) as session:
            item = Conversation(brokerage_id=user.brokerage_id, owner_user_id=user.id)
            session.execute(
                insert(Conversation)
                .values(**item.model_dump())
                .on_conflict_do_nothing(index_elements=["brokerage_id", "owner_user_id"])
            )
            session.commit()
        result = self.current(user)
        assert result is not None
        return result

    def history(
        self, user: CurrentUser, conversation_id: UUID, before: int | None, limit: int
    ) -> HistoryView:
        with Session(self.engine) as session:
            owned(session, user, conversation_id)
            query = select(Message).where(col(Message.conversation_id) == conversation_id)
            if before is not None:
                query = query.where(col(Message.sequence_no) < before)
            rows = list(
                session.execute(
                    query.order_by(col(Message.sequence_no).desc()).limit(limit + 1)
                ).scalars()
            )
            more = len(rows) > limit
            rows = rows[:limit]
            return HistoryView(
                items=[MessageView.model_validate(row) for row in reversed(rows)],
                next_cursor=rows[-1].sequence_no if more else None,
            )

    def get_request(self, user: CurrentUser, request_id: UUID) -> RequestView:
        with Session(self.engine) as session:
            item = session.get(ChatRequest, request_id)
            if item is None:
                raise NotFoundError()
            owned(session, user, item.conversation_id)
            return request_view(session, item)

    def _context(self, session, conversation, question: SubmitQuestion) -> ChatInput:
        completed = list(
            session.execute(
                select(ChatRequest)
                .where(
                    col(ChatRequest.conversation_id) == conversation.id,
                    col(ChatRequest.status) == "COMPLETED",
                )
                .order_by(col(ChatRequest.completed_at).desc(), col(ChatRequest.id).desc())
                .limit(2)
            ).scalars()
        )
        history = []
        eligible = {}
        for request in reversed(completed):
            messages = list(
                session.execute(
                    select(Message).where(col(Message.request_id) == request.id)
                ).scalars()
            )
            user_message = next((m for m in messages if m.role == "user"), None)
            assistant = next((m for m in messages if m.role == "assistant"), None)
            if user_message and assistant:
                payload = assistant.result_payload or {}
                summary = f"{payload.get('kind', 'help')}: {payload.get('total', 0)}건"
                history.append(CompletedTurn(question=user_message.content, answer_summary=summary))
                if payload.get("kind") in ("properties", "buyers", "agenda"):
                    eligible[assistant.id] = payload
        reference = None
        if question.reference_message_id is not None:
            payload = eligible.get(question.reference_message_id)
            if payload is None:
                raise ValidationError(
                    "최근 두 번의 완료된 검색 결과만 참조할 수 있어요.", "CHATBOT_REFERENCE_EXPIRED"
                )
            # Reference rows stay inside the Backend port; workflow omits their content from prompt.
            reference = ResultReference(kind=payload["kind"], items=payload["items"])
        return ChatInput(
            question=question.question,
            active_filters=conversation.active_filters,
            history=tuple(history),
            reference=reference,
            as_of=today_in_business_timezone(),
        )

    def accept(
        self,
        user: CurrentUser,
        conversation_id: UUID,
        question: SubmitQuestion,
        instance_id: UUID,
        timeout: float,
        *,
        can_accept: bool = True,
    ) -> tuple[RequestView, bool]:
        fingerprint = hashlib.sha256(
            json.dumps(
                question.model_dump(mode="json"), sort_keys=True, ensure_ascii=False
            ).encode()
        ).hexdigest()
        with Session(self.engine) as session:
            # Model-profile changes hold the same brokerage lock before checking active requests.
            brokerage = session.execute(
                select(Brokerage).where(col(Brokerage.id) == user.brokerage_id).with_for_update()
            ).scalar_one_or_none()
            if brokerage is None:
                raise NotFoundError()
            conversation = owned(session, user, conversation_id, lock=True)
            existing = session.execute(
                select(ChatRequest).where(
                    col(ChatRequest.conversation_id) == conversation_id,
                    col(ChatRequest.client_request_id) == question.client_request_id,
                )
            ).scalar_one_or_none()
            if existing:
                if existing.fingerprint != fingerprint:
                    raise ChatConflict(
                        "CHATBOT_IDEMPOTENCY_CONFLICT",
                        "같은 요청 키에 다른 질문을 사용할 수 없어요.",
                    )
                return request_view(session, existing), False
            active = session.execute(
                select(col(ChatRequest.id)).where(
                    col(ChatRequest.conversation_id) == conversation_id,
                    col(ChatRequest.status).in_(ACTIVE_STATUSES),
                )
            ).first()
            if active or conversation.state_version != question.expected_version:
                raise ChatConflict()
            if not can_accept:
                raise ChatBusy()
            context = self._context(session, conversation, question)
            item = ChatRequest(
                brokerage_id=user.brokerage_id,
                conversation_id=conversation_id,
                client_request_id=question.client_request_id,
                fingerprint=fingerprint,
                owner_instance_id=instance_id,
                deadline_at=now() + timedelta(seconds=timeout),
                context_snapshot=context.model_dump(mode="json"),
            )
            session.add(item)
            session.flush()
            session.add(
                Message(
                    brokerage_id=user.brokerage_id,
                    conversation_id=conversation_id,
                    request_id=item.id,
                    sequence_no=next_sequence(session, conversation_id),
                    role="user",
                    content=question.question,
                )
            )
            conversation.updated_at = now()
            session.add(conversation)
            session.commit()
            return request_view(session, item), True

    def context(self, request_id: UUID) -> ChatInput | None:
        with Session(self.engine) as session:
            item = session.get(ChatRequest, request_id)
            return (
                ChatInput.model_validate(item.context_snapshot)
                if item and item.status in ACTIVE_STATUSES
                else None
            )

    def transition(
        self,
        user: CurrentUser,
        request_id: UUID,
        *,
        status: str | None = None,
        stage: str | None = None,
        result: ChatResult | None = None,
        failure_code: str | None = None,
        diagnostics: dict | None = None,
        search_filters: dict | None = None,
    ) -> bool:
        with Session(self.engine) as session:
            item = session.get(ChatRequest, request_id)
            if item is None:
                return False
            try:
                conversation = owned(session, user, item.conversation_id, lock=True)
            except NotFoundError:
                return False
            # Refresh after locking: another transaction may have terminalized or deleted this row.
            session.expire(item)
            session.refresh(item)
            if item.status not in ACTIVE_STATUSES:
                return False
            item.heartbeat_at = now()
            if search_filters is not None:
                item.search_filters = search_filters
            if status or stage or search_filters is not None:
                item.revision += 1
            if stage:
                item.stage = stage
            if status:
                item.status = status
                if status == "RUNNING":
                    item.started_at = now()
                else:
                    item.completed_at = now()
                    item.stage = status.lower()
                    item.failure_code = failure_code
                    if diagnostics is not None:
                        item.diagnostics = diagnostics
                    if result is not None:
                        session.add(
                            Message(
                                brokerage_id=user.brokerage_id,
                                conversation_id=conversation.id,
                                request_id=item.id,
                                sequence_no=next_sequence(session, conversation.id),
                                role="assistant",
                                content=result.text,
                                result_payload=result.model_dump(mode="json"),
                            )
                        )
                        if result.kind in ("properties", "buyers", "agenda"):
                            conversation.active_filters = result.filters
                            conversation.state_version += 1
                    conversation.updated_at = now()
                    session.add(conversation)
            session.add(item)
            session.commit()
            return True

    def cancel(self, user: CurrentUser, request_id: UUID) -> RequestView:
        self.get_request(user, request_id)
        self.transition(user, request_id, status="CANCELLED")
        return self.get_request(user, request_id)

    def reset(self, user: CurrentUser, conversation_id: UUID, expected: int) -> ConversationView:
        with Session(self.engine) as session:
            conversation = owned(session, user, conversation_id, lock=True)
            if (
                conversation.state_version != expected
                or session.execute(
                    select(col(ChatRequest.id)).where(
                        col(ChatRequest.conversation_id) == conversation_id,
                        col(ChatRequest.status).in_(ACTIVE_STATUSES),
                    )
                ).first()
            ):
                raise ChatConflict()
            conversation.active_filters = {}
            conversation.state_version += 1
            conversation.updated_at = now()
            session.add(conversation)
            session.commit()
            return conversation_view(session, conversation)

    def remove(self, user: CurrentUser, conversation_id: UUID) -> list[UUID]:
        with Session(self.engine) as session:
            conversation = owned(session, user, conversation_id, lock=True)
            ids = list(
                session.execute(
                    select(col(ChatRequest.id)).where(
                        col(ChatRequest.conversation_id) == conversation_id,
                        col(ChatRequest.status).in_(ACTIVE_STATUSES),
                    )
                ).scalars()
            )
            session.execute(delete(Conversation).where(col(Conversation.id) == conversation.id))
            session.commit()
            return ids

    def interrupt_stale(self, instance_id: UUID, stale_seconds: float) -> list[UUID]:
        # Read candidates without locks, then use the same conversation-first order as all writers.
        with Session(self.engine) as session:
            rows = session.execute(
                select(
                    col(ChatRequest.id),
                    col(Conversation.owner_user_id),
                    col(Conversation.brokerage_id),
                )
                .join(Conversation, col(Conversation.id) == col(ChatRequest.conversation_id))
                .where(
                    col(ChatRequest.status).in_(ACTIVE_STATUSES),
                    (col(ChatRequest.deadline_at) < now())
                    | (col(ChatRequest.heartbeat_at) < now() - timedelta(seconds=stale_seconds)),
                )
            ).all()
        changed = []
        for request_id, owner_id, brokerage_id in rows:
            user = CurrentUser(owner_id, brokerage_id, "", "", UserRole.STAFF)
            with Session(self.engine) as session:
                request = session.get(ChatRequest, request_id)
                if request is None:
                    continue
                try:
                    owned(session, user, request.conversation_id, lock=True)
                except NotFoundError:
                    continue
                session.refresh(request)
                if request.status not in ACTIVE_STATUSES:
                    continue
                if request.deadline_at >= now() and request.heartbeat_at >= now() - timedelta(
                    seconds=stale_seconds
                ):
                    continue
                request.status, request.stage = "INTERRUPTED", "interrupted"
                request.failure_code = "CHATBOT_INTERRUPTED"
                request.completed_at, request.revision = now(), request.revision + 1
                session.add(request)
                session.commit()
                changed.append(request_id)
        return changed
