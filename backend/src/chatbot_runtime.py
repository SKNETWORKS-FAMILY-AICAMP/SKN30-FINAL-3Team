"""Application composition for F4. No prompts or tenant identifiers enter AI."""

from __future__ import annotations

from collections.abc import Callable

from brokerage_ai import AiRuntime, ModelRoute, ProviderKind
from brokerage_ai.chatbot import ChatbotWorkflow
from sqlalchemy import Engine
from sqlmodel import Session

from core.config import Config
from core.errors import ConfigurationError
from domain.agent_execution.repository import find_active_model_config

CHATBOT_CAPABILITY = "CHATBOT"


def workflow_factory(
    engine: Engine, runtime: AiRuntime, config: Config
) -> Callable[[int], ChatbotWorkflow]:
    """Resolve a dedicated capability in a short transaction before model execution."""

    def resolve(brokerage_id: int) -> ChatbotWorkflow:
        with Session(engine) as session:
            model = find_active_model_config(session, brokerage_id, CHATBOT_CAPABILITY)
            if model is None:
                raise ConfigurationError("CHATBOT model configuration is unavailable")
            route = ModelRoute(
                provider=ProviderKind(model.provider),
                model=model.model_name,
                endpoint_alias=model.endpoint_alias,
            )
        provider = runtime.providers.get_llm(route.provider, route.endpoint_alias)
        return ChatbotWorkflow(
            provider=provider,
            route=route,
            timeout_seconds=config.chatbot.request_timeout_seconds,
        )

    return resolve
