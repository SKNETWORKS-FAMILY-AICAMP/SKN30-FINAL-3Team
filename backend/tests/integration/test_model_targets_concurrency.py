"""Non-cooperating writers cannot change the reviewed inputs inside batch apply."""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from queue import Queue

import pytest
import test_chatbot as fixtures
from brokerage_ai.core.model_catalog import GeneralModel, GeneralSelection
from brokerage_ai.core.types import ProviderKind
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel import Session

from model_selection import Capability, apply_selection, apply_targets, list_targets

chat_engine = fixtures.chat_engine
user = fixtures.user
pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DB_URL"), reason="isolated TEST_DB_URL required"
)


@pytest.fixture
def reviewed(chat_engine, user):
    # Use the same desired model in this module so previous successful tests never
    # leave unrelated incompatible targets. Each test creates its own brokerage.
    desired = GeneralSelection(provider=ProviderKind.VLLM, model=GeneralModel.QWEN_FP8)
    with Session(chat_engine) as session, session.begin():
        apply_selection(session, user.brokerage_id, Capability.CHATBOT, desired)
        snapshot = list_targets(session, desired)
    return desired, snapshot["snapshot"]


def test_all_input_tables_reject_concurrent_dml_until_commit(chat_engine, user, reviewed):
    desired, snapshot = reviewed

    def attempt_write(sql):
        with chat_engine.begin() as connection:
            connection.execute(text("SET LOCAL lock_timeout = '150ms'"))
            connection.execute(text(sql), {"b": user.brokerage_id})

    statements = [
        f"UPDATE {table} SET brokerage_id=brokerage_id WHERE brokerage_id=:b"
        for table in ("ai_model_config", "agent_run", "chat_request")
    ]
    statements.extend(
        [
            "INSERT INTO brokerage(name) VALUES ('synthetic concurrency test')",
            "INSERT INTO ai_model_config(brokerage_id,capability,config_key,config_version,"
            "provider,model_name,parameters,is_active) VALUES "
            "(:b,'CHATBOT','writer-review',1,'openai','synthetic-model','{}'::jsonb,FALSE)",
        ]
    )
    with Session(chat_engine) as session, session.begin():
        apply_targets(session, desired, [], snapshot)
        with ThreadPoolExecutor(max_workers=1) as pool:
            for statement in statements:
                with pytest.raises(DBAPIError) as error:
                    pool.submit(attempt_write, statement).result(timeout=3)
                assert getattr(error.value.orig, "sqlstate", None) == "55P03"
        # A normal operational read still works from another connection.
        with chat_engine.connect() as reader:
            assert reader.execute(text("SELECT count(*) FROM ai_model_config")).scalar_one() > 0
    # Committing batch apply releases the same lock; the other writer now succeeds.
    attempt_write(statements[0])


def test_writer_committed_while_waiting_invalidates_review(chat_engine, user, reviewed):
    desired, snapshot = reviewed
    pid_ready = Queue()

    def batch_apply():
        with Session(chat_engine) as session, session.begin():
            pid_ready.put(session.execute(text("SELECT pg_backend_pid()")).scalar_one())
            return apply_targets(session, desired, [], snapshot)

    with chat_engine.connect() as writer:
        transaction = writer.begin()
        writer.execute(
            text(
                "UPDATE ai_model_config SET config_version=config_version+1 WHERE brokerage_id=:b"
            ),
            {"b": user.brokerage_id},
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(batch_apply)
            pid = pid_ready.get(timeout=3)
            try:
                deadline = time.monotonic() + 3
                with chat_engine.connect() as observer:
                    while time.monotonic() < deadline:
                        waiting = observer.execute(
                            text(
                                "SELECT EXISTS(SELECT 1 FROM pg_locks "
                                "WHERE pid=:pid AND NOT granted)"
                            ),
                            {"pid": pid},
                        ).scalar_one()
                        if waiting:
                            break
                        time.sleep(0.01)
                    else:
                        pytest.fail("batch did not wait for concurrent writer")
                transaction.commit()
                with pytest.raises(ValueError, match="changed after review"):
                    future.result(timeout=3)
            finally:
                if transaction.is_active:
                    transaction.rollback()
    with Session(chat_engine) as session:
        assert (
            session.execute(
                text("SELECT count(*) FROM ai_model_config WHERE brokerage_id=:b"),
                {"b": user.brokerage_id},
            ).scalar_one()
            == 1
        )


def test_busy_writer_times_out_without_partial_model_versions(chat_engine, user, reviewed):
    desired, snapshot = reviewed
    with chat_engine.connect() as writer, writer.begin():
        writer.execute(
            text("UPDATE ai_model_config SET brokerage_id=brokerage_id WHERE brokerage_id=:b"),
            {"b": user.brokerage_id},
        )
        with pytest.raises(DBAPIError) as error, Session(chat_engine) as session, session.begin():
            apply_targets(session, desired, [], snapshot)
        assert getattr(error.value.orig, "sqlstate", None) == "55P03"
    with Session(chat_engine) as session:
        assert list_targets(session, desired)["snapshot"] == snapshot
