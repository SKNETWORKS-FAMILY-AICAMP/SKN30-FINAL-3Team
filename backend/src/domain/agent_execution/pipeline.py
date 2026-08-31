"""선점한 F3 실행을 저장된 상태에서 다음 단계로 진행시킨다.

DB 상태가 재개 지점의 정본이다. 한 번 선점한 실행은 같은 lease 아래에서 가능한 단계까지
진행하고, 프로세스가 중단되면 다음 Worker가 저장된 상태부터 이어받는다. 별도 scheduler,
heartbeat 또는 메모리 checkpoint를 만들지 않는다.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

import structlog
from brokerage_ai.core.errors import (
    ProviderConfigurationError,
    ProviderError,
    ProviderOutputInvalidError,
    ProviderRateLimitError,
    ProviderRefusalError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from brokerage_ai.f3 import BrokerageJudgmentContractError, PositionCardContractError
from sqlmodel import Session

from core.errors import NotFoundError
from domain.agent_execution import repository
from domain.agent_execution.anchor_card import (
    CachedCardUnavailableError,
    GenerationBinding,
    GenerationBindingError,
    SourceChangedError,
    generate_and_store_anchor_position_card,
)
from domain.agent_execution.candidate_cards import (
    CandidateSelectionMissingError,
    generate_and_store_candidate_cards,
)
from domain.agent_execution.candidates import AnchorCardMissingError, store_candidate_selection
from domain.agent_execution.judgment import (
    JudgmentAlreadyStoredError,
    JudgmentBinding,
    JudgmentEvidenceError,
    JudgmentResultMismatchError,
    judge_and_store,
)
from domain.agent_execution.models import (
    ANCHOR_READY_STATUS,
    CANDIDATE_CARDS_READY_STATUS,
    CANDIDATES_READY_STATUS,
    FAILED_TERMINAL_STATUS,
    JUDGING_STATUS,
    LEDGER_SAVE_TRIGGER_TYPE,
    RUNNING_STATUS,
    SUPERSEDED_FAILURE_CODE,
    SUPERSEDED_FAILURE_MESSAGE,
    SUPERSEDED_STATUS,
    AgentRun,
    AgentRunAnchorError,
    InputVersionChangedError,
    LeaseNotHeldError,
)

logger = structlog.get_logger()

# 공개 응답에 실어도 되는 고정 실패 어휘. raw 예외와 Provider 응답은 저장하지 않는다.
TERMINAL_FAILURE_CODE = "EXECUTION_FAILED"
TERMINAL_FAILURE_MESSAGE = "실행에 실패했습니다. 잠시 후 다시 시도해 주세요"

_SUPERSEDING_ERRORS = (InputVersionChangedError, SourceChangedError)
_RETRYABLE_ERRORS = (CachedCardUnavailableError, AnchorCardMissingError)
_TERMINAL_ERRORS = (
    PositionCardContractError,
    BrokerageJudgmentContractError,
    GenerationBindingError,
    JudgmentEvidenceError,
    JudgmentAlreadyStoredError,
    JudgmentResultMismatchError,
    AgentRunAnchorError,
    CandidateSelectionMissingError,
    NotFoundError,
)


class StepOutcome(StrEnum):
    """단계 처리 결과. Worker 로그와 다음 polling 동작에만 사용한다."""

    ADVANCED = "ADVANCED"
    COMPLETED = "COMPLETED"
    SUPERSEDED = "SUPERSEDED"
    FAILED_TERMINAL = "FAILED_TERMINAL"
    RETRY = "RETRY"
    LEASE_LOST = "LEASE_LOST"
    SKIPPED = "SKIPPED"


class FailureStage(StrEnum):
    """상담 본문 없이 실패 지점을 집계하는 안전한 단계 어휘."""

    ANCHOR_CARD = "ANCHOR_CARD"
    CANDIDATE_SELECTION = "CANDIDATE_SELECTION"
    CANDIDATE_CARDS = "CANDIDATE_CARDS"
    JUDGMENT = "JUDGMENT"
    EXECUTION = "EXECUTION"


class FailureCategory(StrEnum):
    """Provider 원문·모델 출력을 남기지 않는 고정 실패 분류."""

    LEASE = "LEASE"
    INPUT_CHANGED = "INPUT_CHANGED"
    CACHE_INVALIDATED = "CACHE_INVALIDATED"
    OUTPUT_CONTRACT = "OUTPUT_CONTRACT"
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    PROVIDER_RATE_LIMIT = "PROVIDER_RATE_LIMIT"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    PROVIDER_REFUSAL = "PROVIDER_REFUSAL"
    PROVIDER_RESPONSE = "PROVIDER_RESPONSE"
    CONFIGURATION = "CONFIGURATION"
    DATA_INTEGRITY = "DATA_INTEGRITY"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ExecutionBindings:
    """현재 단계에 필요한 생성 구성. 사용하지 않는 capability는 조회하지 않는다."""

    card: GenerationBinding | None = None
    judgment: JudgmentBinding | None = None


BindingResolver = Callable[[AgentRun], ExecutionBindings]


def _card_binding(bindings: ExecutionBindings) -> GenerationBinding:
    if bindings.card is None:
        raise GenerationBindingError("the position card binding is unavailable")
    return bindings.card


def _judgment_binding(bindings: ExecutionBindings) -> JudgmentBinding | None:
    # 후보 0건이면 06번 유스케이스가 binding 없이 AI 호출을 생략한다.
    return bindings.judgment


def failure_stage(status: str) -> FailureStage:
    """DB 상태를 사용자 데이터가 없는 집계 단계로 바꿔 돌려준다."""
    if status == RUNNING_STATUS:
        return FailureStage.ANCHOR_CARD
    if status == ANCHOR_READY_STATUS:
        return FailureStage.CANDIDATE_SELECTION
    if status == CANDIDATES_READY_STATUS:
        return FailureStage.CANDIDATE_CARDS
    if status in {CANDIDATE_CARDS_READY_STATUS, JUDGING_STATUS}:
        return FailureStage.JUDGMENT
    return FailureStage.EXECUTION


def failure_category(error: BaseException) -> FailureCategory:
    """예외 본문을 로그하지 않고 안정적인 소수 어휘로만 분류한다."""
    if isinstance(error, LeaseNotHeldError):
        return FailureCategory.LEASE
    if isinstance(error, _SUPERSEDING_ERRORS):
        return FailureCategory.INPUT_CHANGED
    if isinstance(error, _RETRYABLE_ERRORS):
        return FailureCategory.CACHE_INVALIDATED
    if isinstance(error, ProviderOutputInvalidError):
        return FailureCategory.OUTPUT_CONTRACT
    if isinstance(error, ProviderTimeoutError):
        return FailureCategory.PROVIDER_TIMEOUT
    if isinstance(error, ProviderRateLimitError):
        return FailureCategory.PROVIDER_RATE_LIMIT
    if isinstance(error, ProviderUnavailableError):
        return FailureCategory.PROVIDER_UNAVAILABLE
    if isinstance(error, ProviderRefusalError):
        return FailureCategory.PROVIDER_REFUSAL
    if isinstance(error, ProviderResponseError):
        return FailureCategory.PROVIDER_RESPONSE
    if isinstance(error, ProviderConfigurationError | GenerationBindingError):
        return FailureCategory.CONFIGURATION
    if isinstance(
        error,
        PositionCardContractError
        | BrokerageJudgmentContractError
        | JudgmentEvidenceError
        | JudgmentResultMismatchError,
    ):
        return FailureCategory.OUTPUT_CONTRACT
    if isinstance(
        error,
        JudgmentAlreadyStoredError
        | AgentRunAnchorError
        | CandidateSelectionMissingError
        | NotFoundError,
    ):
        return FailureCategory.DATA_INTEGRITY
    return FailureCategory.UNKNOWN


def classify(error: BaseException) -> StepOutcome:
    """예외를 실행 수명주기 결과로 변환한다."""
    if isinstance(error, LeaseNotHeldError):
        return StepOutcome.LEASE_LOST
    if isinstance(error, _SUPERSEDING_ERRORS):
        return StepOutcome.SUPERSEDED
    if isinstance(error, _RETRYABLE_ERRORS):
        return StepOutcome.RETRY
    if isinstance(error, ProviderError):
        return StepOutcome.RETRY if error.retryable else StepOutcome.FAILED_TERMINAL
    if isinstance(error, _TERMINAL_ERRORS):
        return StepOutcome.FAILED_TERMINAL
    # DB의 3회 lease 상한이 무한 반복을 막는다. 알 수 없는 오류 원문은 저장하지 않는다.
    return StepOutcome.RETRY


async def _advance(
    session: Session,
    run: AgentRun,
    worker_id: str,
    bindings: ExecutionBindings,
) -> StepOutcome:
    """저장된 상태에 대응하는 application 유스케이스 하나를 실행한다."""
    run_id = run.id or 0
    attempt_count = run.attempt_count

    if run.status == RUNNING_STATUS:
        await generate_and_store_anchor_position_card(
            session,
            run_id=run_id,
            worker_id=worker_id,
            attempt_count=attempt_count,
            binding=_card_binding(bindings),
        )
        return StepOutcome.ADVANCED

    if run.status == ANCHOR_READY_STATUS:
        # 저장이 만든 실행은 여기까지다. 앵커 포지션 카드만 만들어 두고 후보 조회와 판정은
        # 사용자가 상세에서 요청할 때 돈다(F3-CR-01~04). 그 요청이 오면 `service` 가
        # trigger_type 을 옮기고 lease 를 만료시켜 이 실행이 그대로 이어서 진행한다.
        if run.trigger_type == LEDGER_SAVE_TRIGGER_TYPE:
            logger.info("f3_run_parked_after_anchor_card", run_id=run_id)
            return StepOutcome.SKIPPED
        store_candidate_selection(session, run_id, worker_id, attempt_count)
        return StepOutcome.ADVANCED

    if run.status == CANDIDATES_READY_STATUS:
        await generate_and_store_candidate_cards(
            session,
            run_id=run_id,
            worker_id=worker_id,
            attempt_count=attempt_count,
            binding=_card_binding(bindings),
        )
        return StepOutcome.ADVANCED

    if run.status in {CANDIDATE_CARDS_READY_STATUS, JUDGING_STATUS}:
        # JUDGING 재선점은 06번 유스케이스가 최초 바인딩과 후보 집합을 다시 검증한다.
        await judge_and_store(
            session,
            run_id=run_id,
            worker_id=worker_id,
            attempt_count=attempt_count,
            binding=_judgment_binding(bindings),
        )
        return StepOutcome.COMPLETED

    return StepOutcome.SKIPPED


def record_failure(
    session: Session,
    run: AgentRun,
    worker_id: str,
    outcome: StepOutcome,
) -> bool:
    """종료 상태와 공개 가능한 고정 실패 정보만 원자적으로 기록한다."""
    status, code, message = (
        (SUPERSEDED_STATUS, SUPERSEDED_FAILURE_CODE, SUPERSEDED_FAILURE_MESSAGE)
        if outcome is StepOutcome.SUPERSEDED
        else (FAILED_TERMINAL_STATUS, TERMINAL_FAILURE_CODE, TERMINAL_FAILURE_MESSAGE)
    )
    try:
        changed = repository.fail_run(
            session,
            run.id or 0,
            run.brokerage_id,
            worker_id,
            run.attempt_count,
            status=status,
            failure_code=code,
            failure_message=message,
        )
        if changed != 1:
            session.rollback()
            return False
        session.commit()
    except BaseException:
        session.rollback()
        raise
    return True


def _release(session: Session, run: AgentRun, worker_id: str) -> bool:
    """재시도 가능한 실패에서 상태를 보존한 채 lease 만 즉시 만료시킨다."""
    try:
        changed = repository.release_lease(
            session,
            run.id or 0,
            run.brokerage_id,
            worker_id,
            run.attempt_count,
        )
        if changed != 1:
            session.rollback()
            return False
        session.commit()
    except BaseException:
        session.rollback()
        raise
    return True


def advance_run(
    session: Session,
    run: AgentRun,
    worker_id: str,
    bindings: ExecutionBindings | BindingResolver,
    loop: asyncio.AbstractEventLoop,
) -> StepOutcome:
    """한 단계를 진행하고 예외를 저장 가능한 실행 결과로 수렴시킨다."""
    try:
        resolved = bindings(run) if callable(bindings) else bindings
        return loop.run_until_complete(_advance(session, run, worker_id, resolved))
    except BaseException as error:  # noqa: BLE001 - 실행 하나의 실패를 격리하는 경계다.
        outcome = classify(error)
        logger.warning(
            "f3_step_failed",
            run_id=run.id,
            status=run.status,
            failure_stage=failure_stage(run.status).value,
            attempt=run.attempt_count,
            outcome=outcome.value,
            failure_category=failure_category(error).value,
            error_type=type(error).__name__,
        )
        if outcome is StepOutcome.LEASE_LOST:
            session.rollback()
            return outcome
        if outcome is StepOutcome.RETRY:
            return outcome if _release(session, run, worker_id) else StepOutcome.LEASE_LOST
        return (
            outcome if record_failure(session, run, worker_id, outcome) else StepOutcome.LEASE_LOST
        )


def drive_run(
    session: Session,
    run: AgentRun,
    worker_id: str,
    bindings: ExecutionBindings | BindingResolver,
    loop: asyncio.AbstractEventLoop,
    should_stop: Callable[[], bool] | None = None,
) -> StepOutcome:
    """같은 lease 아래에서 완료·실패·중단 지점까지 실행을 진행한다."""
    while True:
        outcome = advance_run(session, run, worker_id, bindings, loop)
        if outcome is not StepOutcome.ADVANCED:
            return outcome
        if should_stop is not None and should_stop():
            return outcome
        current = repository.find_root_cross_judgment_run(session, run.brokerage_id, run.id or 0)
        if current is None:  # pragma: no cover - FK와 claim 조건을 통과한 행의 방어 경계
            return outcome
        run = current
