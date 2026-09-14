"""CHATBOT profile selection executes real SQL in the disposable chatbot test schema."""

from __future__ import annotations

import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
import test_chatbot as chatbot_fixtures
from pydantic import SecretStr
from sqlalchemy import text

import chatbot_model
from core.config import AppEnvironment
from domain.chatbot.repository import ChatStore

chat_engine = chatbot_fixtures.chat_engine
user = chatbot_fixtures.user
question = chatbot_fixtures.question

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DB_URL"), reason="isolated TEST_DB_URL required"
)


@pytest.fixture
def local_model_config(config, chat_engine, monkeypatch):
    config = config.model_copy(
        update={
            "app": config.app.model_copy(update={"environment": AppEnvironment.LOCAL}),
            "db": config.db.model_copy(update={"url": SecretStr(os.environ["TEST_DB_URL"])}),
        }
    )
    monkeypatch.setattr(chatbot_model, "create_database_engine", lambda _: chat_engine)
    # Provider presence is relevant; tests never perform inference or contact an endpoint.
    monkeypatch.setattr(
        chatbot_model,
        "load_ai_config",
        lambda _: SimpleNamespace(
            openai=object(), llm_endpoints=[SimpleNamespace(alias="general-dev-gpu")]
        ),
    )
    return config


def model_rows(engine, brokerage_id):
    with engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT id,capability,config_key,config_version,provider,model_name,model_version,"
                "endpoint_alias,parameters,is_active,created_at "
                "FROM ai_model_config WHERE brokerage_id=:b ORDER BY id"
            ),
            {"b": brokerage_id},
        ).all()


def insert_model(
    connection, brokerage_id, capability, key, *, model="preserved-model", active=True
):
    connection.execute(
        text(
            "INSERT INTO ai_model_config(brokerage_id,capability,config_key,config_version,"
            "provider,model_name,parameters,is_active) "
            "VALUES(:b,:c,:k,1,'openai',:m,'{}'::jsonb,:a)"
        ),
        {"b": brokerage_id, "c": capability, "k": key, "m": model, "a": active},
    )


def business_rows(engine, brokerage_id):
    # Compare actual stored values, not just counts that could conceal a delete-and-reinsert.
    result = {}
    with engine.connect() as connection:
        for table in (
            "property_complex",
            "property_unit",
            "property_listing",
            "party",
            "property_requirement",
            "calendar_event",
        ):
            result[table] = (
                connection.execute(
                    text(
                        f"SELECT row_to_json(t)::text FROM {table} t "
                        "WHERE brokerage_id=:b ORDER BY id"
                    ),
                    {"b": brokerage_id},
                )
                .scalars()
                .all()
            )
    return result


def test_activation_preserves_f3_and_business_rows_and_dry_run(
    chat_engine,
    user,
    local_model_config,
):
    with chat_engine.begin() as connection:
        for capability in ("POSITION_CARD", "BROKERAGE_JUDGMENT"):
            insert_model(connection, user.brokerage_id, capability, "existing-f3")
        insert_model(connection, user.brokerage_id, "CHATBOT", "previous-chatbot")
        complex_id = connection.execute(
            text(
                "INSERT INTO property_complex(brokerage_id,name,memo)"
                " VALUES(:b,'합성 단지','보존 검증') RETURNING id"
            ),
            {"b": user.brokerage_id},
        ).scalar_one()
        unit_id = connection.execute(
            text(
                "INSERT INTO property_unit(brokerage_id,complex_id,unit_number)"
                " VALUES(:b,:c,'101') RETURNING id"
            ),
            {"b": user.brokerage_id, "c": complex_id},
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO property_listing(brokerage_id,unit_id,is_sale_available,sale_price) "
                "VALUES(:b,:u,TRUE,500000000)"
            ),
            {"b": user.brokerage_id, "u": unit_id},
        )
        party_id = connection.execute(
            text(
                "INSERT INTO party(brokerage_id,party_type,name)"
                " VALUES(:b,'PERSON','합성 인물') RETURNING id"
            ),
            {"b": user.brokerage_id},
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO property_requirement(brokerage_id,party_id,"
                "demand_type,max_budget_amount) "
                "VALUES(:b,:p,'매수',500000000)"
            ),
            {"b": user.brokerage_id, "p": party_id},
        )
        connection.execute(
            text(
                "INSERT INTO calendar_event(brokerage_id,title,event_date)"
                " VALUES(:b,'합성 일정','2026-09-08')"
            ),
            {"b": user.brokerage_id},
        )
    before_models = model_rows(chat_engine, user.brokerage_id)
    before_business = business_rows(chat_engine, user.brokerage_id)

    chatbot_model.activate_chatbot(
        local_model_config, user.brokerage_id, "local-openai", apply=False
    )
    assert model_rows(chat_engine, user.brokerage_id) == before_models
    assert business_rows(chat_engine, user.brokerage_id) == before_business

    chatbot_model.activate_chatbot(
        local_model_config, user.brokerage_id, "local-openai", apply=True
    )
    after = model_rows(chat_engine, user.brokerage_id)
    assert [r for r in after if r.capability != "CHATBOT"] == [
        r for r in before_models if r.capability != "CHATBOT"
    ]
    active = [r for r in after if r.capability == "CHATBOT" and r.is_active]
    assert len(active) == 1
    assert (active[0].config_key, active[0].provider, active[0].model_name) == (
        "local-openai",
        "openai",
        "gpt-5.6-luna",
    )
    assert business_rows(chat_engine, user.brokerage_id) == before_business

    # Re-selecting the identical pinned profile preserves row identities and settings.
    chatbot_model.activate_chatbot(
        local_model_config, user.brokerage_id, "local-openai", apply=True
    )
    assert model_rows(chat_engine, user.brokerage_id) == after


@pytest.mark.parametrize("apply", [False, True])
def test_profile_pin_mismatch_is_rejected_without_mutation(
    chat_engine,
    user,
    local_model_config,
    apply,
):
    with chat_engine.begin() as connection:
        insert_model(connection, user.brokerage_id, "CHATBOT", "previous-profile")
        insert_model(
            connection,
            user.brokerage_id,
            "CHATBOT",
            "local-openai",
            model="different-pinned-model",
            active=False,
        )
    before = model_rows(chat_engine, user.brokerage_id)
    with pytest.raises(ValueError, match="pinned CHATBOT profile differs"):
        chatbot_model.activate_chatbot(
            local_model_config, user.brokerage_id, "local-openai", apply=apply
        )
    assert model_rows(chat_engine, user.brokerage_id) == before


@pytest.mark.parametrize("status", ["ACCEPTED", "RUNNING"])
@pytest.mark.parametrize("apply", [False, True])
def test_active_request_prevents_profile_selection(
    chat_engine,
    user,
    local_model_config,
    status,
    apply,
):
    with chat_engine.begin() as connection:
        insert_model(connection, user.brokerage_id, "CHATBOT", "previous-profile")
    store = ChatStore(chat_engine)
    conversation = store.create(user)
    accepted, _ = store.accept(user, conversation.id, question(), uuid4(), 60)
    if status == "RUNNING":
        assert store.transition(user, accepted.id, status="RUNNING")
    before = model_rows(chat_engine, user.brokerage_id)
    request_before = store.get_request(user, accepted.id)
    with pytest.raises(ValueError, match="settle active chatbot requests"):
        chatbot_model.activate_chatbot(
            local_model_config, user.brokerage_id, "local-openai", apply=apply
        )
    assert model_rows(chat_engine, user.brokerage_id) == before
    assert store.get_request(user, accepted.id) == request_before
