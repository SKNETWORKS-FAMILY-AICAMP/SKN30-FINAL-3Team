"""Review/apply against real PostgreSQL; schema and rows are disposable test data."""

from __future__ import annotations

import os

import pytest
import test_chatbot as fixtures
from brokerage_ai.core.model_catalog import GeneralModel, GeneralSelection
from brokerage_ai.core.types import ProviderKind
from sqlalchemy import text
from sqlmodel import Session

import model_selection as model_cli
from model_selection import Capability, apply_selection, apply_targets, list_targets

chat_engine = fixtures.chat_engine
user = fixtures.user
pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DB_URL"), reason="isolated TEST_DB_URL required"
)


def test_target_review_is_atomic_scoped_versioned_and_rejects_drift(chat_engine, user, monkeypatch):
    desired = GeneralSelection(provider=ProviderKind.VLLM, model=GeneralModel.QWEN_FP8)
    with Session(chat_engine) as session, session.begin():
        for capability in (Capability.CHATBOT, Capability.POSITION_CARD):
            apply_selection(session, user.brokerage_id, capability, GeneralSelection())
        before = list_targets(session, desired)
    target = (user.brokerage_id, Capability.CHATBOT)
    with (
        pytest.raises(ValueError, match="outside selected"),
        Session(chat_engine) as session,
        session.begin(),
    ):
        apply_targets(session, desired, [target], before["snapshot"])
    with Session(chat_engine) as session:
        assert list_targets(session, desired) == before
    # A concurrent config version changes the review hash even with the same route.
    with chat_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE ai_model_config SET config_version=config_version+1 WHERE brokerage_id=:b"
            ),
            {"b": user.brokerage_id},
        )
    with (
        pytest.raises(ValueError, match="changed after review"),
        Session(chat_engine) as session,
        session.begin(),
    ):
        apply_targets(session, desired, [target], before["snapshot"])
    with Session(chat_engine) as session:
        reviewed = list_targets(session, desired)
    real_apply = model_cli.apply_selection

    def fail_second(session, brokerage_id, capability, selection):
        if capability is Capability.POSITION_CARD:
            raise ValueError("simulated second target failure")
        real_apply(session, brokerage_id, capability, selection)

    with monkeypatch.context() as patch:
        patch.setattr(model_cli, "apply_selection", fail_second)
        with (
            pytest.raises(ValueError, match="second target failure"),
            Session(chat_engine) as session,
            session.begin(),
        ):
            apply_targets(
                session,
                desired,
                [target, (user.brokerage_id, Capability.POSITION_CARD)],
                reviewed["snapshot"],
            )
    with Session(chat_engine) as session:
        assert list_targets(session, desired) == reviewed
    with Session(chat_engine) as session, session.begin():
        review = list_targets(session, desired)
        explicit = [target, (user.brokerage_id, Capability.POSITION_CARD)]
        result = apply_targets(session, desired, explicit, review["snapshot"])
        assert len(result["applied"]) == 2
    with Session(chat_engine) as session, session.begin():
        after = list_targets(session, desired)
        assert all(row["compatible"] for row in after["targets"])
        assert apply_targets(session, desired, explicit, after["snapshot"])["applied"] == []
        rows = session.execute(
            text(
                "SELECT capability,config_version,provider,is_active FROM ai_model_config "
                "WHERE brokerage_id=:b ORDER BY capability,config_version"
            ),
            {"b": user.brokerage_id},
        ).all()
        assert len(rows) == 4
        assert [(row.config_version, row.provider, row.is_active) for row in rows] == [
            (2, "openai", False),
            (3, "vllm", True),
            (2, "openai", False),
            (3, "vllm", True),
        ]
        assert not any(row.capability == "BROKERAGE_JUDGMENT" for row in rows)

    store = fixtures.ChatStore(chat_engine)
    conversation = store.create(user)
    store.accept(user, conversation.id, fixtures.question(), fixtures.uuid4(), 60)
    with Session(chat_engine) as session:
        pending = list_targets(session, desired)
        assert all(row["pending_work"] == 1 for row in pending["targets"])
    with (
        pytest.raises(ValueError, match="queued/in-progress"),
        Session(chat_engine) as session,
        session.begin(),
    ):
        apply_targets(session, desired, [], pending["snapshot"])
