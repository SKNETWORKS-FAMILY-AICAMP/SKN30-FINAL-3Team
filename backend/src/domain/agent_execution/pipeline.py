"""선점한 실행 하나를 저장된 상태에서 한 단계 진행시킨다.

Worker 는 어떤 단계를 부를지 정하지 않는다. **DB 에 저장된 상태가 정본**이고 이 모듈이 그
상태에 맞는 유스케이스를 고른다. 프로세스가 죽어도 진행이 남는 이유가 이것이다.

| 저장된 상태 | 하는 일 | 다음 상태 |
|---|---|---|
| `RUNNING` | 앵커 포지션 카드 확보 | `ANCHOR_READY` |
| `ANCHOR_READY` | 결정적 SQL 후보 추출 | `CANDIDATES_READY` |
| `CANDIDATES_READY` | 후보 포지션 카드 확보 | `CANDIDATE_CARDS_READY` |
| `CANDIDATE_CARDS_READY` | 중개 판정 1회와 결과 저장 | `COMPLETED` |
| `JUDGING` | 결과가 없으면 되돌려 다시 판정 | `CANDIDATE_CARDS_READY` |

`COMPLETED` 와 종료 상태는 다시 처리하지 않는다.

## 오류 분류

Provider·모델과 프롬프트는 AI 가 소유하지만 **무엇이 재시도 가능한가**는 실행을 소유한
Backend 가 정한다.

| 원인 | 처리 |
|---|---|
| 입력 장부·상담 로그가 실행 중 바뀜 | `SUPERSEDED` |
| 계약 위반, 잘못된 입력, PII 검증 실패, 바인딩 오류 | `FAILED_TERMINAL` |
| 일시적인 Provider 오류와 그 밖의 예외 | 재시도 |
| lease 상실 | 아무것도 쓰지 않고 이 실행을 놓는다 |

`SUPERSEDED` 는 이 실행의 결과가 더 이상 현재 데이터를 대리하지 않는다는 뜻이다.
`FAILED_TERMINAL` 은 같은 입력으로 다시 해도 같은 결과라는 뜻이다. 재시도는 lease 를 놓아
다음 선점이 이어받게 하고, lease 상실은 다른 Worker 가 이미 가져갔다는 뜻이다.

재시도에는 새 scheduler 나 heartbeat 를 만들지 않는다. 기존 5분 lease 와 3회 상한을 그대로
쓴다. 재시도 가능한 실패에서는 lease 만료 시각을 지금으로 당겨 다음 선점이 5분을 기다리지
않게 하고, **상태는 그대로 둔다.** 저장된 단계가 정본이므로 다음 Worker 가 그 단계부터
이어서 처리한다. 3회를 넘기면 기존 `claim_next_run` 정리가 `FAILED_TERMINAL` 로 끝낸다.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

import structlog
from brokerage_ai.core.errors import ProviderError
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
    judge_and_store,
)
from domain.agent_execution.models import (
    ANCHOR_READY_STATUS,
    CANDIDATE_CARDS_READY_STATUS,
    CANDIDATES_READY_STATUS,
    FAILED_TERMINAL_STATUS,
    JUDGING_STATUS,
    RUNNING_STATUS,
    SUPERSEDED_STATUS,
    AgentRun,
    AgentRunAnchorError,
    InputVersionChangedError,
    LeaseNotHeldError,
)
from domain.agent_execution.pii_guard import ModelOutputPrivacyError

logger = structlog.get_logger()

# 공개 응답에 실릴 수 있는 고정 실패 어휘. 개인정보와 내부 예외 문구는 여기에 없다.
SUPERSEDED_FAILURE_CODE = "INPUT_SUPERSEDED"
SUPERSEDED_FAILURE_MESSAGE = "실행 중 입력 데이터가 변경되어 결과를 반영하지 않았습니다"
TERMINAL_FAILURE_CODE = "EXECUTION_FAILED"
TERMINAL_FAILURE_MESSAGE = "실행에 실패했습니다. 잠시 후 다시 시도해 주세요"

# 입력이 바뀐 것으로 판정하는 예외. 재시도해도 이전 입력으로는 되돌아가지 않는다.
_SUPERSEDING_ERRORS = (InputVersionChangedError, SourceChangedError)

# 같은 입력으로 다시 해도 같은 결과인 예외.
_TERMINAL_ERRORS = (
    PositionCardContractError,
    BrokerageJudgmentContractError,
    ModelOutputPrivacyError,
    GenerationBindingError,
    JudgmentEvidenceError,
    JudgmentAlreadyStoredError,
    AgentRunAnchorError,
    CandidateSelectionMissingError,
    NotFoundError,
)

# 다시 준비하면 풀릴 수 있는 예외. 카드가 무효화됐거나 잠시 사라진 경우다.
_RETRYABLE_ERRORS = (CachedCardUnavailableError, AnchorCardMissingError)


class StepOutcome(StrEnum):
    """한 단계 처리의 결과. Worker 가 로그와 다음 동작을 정하는 데 쓴다."""

    ADVANCED = "ADVANCED"
    COMPLETED = "COMPLETED"
    SUPERSEDED = "SUPERSEDED"
    FAILED_TERMINAL = "FAILED_TERMINAL"
    RETRY = "RETRY"
    LEASE_LOST = "LEASE_LOST"
    SKIPPED = "SKIPPED"


@dataclass(frozen=True)
class ExecutionBindings:
    """이 실행에 쓸 두 생성 구성. 대리와 판정은 서로 다른 모델일 수 있다 (F3-NF-10)."""

    card: GenerationBinding
    judgment: JudgmentBinding


def classify(error: BaseException) -> StepOutcome:
    """예외를 실행 상태로 옮긴다. 여기 한 곳에만 분류를 둔다."""
    if isinstance(error, LeaseNotHeldError):
        return StepOutcome.LEASE_LOST
    if isinstance(error, _SUPERSEDING_ERRORS):
        return StepOutcome.SUPERSEDED
    if isinstance(error, _RETRYABLE_ERRORS):
        return StepOutcome.RETRY
    if isinstance(error, ProviderError):
        # AI 가 재시도 가능 여부를 함께 준다. 그 판단을 여기서 뒤집지 않는다.
        return StepOutcome.RETRY if error.retryable else StepOutcome.FAILED_TERMINAL
    if isinstance(error, _TERMINAL_ERRORS):
        return StepOutcome.FAILED_TERMINAL
    # 분류하지 못한 예외는 재시도로 둔다. 3회 상한이 무한 반복을 막는다.
    return StepOutcome.RETRY


async def _advance(
    session: Session,
    run: AgentRun,
    worker_id: str,
    bindings: ExecutionBindings,
) -> StepOutcome:
    """저장된 상태에 맞는 단계 하나를 실행한다."""
    run_id = run.id or 0
    attempt = run.attempt_count

    if run.status == RUNNING_STATUS:
        await generate_and_store_anchor_position_card(
            session,
            run_id=run_id,
            worker_id=worker_id,
            attempt_count=attempt,
            binding=bindings.card,
        )
        return StepOutcome.ADVANCED

    if run.status == ANCHOR_READY_STATUS:
        store_candidate_selection(session, run_id, worker_id, attempt)
        return StepOutcome.ADVANCED

    if run.status == CANDIDATES_READY_STATUS:
        await generate_and_store_candidate_cards(
            session,
            run_id=run_id,
            worker_id=worker_id,
            attempt_count=attempt,
            binding=bindings.card,
        )
        return StepOutcome.ADVANCED

    if run.status == CANDIDATE_CARDS_READY_STATUS:
        await judge_and_store(
            session,
            run_id=run_id,
            worker_id=worker_id,
            attempt_count=attempt,
            binding=bindings.judgment,
        )
        return StepOutcome.COMPLETED

    if run.status == JUDGING_STATUS:
        return _resume_judging(session, run, worker_id)

    # 종료 상태와 알 수 없는 상태는 건드리지 않는다.
    return StepOutcome.SKIPPED


def _resume_judging(session: Session, run: AgentRun, worker_id: str) -> StepOutcome:
    """판정 호출 도중 끊긴 실행을 되돌린다.

    저장된 후보 판정이 하나도 없으면 되돌려 다시 판정한다. 하나라도 있으면 저장과
    `COMPLETED` 전이가 원자인 계약이 깨진 상태이므로 덮어쓰지 않고 종료 처리한다.
    """
    run_id = run.id or 0
    header = repository.find_match_evaluation_for_run(session, run.brokerage_id, run_id)
    if header is None:
        raise CandidateSelectionMissingError("the judging run has no candidate selection")
    rewound = repository.rewind_judging_run(
        session, run_id, run.brokerage_id, worker_id, run.attempt_count, header.id or 0
    )
    if rewound != 1:
        session.rollback()
        raise JudgmentAlreadyStoredError("the judging run cannot be safely resumed")
    session.commit()
    return StepOutcome.ADVANCED


def record_failure(session: Session, run: AgentRun, worker_id: str, outcome: StepOutcome) -> None:
    """공개 가능한 고정 문구만 저장한다. raw exception 은 여기까지 오지 않는다."""
    status, code, message = (
        (SUPERSEDED_STATUS, SUPERSEDED_FAILURE_CODE, SUPERSEDED_FAILURE_MESSAGE)
        if outcome is StepOutcome.SUPERSEDED
        else (FAILED_TERMINAL_STATUS, TERMINAL_FAILURE_CODE, TERMINAL_FAILURE_MESSAGE)
    )
    try:
        repository.fail_run(
            session,
            run.id or 0,
            run.brokerage_id,
            worker_id,
            run.attempt_count,
            status=status,
            failure_code=code,
            failure_message=message,
        )
        session.commit()
    except BaseException:
        session.rollback()
        raise


def _release(session: Session, run: AgentRun, worker_id: str) -> None:
    """재시도 가능한 실패에서 lease 를 즉시 놓는다. 상태는 그대로 둔다."""
    try:
        repository.release_lease(
            session, run.id or 0, run.brokerage_id, worker_id, run.attempt_count
        )
        session.commit()
    except BaseException:
        session.rollback()
        raise


def drive_run(
    session: Session,
    run: AgentRun,
    worker_id: str,
    bindings: ExecutionBindings,
    loop: asyncio.AbstractEventLoop,
    should_stop: Callable[[], bool] | None = None,
) -> StepOutcome:
    """선점한 실행 하나를 더 나아갈 수 없을 때까지 진행시킨다.

    한 번 claim 한 실행은 **같은 lease 아래에서** 끝까지 간다. 단계마다 다시 선점하려 하면
    lease 가 아직 유효해 아무도 집지 못하고 실행이 5분 동안 멈춘다. `attempt_count` 도 이
    방식에서 "이 실행을 몇 번 시도했는가"라는 원래 의미를 유지한다.

    정지 신호가 오면 **지금 단계를 마친 뒤** 멈춘다. 단계 하나가 곧 transaction 하나라
    저장된 상태가 정본으로 남고 다음 Worker 가 이어서 처리한다.
    """
    outcome = StepOutcome.SKIPPED
    while True:
        outcome = advance_run(session, run, worker_id, bindings, loop)
        if outcome is not StepOutcome.ADVANCED:
            return outcome
        if should_stop is not None and should_stop():
            return outcome
        current = repository.find_root_cross_judgment_run(session, run.brokerage_id, run.id or 0)
        if current is None:  # pragma: no cover - 방어
            return outcome
        run = current


def advance_run(
    session: Session,
    run: AgentRun,
    worker_id: str,
    bindings: ExecutionBindings,
    loop: asyncio.AbstractEventLoop,
) -> StepOutcome:
    """실행 하나를 한 단계 진행시키고 실패를 상태로 옮긴다.

    예외를 밖으로 던지지 않는다. Worker loop 는 실행 하나가 실패해도 계속 돌아야 한다.
    """
    try:
        return loop.run_until_complete(_advance(session, run, worker_id, bindings))
    except BaseException as error:  # noqa: BLE001 - 분류해서 상태로 옮기는 것이 이 함수의 일이다
        outcome = classify(error)
        # 구조화 운영 로그에만 원인을 남긴다. 전체 Provider 응답과 개인정보는 남기지 않는다.
        logger.warning(
            "f3_step_failed",
            run_id=run.id,
            status=run.status,
            attempt=run.attempt_count,
            outcome=outcome.value,
            error_type=type(error).__name__,
        )
        if outcome is StepOutcome.LEASE_LOST:
            # 다른 Worker 가 가져갔다. 이 Worker 는 아무것도 쓰지 않는다.
            session.rollback()
            return outcome
        if outcome is StepOutcome.RETRY:
            _release(session, run, worker_id)
            return outcome
        record_failure(session, run, worker_id, outcome)
        return outcome
