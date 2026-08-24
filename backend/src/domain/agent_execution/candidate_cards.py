"""후보 포지션 카드 확보 단계.

`CANDIDATES_READY` snapshot 의 상위 15건에 대해 **반대편** 측면의 포지션 카드를 확보하고
`CANDIDATE_CARDS_READY` 로 옮긴다.

카드 생성 자체는 `anchor_card` 의 공용 경로를 그대로 쓴다. 여기서 하는 일은 어느 대상의
카드를 몇 장 만들지 정하고, 전부 확보됐을 때만 상태를 옮기는 것뿐이다. snapshot 조립,
입력 개인정보 모드 검사, cache key와 저장 직전 재검증을 다시 구현하지 않는다.

## 후보 카드의 소유 실행

후보 카드는 **루트 실행에 직접 귀속한다.** child `AgentRun` 을 만들지 않는다.

- `negotiation_position_analysis.agent_run_id` 는 어느 실행이 이 카드를 만들었는지를 담는
  감사 값이고, 루트 실행 하나로 그 질문에 답할 수 있다.
- child run 을 만들면 lease 와 결과 소유권이 두 행으로 갈라져 저장 직전 fencing 이
  복잡해진다. 지금 얻는 것이 없다.
- 공개 실행 조회는 `parent_run_id IS NULL` 로 격리하므로 child run 을 만들어도 노출되지는
  않지만, 만들지 않으면 그 격리를 신경 쓸 일 자체가 없다.

## 병렬화

후보를 **순차로** 처리한다. SQLModel `Session` 은 여러 async task 가 공유할 수 없고, 카드
하나가 곧 transaction 하나라 세션을 나누면 커넥션 수와 fencing 이 함께 복잡해진다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from brokerage_ai.f3 import PositionCardGenerationResult
from sqlmodel import Session

from domain.agent_execution import repository
from domain.agent_execution.anchor_card import (
    CardTarget,
    GenerationBinding,
    prepare_generation,
    store_position_card,
)
from domain.agent_execution.candidates import (
    CANDIDATE_CARD_LIMIT,
    CANDIDATE_SELECTION_SCHEMA_VERSION,
    AnchorCardMissingError,
)
from domain.agent_execution.models import (
    CANDIDATE_CARDS_READY_STATUS,
    CANDIDATES_READY_STATUS,
    AgentRun,
    AnchorType,
    InputVersionChangedError,
    LeaseNotHeldError,
    anchor_of,
)
from domain.agent_execution.service import current_target_version


class CandidateSelectionMissingError(RuntimeError):
    """`CANDIDATES_READY` 인데 읽을 수 있는 후보 snapshot 이 없다.

    헤더가 사라졌거나 다른 schema 로 저장돼 있다. 이 상태로는 어떤 후보의 카드를 만들어야
    하는지 알 수 없으므로 진행하지 않는다.
    """


@dataclass(frozen=True)
class CandidateCardPlan:
    """이번 단계에서 카드를 확보할 대상. snapshot 이 정한 상위 15건이다."""

    candidate_side: AnchorType
    candidate_ids: tuple[int, ...]
    match_evaluation_id: int
    anchor_data_version: int


@dataclass(frozen=True)
class CandidateCard:
    """후보 1건의 확보 결과."""

    candidate_id: int
    position_analysis_id: int
    cache_hit: bool


@dataclass(frozen=True)
class CandidateCardsResult:
    """단계 결과. 카드가 몇 장 새로 생겼는지로 캐시 재사용률을 볼 수 있다 (F3-NF-03)."""

    run_id: int
    cards: tuple[CandidateCard, ...]

    @property
    def generated_count(self) -> int:
        return sum(1 for card in self.cards if not card.cache_hit)

    @property
    def cache_hit_count(self) -> int:
        return sum(1 for card in self.cards if card.cache_hit)


def _opposite(anchor_type: AnchorType) -> AnchorType:
    """앵커의 반대편. 매물 앵커는 구입장 후보를, 구입장 앵커는 매물 후보를 갖는다."""
    return AnchorType.REQUIREMENT if anchor_type is AnchorType.LISTING else AnchorType.LISTING


def _plan_from_snapshot(run: AgentRun, header: repository.MatchEvaluation) -> CandidateCardPlan:
    """snapshot 에서 카드화 대상만 뽑는다. 15건 이후는 이 단계가 건드리지 않는다."""
    snapshot = header.candidate_selection_snapshot
    if snapshot.get("schema") != CANDIDATE_SELECTION_SCHEMA_VERSION:
        raise CandidateSelectionMissingError("the candidate selection snapshot is unreadable")
    entries = snapshot.get("candidates")
    if not isinstance(entries, list):
        raise CandidateSelectionMissingError("the candidate selection snapshot has no candidates")

    anchor_type, _ = anchor_of(run)
    candidate_side = _opposite(anchor_type)
    criteria = snapshot.get("criteria")
    if not isinstance(criteria, dict) or criteria.get("candidate_side") != candidate_side.value:
        raise CandidateSelectionMissingError("the candidate selection side is inconsistent")

    selected: list[int] = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("selected_for_cards") is not True:
            continue
        candidate_id = entry.get("candidate_id")
        if not isinstance(candidate_id, int) or candidate_id < 1:
            raise CandidateSelectionMissingError("the candidate selection snapshot is malformed")
        selected.append(candidate_id)
    if len(selected) > CANDIDATE_CARD_LIMIT or len(selected) != len(set(selected)):
        raise CandidateSelectionMissingError("the selected candidate set is malformed")

    return CandidateCardPlan(
        candidate_side=candidate_side,
        # snapshot 순서가 곧 카드화 순서다. 여기서 다시 정렬하면 저장된 순위와 어긋난다.
        candidate_ids=tuple(selected),
        match_evaluation_id=header.id or 0,
        anchor_data_version=run.input_data_version,
    )


def plan_candidate_cards(
    session: Session, run_id: int, worker_id: str, attempt_count: int
) -> CandidateCardPlan:
    """어느 후보의 카드를 만들지 정한다. 아무것도 저장하지 않는다."""
    try:
        run = repository.find_leased_run(
            session, run_id, worker_id, attempt_count, status=CANDIDATES_READY_STATUS
        )
        if run is None:
            raise LeaseNotHeldError("the worker does not hold a valid lease on this run")

        anchor_type, anchor_id = anchor_of(run)
        if (
            current_target_version(session, run.brokerage_id, anchor_type, anchor_id)
            != run.input_data_version
        ):
            raise InputVersionChangedError("the anchor changed after the candidates were selected")

        header = repository.find_match_evaluation_for_run(session, run.brokerage_id, run_id)
        if header is None:
            raise CandidateSelectionMissingError("the run has no candidate selection")
        plan = _plan_from_snapshot(run, header)
    except BaseException:
        session.rollback()
        raise
    else:
        session.rollback()
    return plan


def _record_cards(
    session: Session,
    run_id: int,
    worker_id: str,
    attempt_count: int,
    plan: CandidateCardPlan,
    cards: tuple[CandidateCard, ...],
    *,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int,
) -> None:
    """확보한 카드 ID 를 snapshot 에 붙이고 `CANDIDATE_CARDS_READY` 로 옮긴다.

    카드 ID 는 중개 판정 단계가 어떤 카드를 모델에 넣었는지 확정하는 값이다. 판정 시점에
    cache key 를 다시 계산해 되찾는 방식은 비싸고, 그 사이 캐시가 바뀌면 다른 카드를 가리킨다.
    """
    try:
        run = repository.find_leased_run(
            session, run_id, worker_id, attempt_count, status=CANDIDATES_READY_STATUS
        )
        if run is None:
            raise LeaseNotHeldError("the worker does not hold a valid lease on this run")

        header = repository.find_match_evaluation_for_run(session, run.brokerage_id, run_id)
        if header is None or header.id != plan.match_evaluation_id:
            raise CandidateSelectionMissingError("the candidate selection changed during carding")

        anchor_type, anchor_id = anchor_of(run)
        if (
            current_target_version(session, run.brokerage_id, anchor_type, anchor_id)
            != plan.anchor_data_version
        ):
            raise InputVersionChangedError("the anchor changed while candidate cards were made")

        # 후보 집합이 그대로인지 다시 본다. 도중에 다시 뽑혔으면 이 카드들은 그 집합의
        # 카드가 아니다.
        current = _plan_from_snapshot(run, header)
        if current.candidate_ids != plan.candidate_ids:
            raise CandidateSelectionMissingError("the candidate set changed while cards were made")
        if tuple(card.candidate_id for card in cards) != plan.candidate_ids:
            raise CandidateSelectionMissingError("the candidate card set is incomplete")

        # 저장 직전에 카드가 아직 그 대상의 활성 카드인지 확인한다.
        listing_side = plan.candidate_side is AnchorType.LISTING
        for card in cards:
            found = repository.find_position_card_for_target(
                session,
                run.brokerage_id,
                position_analysis_id=card.position_analysis_id,
                negotiation_side=plan.candidate_side.value,
                listing_id=card.candidate_id if listing_side else None,
                requirement_id=None if listing_side else card.candidate_id,
            )
            if found is None:
                raise AnchorCardMissingError("a candidate position card is no longer usable")

        snapshot = dict(header.candidate_selection_snapshot)
        snapshot["candidate_cards"] = [
            {
                "candidate_id": card.candidate_id,
                "position_analysis_id": card.position_analysis_id,
                "cache_hit": card.cache_hit,
            }
            for card in cards
        ]
        changed = repository.update_match_evaluation_snapshot(
            session, run.brokerage_id, header.id or 0, candidate_selection_snapshot=snapshot
        )
        if changed != 1:
            raise CandidateSelectionMissingError("the candidate selection could not be updated")

        advanced = repository.advance_run_status(
            session,
            run_id,
            run.brokerage_id,
            worker_id,
            attempt_count,
            expected_status=CANDIDATES_READY_STATUS,
            next_status=CANDIDATE_CARDS_READY_STATUS,
            add_input_tokens=input_tokens,
            add_output_tokens=output_tokens,
            add_latency_ms=latency_ms,
        )
        if advanced != 1:
            raise LeaseNotHeldError("the lease was lost before the run could advance")
        session.commit()
    except BaseException:
        session.rollback()
        raise


async def generate_and_store_candidate_cards(
    session: Session,
    *,
    run_id: int,
    worker_id: str,
    attempt_count: int,
    binding: GenerationBinding,
    as_of: datetime | None = None,
) -> CandidateCardsResult:
    """상위 후보의 반대편 포지션 카드를 확보하고 `CANDIDATE_CARDS_READY` 로 옮긴다.

    **모든** 카드를 확보한 뒤에만 상태를 옮긴다. 후보 하나가 실패하면 예외가 그대로 올라가고
    실행은 `CANDIDATES_READY` 에 남는다. 일부만 성공한 상태를 완료로 만들면 중개 판정이
    반쪽짜리 후보 집합으로 돌아간다.

    후보가 0건이면 모델을 한 번도 부르지 않고 곧장 다음 단계로 넘어간다 (F3-CR-11).
    """
    moment = as_of or datetime.now(UTC)
    plan = plan_candidate_cards(session, run_id, worker_id, attempt_count)

    cards: list[CandidateCard] = []
    input_tokens = output_tokens = latency_ms = 0
    for candidate_id in plan.candidate_ids:
        prepared = prepare_generation(
            session,
            run_id,
            worker_id,
            attempt_count,
            binding,
            target=CardTarget(anchor_type=plan.candidate_side, anchor_id=candidate_id),
            expected_status=CANDIDATES_READY_STATUS,
            as_of=moment,
        )
        result: PositionCardGenerationResult | None = None
        if prepared.request is not None:
            # cache miss 일 때만 모델을 부른다. transaction 은 이미 닫혀 있다.
            result = await binding.generator.generate_position_card(prepared.request)
            diagnostics = result.diagnostics
            usage = diagnostics.usage if diagnostics else None
            if usage is not None:
                input_tokens += usage.input_tokens
                # total 만 오는 Provider 가 있어 output 을 total 로 덮지 않는다.
                output_tokens += usage.output_tokens or 0
            if diagnostics is not None:
                latency_ms += int(diagnostics.latency_ms)

        analysis_id = store_position_card(
            session,
            run_id,
            worker_id,
            attempt_count,
            binding,
            prepared,
            result,
            expected_status=CANDIDATES_READY_STATUS,
        )
        cards.append(
            CandidateCard(
                candidate_id=candidate_id,
                position_analysis_id=analysis_id,
                cache_hit=result is None,
            )
        )

    stored = tuple(cards)
    _record_cards(
        session,
        run_id,
        worker_id,
        attempt_count,
        plan,
        stored,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
    )
    return CandidateCardsResult(run_id=run_id, cards=stored)
