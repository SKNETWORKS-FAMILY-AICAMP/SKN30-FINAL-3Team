"""F3 composition root: resolve persisted model routes into AI facade bindings."""

from __future__ import annotations

from brokerage_ai.core.errors import ProviderConfigurationError
from brokerage_ai.core.types import ModelRoute, ProviderKind
from brokerage_ai.f3 import (
    InputPrivacyMode,
    LlmBrokerageJudgmentGenerator,
    LlmPositionCardGenerator,
)
from brokerage_ai.providers.ports import LlmProvider
from brokerage_ai.runtime import AiRuntime
from pydantic import ValidationError
from sqlmodel import Session

from core.errors import ConfigurationError
from domain.agent_execution import pipeline, repository
from domain.agent_execution.anchor_card import GenerationBinding, GenerationBindingError
from domain.agent_execution.execution_policy import ExecutionStep, next_step
from domain.agent_execution.judgment import JudgmentBinding
from domain.agent_execution.model_timing import TimedProvider
from domain.agent_execution.models import (
    BROKERAGE_JUDGMENT_CAPABILITY,
    POSITION_CARD_CAPABILITY,
    AgentRun,
    AiModelConfig,
)


def _route(config: AiModelConfig) -> ModelRoute:
    """DB의 안전한 모델 설정을 Provider 중립 AI route로 옮긴다."""
    try:
        provider = ProviderKind(config.provider)
    except ValueError as error:
        raise ConfigurationError("the configured AI provider is not supported") from error
    if provider is ProviderKind.OPENAI and config.endpoint_alias is not None:
        raise ConfigurationError("the configured openai route cannot have an endpoint alias")
    if (
        provider
        in {
            ProviderKind.VLLM,
            ProviderKind.LLAMA_CPP,
            ProviderKind.BEDROCK,
        }
        and not (config.endpoint_alias or "").strip()
    ):
        raise ConfigurationError(
            f"the configured {provider.value} route requires an endpoint alias"
        )
    try:
        return ModelRoute(
            provider=provider,
            model=config.model_name,
            endpoint_alias=config.endpoint_alias,
        )
    except ValidationError as error:
        raise ConfigurationError("the configured AI model route is invalid") from error


def _generator_inputs(runtime: AiRuntime, config: AiModelConfig) -> tuple[LlmProvider, ModelRoute]:
    route = _route(config)
    try:
        provider = runtime.providers.get_llm(route.provider, route.endpoint_alias)
    except ProviderConfigurationError as error:
        raise ConfigurationError("the configured AI provider is not available") from error
    return provider, route


def _card_model_config(session: Session, run: AgentRun) -> AiModelConfig | None:
    if run.model_config_id is not None:
        return repository.find_position_card_model_config(
            session, run.brokerage_id, run.model_config_id
        )
    return repository.find_active_model_config(session, run.brokerage_id, POSITION_CARD_CAPABILITY)


def _judgment_model_config(session: Session, run: AgentRun) -> AiModelConfig | None:
    recorded = run.redacted_output_snapshot.get("judgment")
    recorded_id = recorded.get("model_config_id") if isinstance(recorded, dict) else None
    if isinstance(recorded_id, int):
        return repository.find_brokerage_judgment_model_config(
            session, run.brokerage_id, recorded_id
        )
    return repository.find_active_model_config(
        session, run.brokerage_id, BROKERAGE_JUDGMENT_CAPABILITY
    )


def _judgment_required(session: Session, run: AgentRun) -> bool:
    """후보 카드가 없으면 판정 설정과 Provider를 조회하지 않는다."""
    header = repository.find_match_evaluation_for_run(session, run.brokerage_id, run.id or 0)
    if header is None:
        return False
    entries = header.candidate_selection_snapshot.get("candidate_cards")
    return isinstance(entries, list) and bool(entries)


def build_bindings(
    session: Session,
    runtime: AiRuntime,
    run: AgentRun,
) -> pipeline.ExecutionBindings:
    """현재 저장 상태에서 실제로 필요한 capability만 조립한다."""
    step = next_step(run.status)
    privacy_mode = InputPrivacyMode.SYNTHETIC_PROTOTYPE
    card: GenerationBinding | None = None
    judgment: JudgmentBinding | None = None

    if step in {ExecutionStep.ANCHOR_CARD, ExecutionStep.CANDIDATE_CARDS}:
        card_config = _card_model_config(session, run)
        if card_config is None:
            raise GenerationBindingError("the position card model configuration is unavailable")
        try:
            card_provider, card_route = _generator_inputs(runtime, card_config)
        except ConfigurationError as error:
            raise GenerationBindingError("the position card provider is unavailable") from error
        card = GenerationBinding(
            generator=LlmPositionCardGenerator(
                provider=TimedProvider(
                    card_provider, run.id or 0, run.attempt_count, POSITION_CARD_CAPABILITY
                ),
                route=card_route,
                allow_synthetic_prototype=True,
            ),
            model_config_id=card_config.id or 0,
            input_privacy_mode=privacy_mode,
        )

    if step is ExecutionStep.JUDGMENT and _judgment_required(session, run):
        judgment_config = _judgment_model_config(session, run)
        if judgment_config is None:
            raise GenerationBindingError("the judgment model configuration is unavailable")
        try:
            judgment_provider, judgment_route = _generator_inputs(runtime, judgment_config)
        except ConfigurationError as error:
            raise GenerationBindingError("the judgment provider is unavailable") from error
        judgment = JudgmentBinding(
            generator=LlmBrokerageJudgmentGenerator(
                provider=TimedProvider(
                    judgment_provider, run.id or 0, run.attempt_count, BROKERAGE_JUDGMENT_CAPABILITY
                ),
                route=judgment_route,
                allow_synthetic_prototype=True,
            ),
            model_config_id=judgment_config.id or 0,
            input_privacy_mode=privacy_mode,
        )

    return pipeline.ExecutionBindings(card=card, judgment=judgment)
