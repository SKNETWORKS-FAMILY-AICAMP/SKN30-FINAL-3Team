"""Real PostgreSQL invariants and lifecycle checks in a disposable per-module schema."""

from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from typing import Literal
from uuid import uuid4

import pytest
from brokerage_ai.chatbot import ChatExecution, ChatFilters, ChatInput, ChatIntent, ChatResult
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, create_engine

from core.errors import NotFoundError, ValidationError
from domain.authentication.models import CurrentUser, UserRole
from domain.chatbot.errors import ChatConflict
from domain.chatbot.manager import ChatbotManager
from domain.chatbot.models import ChatRequest, now
from domain.chatbot.query import ChatLookup, normalize
from domain.chatbot.repository import ChatStore
from domain.chatbot.schemas import SubmitQuestion

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DB_URL"), reason="isolated TEST_DB_URL required"
)
MIGRATIONS = Path(__file__).resolve().parents[3] / "docs/db/migrate"


@pytest.fixture(scope="module")
def chat_engine():
    schema = f"chatbot_test_{uuid4().hex}"
    admin = create_engine(os.environ["TEST_DB_URL"])
    with admin.begin() as connection:
        connection.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_engine(
        os.environ["TEST_DB_URL"], connect_args={"options": f"-csearch_path={schema},public"}
    )
    try:
        with engine.begin() as connection:
            for path in sorted(MIGRATIONS.glob("*.sql")):
                connection.exec_driver_sql(path.read_text())
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


@pytest.fixture
def user(chat_engine):
    with chat_engine.begin() as connection:
        brokerage_id = connection.execute(
            text("INSERT INTO brokerage(name) VALUES ('합성 검증') RETURNING id")
        ).scalar_one()
        user_id = connection.execute(
            text(
                "INSERT INTO app_user(brokerage_id,login_id,password_hash,display_name,role)"
                " VALUES(:b,:l,'unused','합성','OWNER') RETURNING id"
            ),
            {"b": brokerage_id, "l": uuid4().hex},
        ).scalar_one()
    return CurrentUser(user_id, brokerage_id, "synthetic", "synthetic", UserRole.OWNER)


def question(version=1, **kwargs):
    return SubmitQuestion(
        question=kwargs.pop("question", "매물 보여줘"),
        client_request_id=kwargs.pop("client_request_id", uuid4()),
        expected_version=version,
        **kwargs,
    )


def result(kind: Literal["properties", "buyers", "agenda"] = "properties", **kwargs):
    return ChatResult(
        kind=kind,
        text="조건에 맞는 매물 0건을 찾았어요.",
        filters={"tool": kind},
        as_of=now(),
        **kwargs,
    )


def test_atomic_submit_dedupe_and_version(chat_engine, user):
    store = ChatStore(chat_engine)
    conversation = store.create(user)
    assert store.create(user).id == conversation.id
    body = question()
    first, created = store.accept(user, conversation.id, body, uuid4(), 60)
    assert created
    duplicate, created = store.accept(user, conversation.id, body, uuid4(), 60, can_accept=False)
    assert not created and duplicate.id == first.id
    with pytest.raises(ChatConflict):
        store.accept(
            user,
            conversation.id,
            question(client_request_id=body.client_request_id, question="다른 질문"),
            uuid4(),
            60,
        )
    with pytest.raises(ChatConflict):
        store.accept(user, conversation.id, question(), uuid4(), 60)
    assert len(store.history(user, conversation.id, None, 30).items) == 1
    assert store.transition(user, first.id, status="COMPLETED", result=result())
    assert not store.transition(user, first.id, status="FAILED")
    current = store.current(user)
    assert current is not None and current.state_version == 2
    assert len(store.history(user, conversation.id, None, 30).items) == 2
    with pytest.raises(ChatConflict):
        store.accept(user, conversation.id, question(), uuid4(), 60)


def test_owner_and_tenant_checks_and_fk(chat_engine, user):
    store = ChatStore(chat_engine)
    conversation = store.create(user)
    accepted, _ = store.accept(user, conversation.id, question(), uuid4(), 60)
    foreign_users = [
        CurrentUser(user.id + 100000, user.brokerage_id, "", "", UserRole.STAFF),
        CurrentUser(user.id, user.brokerage_id + 100000, "", "", UserRole.STAFF),
    ]
    for foreign in foreign_users:
        for operation in (
            lambda foreign=foreign: store.get_request(foreign, accepted.id),
            lambda foreign=foreign: store.history(foreign, conversation.id, None, 30),
            lambda foreign=foreign: store.cancel(foreign, accepted.id),
            lambda foreign=foreign: store.remove(foreign, conversation.id),
            lambda foreign=foreign: store.reset(foreign, conversation.id, 1),
            lambda foreign=foreign: store.accept(foreign, conversation.id, question(), uuid4(), 60),
        ):
            with pytest.raises(NotFoundError):
                operation()
    with pytest.raises(IntegrityError), chat_engine.begin() as connection:
        connection.execute(
            text("INSERT INTO chat_conversation(id,brokerage_id,owner_user_id) VALUES(:i,:b,:u)"),
            {"i": uuid4(), "b": user.brokerage_id + 100000, "u": user.id},
        )


def test_concurrent_submit_and_delete_complete_race(chat_engine, user):
    store = ChatStore(chat_engine)
    conversation = store.create(user)
    body = question()
    with ThreadPoolExecutor(2) as executor:
        futures = [
            executor.submit(store.accept, user, conversation.id, body, uuid4(), 60)
            for _ in range(2)
        ]
        values = [future.result() for future in futures]
    assert sum(created for _, created in values) == 1
    request_id = values[0][0].id
    with ThreadPoolExecutor(2) as executor:
        finish = executor.submit(
            store.transition, user, request_id, status="COMPLETED", result=result()
        )
        remove = executor.submit(store.remove, user, conversation.id)
        finish.result()
        remove.result()
    assert store.current(user) is None
    assert not store.transition(user, request_id, status="COMPLETED", result=result())
    with Session(chat_engine) as session:
        assert (
            session.execute(
                text("SELECT count(*) FROM chat_message WHERE request_id=:i"), {"i": request_id}
            ).scalar_one()
            == 0
        )
        assert session.get(ChatRequest, request_id) is None


def test_history_context_only_two_completed_pairs_and_reset(chat_engine, user):
    store = ChatStore(chat_engine)
    conversation = store.create(user)
    assistant_ids = []
    for index in range(3):
        accepted, _ = store.accept(
            user, conversation.id, question(index + 1, question=f"질문 {index}"), uuid4(), 60
        )
        store.transition(user, accepted.id, status="COMPLETED", result=result())
        answer = store.get_request(user, accepted.id).answer
        assert answer is not None
        assistant_ids.append(answer.id)
    failed, _ = store.accept(user, conversation.id, question(4), uuid4(), 60)
    store.transition(user, failed.id, status="FAILED")
    with pytest.raises(ValidationError):
        store.accept(
            user, conversation.id, question(4, reference_message_id=assistant_ids[0]), uuid4(), 60
        )
    accepted, _ = store.accept(user, conversation.id, question(4), uuid4(), 60)
    context = store.context(accepted.id)
    assert context is not None
    assert [turn.question for turn in context.history] == ["질문 1", "질문 2"]
    assert context.active_filters == {"tool": "properties"}
    store.cancel(user, accepted.id)
    page = store.history(user, conversation.id, None, 3)
    older = store.history(user, conversation.id, page.next_cursor, 30)
    assert not set(m.id for m in page.items).intersection(m.id for m in older.items)
    reset = store.reset(user, conversation.id, 4)
    assert reset.state_version == 5 and reset.active_filters == {}
    assert len(store.history(user, conversation.id, None, 100).items) == 8


def test_stale_execution_interrupts_without_replay(chat_engine, user):
    store = ChatStore(chat_engine)
    conversation = store.create(user)
    accepted, _ = store.accept(user, conversation.id, question(), uuid4(), 60)
    with Session(chat_engine) as session:
        record = session.get(ChatRequest, accepted.id)
        assert record is not None
        record.heartbeat_at = now() - timedelta(seconds=100)
        session.add(record)
        session.commit()
    assert store.interrupt_stale(uuid4(), 30) == [accepted.id]
    assert store.get_request(user, accepted.id).status == "INTERRUPTED"
    assert store.interrupt_stale(uuid4(), 30) == []
    assert len(store.history(user, conversation.id, None, 30).items) == 1


def test_server_task_runs_without_sse_and_cancel_keeps_terminal(chat_engine, user):
    class Workflow:
        def __init__(self):
            self.gate = asyncio.Event()

        async def run(self, context, *, capability, on_progress):
            await on_progress("searching")
            await self.gate.wait()
            return ChatExecution(result=result(), intent=ChatIntent(tool="properties"))

    async def scenario():
        workflow = Workflow()
        manager = ChatbotManager(chat_engine, workflow_factory=lambda _: workflow)
        await manager.start()
        try:
            conversation = manager.store.create(user)
            accepted = await manager.submit(user, conversation.id, question())
            await asyncio.sleep(0.05)
            assert manager.store.get_request(user, accepted.id).status == "RUNNING"
            workflow.gate.set()
            await asyncio.gather(*list(manager.tasks.values()))
            assert manager.store.get_request(user, accepted.id).status == "COMPLETED"
            workflow.gate.clear()
            accepted = await manager.submit(user, conversation.id, question(2))
            await asyncio.sleep(0.05)
            await manager.cancel(user, accepted.id)
            workflow.gate.set()
            await asyncio.gather(*list(manager.tasks.values()), return_exceptions=True)
            assert manager.store.get_request(user, accepted.id).status == "CANCELLED"
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_query_latest_listing_null_price_and_exact_total(chat_engine, user):
    with chat_engine.begin() as connection:
        complex_id = connection.execute(
            text(
                "INSERT INTO property_complex(brokerage_id,name) VALUES(:b,'합성단지') RETURNING id"
            ),
            {"b": user.brokerage_id},
        ).scalar_one()
        for index in range(13):
            unit = connection.execute(
                text(
                    "INSERT INTO property_unit(brokerage_id,complex_id,"
                    "unit_number,exclusive_area_sqm)"
                    " VALUES(:b,:c,:n,84) RETURNING id"
                ),
                {"b": user.brokerage_id, "c": complex_id, "n": str(index)},
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO property_listing(brokerage_id,unit_id,"
                    "is_sale_available,sale_price,received_at)"
                    " VALUES(:b,:u,true,200000000,'2026-08-01')"
                ),
                {"b": user.brokerage_id, "u": unit},
            )
            connection.execute(
                text(
                    "INSERT INTO property_listing(brokerage_id,unit_id,"
                    "is_sale_available,sale_price,received_at)"
                    " VALUES(:b,:u,true,:p,'2026-09-01')"
                ),
                {"b": user.brokerage_id, "u": unit, "p": None if index == 12 else 500000000},
            )
    lookup = ChatLookup(chat_engine, user.brokerage_id)
    filters = normalize(
        ChatIntent(
            tool="properties",
            filters=ChatFilters(transaction_type="SALE", price_expression="5억 이하"),
        ),
        ChatInput(question="5억 이하 매매", as_of=date(2026, 9, 8)),
    )
    page = lookup.search(filters)
    assert page.total == 12 and len(page.items) == 10
    more = lookup.search(filters, 10)
    assert more.total == 12 and len(more.items) == 2
    assert not set(item.id for item in page.items).intersection(item.id for item in more.items)
    filters = normalize(
        ChatIntent(
            tool="properties",
            filters=ChatFilters(transaction_type="SALE", price_expression="3억 이하"),
        ),
        ChatInput(question="3억 이하 매매", as_of=date(2026, 9, 8)),
    )
    assert lookup.search(filters).total == 0  # Older cheap listing is not selected after filtering.


def test_agenda_period_before_count_and_no_category_cap(chat_engine, user):
    with chat_engine.begin() as connection:
        for index in range(12):
            connection.execute(
                text(
                    "INSERT INTO calendar_event(brokerage_id,title,event_date)"
                    " VALUES(:b,:t,'2026-09-08')"
                ),
                {"b": user.brokerage_id, "t": f"합성 일정 {index}"},
            )
        connection.execute(
            text(
                "INSERT INTO calendar_event(brokerage_id,title,event_date)"
                " VALUES(:b,'범위 밖','2026-10-01')"
            ),
            {"b": user.brokerage_id},
        )
    filters = normalize(
        ChatIntent(tool="agenda", filters=ChatFilters(date_expression="이번 달")),
        ChatInput(question="이번달일정", as_of=date(2026, 9, 8)),
    )
    lookup = ChatLookup(chat_engine, user.brokerage_id)
    assert lookup.search(filters).total == 12
    assert len(lookup.search(filters).items) == 10
    assert len(lookup.search(filters, 10).items) == 2


def test_http_auth_csrf_owner_and_sse_snapshot(chat_engine, user, config):
    import json

    from fastapi.testclient import TestClient

    from domain.authentication.models import UserSession
    from domain.authentication.service import hash_token
    from main import create_app

    class Workflow:
        async def run(self, context, *, capability, on_progress):
            await on_progress("searching")
            await asyncio.sleep(0.05)
            return ChatExecution(result=result(), intent=ChatIntent(tool="properties"))

    config = config.model_copy(
        update={"chatbot": config.chatbot.model_copy(update={"enabled": True})}
    )
    app = create_app(
        config=config,
        chatbot_manager_factory=lambda _: ChatbotManager(
            chat_engine, workflow_factory=lambda _: Workflow()
        ),
    )
    app.state.db_engine.dispose()
    app.state.db_engine = chat_engine
    token, csrf = uuid4().hex, uuid4().hex
    with Session(chat_engine) as session:
        session.add(
            UserSession(
                brokerage_id=user.brokerage_id,
                user_id=user.id,
                session_token_hash=hash_token(token),
                csrf_token_hash=hash_token(csrf),
                created_at=now(),
                last_seen_at=now(),
                idle_expires_at=now() + timedelta(hours=1),
                absolute_expires_at=now() + timedelta(hours=1),
            )
        )
        session.commit()
    with TestClient(app) as client:
        prefix = "/api/v1/chatbot"
        assert client.get(prefix + "/conversation").status_code == 401
        client.cookies.set(config.auth.session.cookie_name, token)
        assert client.post(prefix + "/conversations").status_code == 403
        client.headers["X-CSRF-Token"] = csrf
        conversation = client.post(prefix + "/conversations")
        assert conversation.status_code == 200, conversation.text
        conversation_id = conversation.json()["id"]
        accepted = client.post(
            f"{prefix}/conversations/{conversation_id}/requests",
            json=question().model_dump(mode="json"),
        )
        assert accepted.status_code == 202, accepted.text
        request_id = accepted.json()["id"]
        streamed = client.get(f"{prefix}/requests/{request_id}/events")
        assert streamed.status_code == 200
        assert streamed.headers["cache-control"] == "no-store"
        events = [
            json.loads(line[6:]) for line in streamed.text.splitlines() if line.startswith("data: ")
        ]
        assert events[0]["type"] == "snapshot"
        assert events[-1]["payload"]["status"] == "COMPLETED"
        revisions = [event["revision"] for event in events]
        assert revisions == sorted(set(revisions))
        assert client.get(f"{prefix}/requests/{request_id}").json()["answer"] is not None
        assert client.get(f"{prefix}/requests/{uuid4()}/events").status_code == 404
        assert (
            client.get(f"{prefix}/conversations/{conversation_id}/messages").json()["items"][-1][
                "role"
            ]
            == "assistant"
        )
        # Owner boundary uses real authentication, even for another user in this brokerage.
        with chat_engine.begin() as connection:
            other_user_id = connection.execute(
                text(
                    "INSERT INTO app_user(brokerage_id,login_id,password_hash,display_name,role)"
                    " VALUES(:b,:l,'unused','합성','STAFF') RETURNING id"
                ),
                {"b": user.brokerage_id, "l": uuid4().hex},
            ).scalar_one()
            connection.execute(
                text("UPDATE user_session SET user_id=:u WHERE session_token_hash=:h"),
                {"u": other_user_id, "h": hash_token(token)},
            )
        for path in (
            f"/requests/{request_id}",
            f"/requests/{request_id}/events",
            f"/requests/{request_id}/results",
            f"/conversations/{conversation_id}/messages",
        ):
            assert client.get(prefix + path).status_code == 404
        assert client.delete(f"{prefix}/conversations/{conversation_id}").status_code == 404
        assert client.post(f"{prefix}/requests/{request_id}/cancel").status_code == 404


def test_deadline_and_shutdown_persist_terminal(chat_engine, user):
    class SlowWorkflow:
        async def run(self, context, *, capability, on_progress):
            await asyncio.sleep(30)

    async def scenario():
        manager = ChatbotManager(
            chat_engine, workflow_factory=lambda _: SlowWorkflow(), request_timeout_seconds=0.1
        )
        await manager.start()
        conversation = manager.store.create(user)
        first = await manager.submit(user, conversation.id, question())
        await asyncio.gather(*list(manager.tasks.values()))
        assert manager.store.get_request(user, first.id).failure_code == "CHATBOT_TIMEOUT"
        manager.request_timeout_seconds = 60
        second = await manager.submit(user, conversation.id, question())
        await asyncio.sleep(0.03)
        await manager.close()
        assert manager.store.get_request(user, second.id).status == "INTERRUPTED"
        assert not manager.tasks

    asyncio.run(scenario())


def test_buyer_actual_vocabulary_budget_unknown_and_area(chat_engine, user):
    with chat_engine.begin() as connection:
        party_id = connection.execute(
            text(
                "INSERT INTO party(brokerage_id,party_type,name)"
                " VALUES(:b,'PERSON','합성 인물') RETURNING id"
            ),
            {"b": user.brokerage_id},
        ).scalar_one()
        for demand, low, high in [
            ("매수", 300000000, 500000000),
            ("전세", 300000000, 500000000),
            ("매수", None, None),
            ("매수", 1000000000, None),
            ("매수", None, 1000000000),
            ("매수", 600000000, 800000000),
        ]:
            connection.execute(
                text(
                    "INSERT INTO property_requirement(brokerage_id,party_id,demand_type,"
                    "min_budget_amount,max_budget_amount)"
                    " VALUES(:b,:p,:d,:lo,:hi)"
                ),
                {"b": user.brokerage_id, "p": party_id, "d": demand, "lo": low, "hi": high},
            )
    lookup = ChatLookup(chat_engine, user.brokerage_id)
    request = ChatInput(question="5억 이하 매수 의뢰", as_of=date(2026, 9, 8))
    intent = ChatIntent(
        tool="buyers", filters=ChatFilters(transaction_type="SALE", price_expression="5억 이하")
    )
    page = asyncio.run(lookup.execute(intent, request))
    assert page.total == 1
    assert "합성 인물" not in page.model_dump_json()
    assert "겹치는" in page.text
    area = asyncio.run(
        lookup.execute(
            ChatIntent(
                tool="buyers",
                filters=ChatFilters(area_expression="84㎡ 이상", area_basis="exclusive"),
            ),
            request,
        )
    )
    assert area.kind == "clarification"
    assert "기준이 저장되어 있지 않아" in area.text


def test_complex_ambiguity_and_escaped_wildcard(chat_engine, user):
    with chat_engine.begin() as connection:
        for name in ("합성단지 1", "합성단지 2"):
            connection.execute(
                text("INSERT INTO property_complex(brokerage_id,name) VALUES(:b,:n)"),
                {"b": user.brokerage_id, "n": name},
            )
    lookup = ChatLookup(chat_engine, user.brokerage_id)
    request = ChatInput(question="합성단지 매물", as_of=date(2026, 9, 8))
    page = asyncio.run(
        lookup.execute(
            ChatIntent(tool="properties", filters=ChatFilters(complex_name="합성단지")), request
        )
    )
    assert page.kind == "clarification"
    assert "여러 단지" in page.text
    page = asyncio.run(
        lookup.execute(
            ChatIntent(tool="properties", filters=ChatFilters(complex_name="%")), request
        )
    )
    assert page.kind == "properties" and page.total == 0


def test_cancel_retains_admission_until_database_thread_exits(chat_engine, user, monkeypatch):
    import threading

    import domain.chatbot.manager as manager_module
    from domain.chatbot.errors import ChatBusy

    entered, release = threading.Event(), threading.Event()

    class SlowLookup(ChatLookup):
        def search(self, filters, offset=0):
            entered.set()
            assert release.wait(5)
            return result()

    class Workflow:
        async def run(self, context, *, capability, on_progress):
            intent = ChatIntent(tool="properties")
            found = await capability.execute(intent, context)
            return ChatExecution(result=found, intent=intent)

    monkeypatch.setattr(manager_module, "ChatLookup", SlowLookup)

    async def scenario():
        manager = ChatbotManager(chat_engine, workflow_factory=lambda _: Workflow())
        await manager.start()
        try:
            conversation = manager.store.create(user)
            accepted = await manager.submit(user, conversation.id, question())
            assert await asyncio.to_thread(entered.wait, 2)
            searching = manager.store.get_request(user, accepted.id)
            assert searching.search_filters is not None
            assert searching.search_filters["tool"] == "properties"
            await manager.cancel(user, accepted.id)
            await asyncio.sleep(0.03)
            assert accepted.id in manager.tasks
            with pytest.raises(ChatBusy):
                await manager.submit(user, conversation.id, question())
            release.set()
            await asyncio.gather(*list(manager.tasks.values()), return_exceptions=True)
            assert not manager.tasks
            assert manager.store.get_request(user, accepted.id).status == "CANCELLED"
        finally:
            release.set()
            await manager.close()

    asyncio.run(scenario())


def test_cancel_retains_remote_provider_slot_without_cancelling_it(chat_engine, user):
    from domain.chatbot.errors import ChatBusy

    class BlockingProviderWorkflow:
        def __init__(self):
            self.entered = asyncio.Event()
            self.release = asyncio.Event()
            self.cancelled = False

        async def run(self, context, *, capability, on_progress):
            self.entered.set()
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
            await on_progress("searching")
            raise AssertionError("cancelled request must not reach another capability")

    async def scenario():
        workflow = BlockingProviderWorkflow()
        manager = ChatbotManager(chat_engine, workflow_factory=lambda _: workflow)
        await manager.start()
        try:
            conversation = manager.store.create(user)
            accepted = await manager.submit(user, conversation.id, question())
            await workflow.entered.wait()
            await manager.cancel(user, accepted.id)
            await asyncio.sleep(0.02)
            assert manager.store.get_request(user, accepted.id).status == "CANCELLED"
            assert not workflow.cancelled and accepted.id in manager.tasks
            with pytest.raises(ChatBusy):
                await manager.submit(user, conversation.id, question())
            workflow.release.set()
            await asyncio.gather(*list(manager.tasks.values()), return_exceptions=True)
            assert not manager.tasks
            assert manager.store.get_request(user, accepted.id).status == "CANCELLED"
        finally:
            workflow.release.set()
            await manager.close()

    asyncio.run(scenario())


def test_reference_lookup_is_bounded_under_table_lock(chat_engine, user, monkeypatch):
    from brokerage_ai.chatbot import ChatAction, ChatResultItem, ResultReference
    from sqlalchemy.exc import DBAPIError

    import domain.chatbot.query as query_module

    monkeypatch.setattr(query_module, "QUERY_TIMEOUT_MS", 50)
    with chat_engine.begin() as connection:
        event_id = connection.execute(
            text(
                "INSERT INTO calendar_event(brokerage_id,title,event_date)"
                " VALUES(:b,'합성 잠금 검증','2026-09-08') RETURNING id"
            ),
            {"b": user.brokerage_id},
        ).scalar_one()
    request = ChatInput(
        question="첫번째 일정 열어",
        as_of=date(2026, 9, 8),
        reference=ResultReference(
            kind="agenda",
            items=(
                ChatResultItem(
                    id=str(event_id),
                    title="합성 잠금 검증",
                    action=ChatAction(
                        type="open_calendar", target_id=event_id, label="캘린더 보기"
                    ),
                ),
            ),
        ),
    )
    with chat_engine.begin() as blocker:
        blocker.execute(text("LOCK TABLE calendar_event IN ACCESS EXCLUSIVE MODE"))
        with pytest.raises(DBAPIError):
            ChatLookup(chat_engine, user.brokerage_id)._reference(
                ChatIntent(tool="open_result", reference_ordinal=1), request
            )
