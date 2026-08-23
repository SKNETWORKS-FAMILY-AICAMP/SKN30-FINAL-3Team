"""중개 판정 실행과 저장의 application 유스케이스.

포지션 카드와 같은 세 단계 구조를 쓴다.

1. 준비 transaction — lease·앵커 버전 확인, 판정 바인딩 확정·기록, 카드 조립,
   `JUDGING` 전이. 끝나면 transaction 을 닫는다.
2. transaction 밖 — AI 판정 **1회** 호출. 모델을 기다리는 동안 DB 잠금을 쥐지 않는다.
3. 저장 transaction — 재검증 후 판정·후보·근거를 원자 저장하며 `COMPLETED` 로 옮긴다.

후보가 0건이면 모델을 부르지 않고 빈 최종 결과를 원자 저장한 뒤 바로 `COMPLETED` 로 간다.

## 판정 모델 바인딩

대리와 판정은 다른 모델을 쓸 수 있어야 한다 (F3-NF-10). 그래서 포지션 카드용
`POSITION_CARD` 설정을 억지로 재사용하지 않고 `BROKERAGE_JUDGMENT` capability 설정을
따로 요구한다.

`agent_run` 에는 모델 바인딩 컬럼이 한 벌뿐이고 그 자리는 이미 포지션 카드 바인딩이
차지하고 있다. 판정 바인딩은 새 컬럼을 만들지 않고 `redacted_output_snapshot["judgment"]`
에 **allowlist 필드만** 기록한다. API key, token, endpoint URL 은 들어가지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass

from brokerage_ai.f3 import (
    BrokerageJudgmentGenerator,
    BrokerageJudgmentRequest,
    BrokerageJudgmentResult,
    CandidateJudgment,
    EvidenceKind,
    JudgmentCard,
    MatchGrade,
    NegotiationSide,
    PositionCardGenerationResult,
    validate_judgment_result,
)
from sqlmodel import Session

from domain.agent_execution import repository
from domain.agent_execution.anchor_card import GenerationBindingError
from domain.agent_execution.candidate_cards import CandidateSelectionMissingError
from domain.agent_execution.candidates import (
    CANDIDATE_SELECTION_SCHEMA_VERSION,
    AnchorCardMissingError,
)
from domain.agent_execution.models import (
    CANDIDATE_CARDS_READY_STATUS,
    COMPLETED_STATUS,
    JUDGING_STATUS,
    AgentRun,
    AnchorType,
    InputVersionChangedError,
    LeaseNotHeldError,
    MatchCandidateEvaluation,
    MatchCandidateEvidence,
    NegotiationPositionAnalysis,
    anchor_of,
)
from domain.agent_execution.pii_guard import assert_no_personal_data_in_judgment
from domain.agent_execution.service import current_target_version


class JudgmentAlreadyStoredError(RuntimeError):
    """이 실행의 판정 결과가 이미 저장돼 있다.

    저장과 `COMPLETED` 전이는 한 transaction 이라 정상 경로에서는 생기지 않는다. 생겼다면
    수동 개입이나 손상된 상태이므로 덮어쓰지 않고 멈춘다.
    """


class JudgmentEvidenceError(RuntimeError):
    """판정 근거가 카드 근거와 맞지 않는다.

    인용이 그 카드에 실제로 없거나 offset 을 대조할 수 없다. 이 결과는 저장하지 않는다.
    """


@dataclass(frozen=True)
class JudgmentBinding:
    """이 실행의 중개 판정에 쓸 생성 구성.

    Backend 는 Provider 나 모델을 고르지 않는다. 무엇을 쓸지는 호출 조립 지점이 정해서
    여기에 주입하고, Backend 는 그 설정이 이 사무소의 **중개 판정용** 활성 설정인지 확인한 뒤
    allowlist 필드만 snapshot 으로 기록한다.
    """

    generator: BrokerageJudgmentGenerator
    model_config_id: int

    @property
    def prompt_version(self) -> str:
        return self.generator.versions.prompt_version

    @property
    def workflow_version(self) -> str:
        return self.generator.versions.workflow_version


@dataclass(frozen=True)
class PreparedJudgment:
    """준비 단계 결과. ORM 행도 열린 transaction 도 들고 있지 않다."""

    brokerage_id: int
    match_evaluation_id: int
    anchor_card_id: int
    anchor_type: AnchorType
    anchor_id: int
    anchor_data_version: int
    candidate_card_ids: tuple[int, ...]
    model_snapshot: dict[str, object]
    request: BrokerageJudgmentRequest | None


@dataclass(frozen=True)
class BrokerageJudgmentStored:
    """유스케이스 결과."""

    run_id: int
    match_evaluation_id: int
    candidate_count: int


def _judgment_snapshot(binding: JudgmentBinding, model_snapshot: dict[str, object]) -> dict:
    """실행에 남길 판정 바인딩. allowlist 필드와 버전만 담는다."""
    return {
        "model_config_id": binding.model_config_id,
        "model_snapshot": model_snapshot,
        "prompt_version": binding.prompt_version,
        "workflow_version": binding.workflow_version,
    }


def _expected_model_snapshot(
    session: Session, brokerage_id: int, binding: JudgmentBinding
) -> dict[str, object]:
    """지금 이 실행에 기대되는 안전한 판정 model snapshot.

    다른 사무소의 설정과 존재하지 않는 설정을 **같은 오류**로 거절한다. 구분해서 알리면
    남의 설정 존재 여부가 새어 나간다.
    """
    config = repository.find_brokerage_judgment_model_config(
        session, brokerage_id, binding.model_config_id
    )
    if config is None:
        raise GenerationBindingError("the judgment model configuration is not usable for this run")
    return repository.safe_model_snapshot(config)


def _card_ids_from_snapshot(snapshot: dict) -> tuple[int, ...]:
    """후보 카드 단계가 붙여 둔 카드 ID. 여기서 다시 cache key 를 계산하지 않는다."""
    if snapshot.get("schema") != CANDIDATE_SELECTION_SCHEMA_VERSION:
        raise CandidateSelectionMissingError("the candidate selection snapshot is unreadable")
    entries = snapshot.get("candidate_cards")
    if not isinstance(entries, list):
        raise CandidateSelectionMissingError("the run has no candidate cards")

    identifiers: list[int] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise CandidateSelectionMissingError("the candidate card list is malformed")
        card_id = entry.get("position_analysis_id")
        if not isinstance(card_id, int):
            raise CandidateSelectionMissingError("the candidate card list is malformed")
        identifiers.append(card_id)
    return tuple(identifiers)


def _judgment_card(card: NegotiationPositionAnalysis) -> JudgmentCard:
    """저장된 카드를 판정 입력으로 되돌린다.

    `analysis_snapshot` 은 검증을 통과한 공개 계약 결과 전체다. 컬럼들을 다시 조립하지 않고
    그 snapshot 을 그대로 되살려야 저장 당시의 카드와 정확히 같은 것이 판정에 들어간다.
    """
    stored = PositionCardGenerationResult.model_validate(card.analysis_snapshot)
    return JudgmentCard(
        card_id=card.id or 0,
        negotiation_side=NegotiationSide(card.negotiation_side),
        target_label=card.target_label or stored.target.target_label,
        analysis=stored.analysis,
    )


def _load_cards(
    session: Session, brokerage_id: int, anchor_card_id: int, candidate_card_ids: tuple[int, ...]
) -> tuple[JudgmentCard, tuple[JudgmentCard, ...]]:
    """앵커와 후보 카드를 활성 상태로 읽는다. 하나라도 없으면 판정하지 않는다."""
    wanted = (anchor_card_id, *candidate_card_ids)
    found = {
        card.id: card for card in repository.list_position_cards(session, brokerage_id, wanted)
    }
    if set(found) != set(wanted):
        raise AnchorCardMissingError("a position card required for the judgment is unavailable")
    return (
        _judgment_card(found[anchor_card_id]),
        tuple(_judgment_card(found[card_id]) for card_id in candidate_card_ids),
    )


def prepare_judgment(
    session: Session,
    run_id: int,
    worker_id: str,
    attempt_count: int,
    binding: JudgmentBinding,
) -> PreparedJudgment:
    """1단계. 바인딩을 기록하고 카드를 조립한 뒤 `JUDGING` 으로 옮기고 transaction 을 닫는다.

    후보가 0건이면 요청을 만들지 않고 `request` 를 `None` 으로 둔다. 그래도 `JUDGING` 을
    거치지 않고 저장 단계가 곧장 빈 결과를 확정한다.
    """
    try:
        run = repository.find_leased_run(
            session, run_id, worker_id, attempt_count, status=CANDIDATE_CARDS_READY_STATUS
        )
        if run is None:
            raise LeaseNotHeldError("the worker does not hold a valid lease on this run")

        anchor_type, anchor_id = anchor_of(run)
        if (
            current_target_version(session, run.brokerage_id, anchor_type, anchor_id)
            != run.input_data_version
        ):
            raise InputVersionChangedError("the anchor changed after the cards were made")

        header = repository.find_match_evaluation_for_run(session, run.brokerage_id, run_id)
        if header is None:
            raise CandidateSelectionMissingError("the run has no candidate selection")
        if repository.count_match_candidate_evaluations(session, run.brokerage_id, header.id or 0):
            raise JudgmentAlreadyStoredError("this run already carries a stored judgment")

        model_snapshot = _expected_model_snapshot(session, run.brokerage_id, binding)
        candidate_card_ids = _card_ids_from_snapshot(header.candidate_selection_snapshot)

        request: BrokerageJudgmentRequest | None = None
        if candidate_card_ids:
            anchor_card, candidate_cards = _load_cards(
                session, run.brokerage_id, header.anchor_position_analysis_id, candidate_card_ids
            )
            request = BrokerageJudgmentRequest(anchor=anchor_card, candidates=candidate_cards)

            # 후보가 있을 때만 JUDGING 을 거친다. 판정할 것이 없으면 "판정 중"이 거짓이다.
            snapshot = dict(run.redacted_output_snapshot)
            snapshot["judgment"] = _judgment_snapshot(binding, model_snapshot)
            changed = repository.advance_run_status(
                session,
                run_id,
                run.brokerage_id,
                worker_id,
                attempt_count,
                expected_status=CANDIDATE_CARDS_READY_STATUS,
                next_status=JUDGING_STATUS,
                output_snapshot=snapshot,
            )
            if changed != 1:
                raise LeaseNotHeldError("the lease was lost before the run could advance")

        prepared = PreparedJudgment(
            brokerage_id=run.brokerage_id,
            match_evaluation_id=header.id or 0,
            anchor_card_id=header.anchor_position_analysis_id,
            anchor_type=anchor_type,
            anchor_id=anchor_id,
            anchor_data_version=run.input_data_version,
            candidate_card_ids=candidate_card_ids,
            model_snapshot=model_snapshot,
            request=request,
        )
        session.commit()
    except BaseException:
        # 도메인 오류에서도 열린 transaction 을 남기지 않는다. 남기면 AI 를 기다리는 동안
        # 이 커넥션이 idle in transaction 으로 잠긴다.
        session.rollback()
        raise
    return prepared


def _evidence_rows(
    brokerage_id: int,
    candidate_evaluation_id: int,
    candidate: CandidateJudgment,
    offsets: dict[tuple[NegotiationSide, int, str], tuple[int | None, int | None]],
) -> list[MatchCandidateEvidence]:
    """판정 근거를 저장 행으로 펼친다.

    인용 offset 은 새로 계산하지 않고 **그 카드가 이미 저장해 둔 값**을 그대로 옮긴다.
    판정 단계에는 상담 원문이 없으므로 여기서 offset 을 만들면 근거 없는 위치가 생긴다.
    """
    rows: list[MatchCandidateEvidence] = []
    for item in candidate.evidence:
        start = end = None
        if item.source.kind is EvidenceKind.QUOTE:
            key = (
                item.evidence_side,
                item.source.interaction_id or 0,
                item.source.quote_text or "",
            )
            if key not in offsets:
                raise JudgmentEvidenceError(
                    "the judgment quote is not present in the position card"
                )
            start, end = offsets[key]
        rows.append(
            MatchCandidateEvidence(
                brokerage_id=brokerage_id,
                match_candidate_evaluation_id=candidate_evaluation_id,
                evidence_side=item.evidence_side.value,
                field_name=item.field_name,
                evidence_type=item.source.kind.value,
                interaction_id=item.source.interaction_id,
                quote_text=item.source.quote_text,
                quote_start_offset=start,
                quote_end_offset=end,
                note=item.source.note,
            )
        )
    return rows


def _quote_offsets(
    session: Session,
    brokerage_id: int,
    anchor: tuple[NegotiationSide, int],
    candidates: dict[int, NegotiationSide],
) -> dict[tuple[NegotiationSide, int, str], tuple[int | None, int | None]]:
    """카드가 저장해 둔 인용과 그 offset 을 `(측면, interaction_id, 인용문)` 으로 색인한다."""
    offsets: dict[tuple[NegotiationSide, int, str], tuple[int | None, int | None]] = {}
    anchor_side, anchor_card_id = anchor
    for card_id, side in ((anchor_card_id, anchor_side), *candidates.items()):
        for row in repository.list_card_quote_evidence(session, brokerage_id, card_id):
            offsets[(side, row.interaction_id, row.quote_text)] = (
                row.quote_start_offset,
                row.quote_end_offset,
            )
    return offsets


def _completion_snapshot(
    run: AgentRun,
    prepared: PreparedJudgment,
    result: BrokerageJudgmentResult | None,
    candidate_count: int,
) -> dict[str, object]:
    """실행에 남길 비식별 요약. 판정 본문과 근거는 여기에 중복 저장하지 않는다.

    본문은 `match_candidate_evaluation` 과 `match_candidate_evidence` 가 소유한다. 전체
    프롬프트와 전체 모델 응답은 어디에도 남기지 않는다.
    """
    snapshot = dict(run.redacted_output_snapshot)
    diagnostics = result.diagnostics if result else None
    snapshot["judgment_result"] = {
        "match_evaluation_id": prepared.match_evaluation_id,
        "anchor_position_analysis_id": prepared.anchor_card_id,
        "candidate_count": candidate_count,
        "contract_version": result.contract_version if result else None,
        "prompt_version": result.prompt_version if result else None,
        "workflow_version": result.workflow_version if result else None,
        "provider": diagnostics.provider.value if diagnostics else None,
        "model": diagnostics.model if diagnostics else None,
        "grades": sorted({candidate.grade.value for candidate in result.candidates})
        if result
        else [],
    }
    return snapshot


def store_judgment(
    session: Session,
    run_id: int,
    worker_id: str,
    attempt_count: int,
    binding: JudgmentBinding,
    prepared: PreparedJudgment,
    result: BrokerageJudgmentResult | None,
) -> BrokerageJudgmentStored:
    """3단계. 재검증하고 판정·후보·근거를 한 transaction 에 저장하며 `COMPLETED` 로 옮긴다.

    일부 후보만 저장된 채 `COMPLETED` 가 되는 상태는 생기지 않는다. 저장과 상태 전이가 같은
    transaction 안에 있고, 하나라도 어긋나면 전체를 rollback 한다.
    """
    empty = prepared.request is None
    expected_status = CANDIDATE_CARDS_READY_STATUS if empty else JUDGING_STATUS
    try:
        run = repository.find_leased_run(
            session, run_id, worker_id, attempt_count, status=expected_status
        )
        if run is None:
            raise LeaseNotHeldError("the worker does not hold a valid lease on this run")
        if run.brokerage_id != prepared.brokerage_id:
            raise LeaseNotHeldError("the run belongs to a different brokerage")

        if _expected_model_snapshot(session, run.brokerage_id, binding) != prepared.model_snapshot:
            raise GenerationBindingError("the judgment binding changed while the model ran")

        if (
            current_target_version(
                session, run.brokerage_id, prepared.anchor_type, prepared.anchor_id
            )
            != prepared.anchor_data_version
        ):
            raise InputVersionChangedError("the anchor changed while the judgment ran")

        header = repository.find_match_evaluation_for_run(session, run.brokerage_id, run_id)
        if header is None or header.id != prepared.match_evaluation_id:
            raise CandidateSelectionMissingError("the candidate selection changed during judging")
        if repository.count_match_candidate_evaluations(session, run.brokerage_id, header.id or 0):
            raise JudgmentAlreadyStoredError("this run already carries a stored judgment")
        if _card_ids_from_snapshot(header.candidate_selection_snapshot) != (
            prepared.candidate_card_ids
        ):
            raise CandidateSelectionMissingError("the candidate card set changed during judging")

        stored_count = 0
        if not empty and result is not None and prepared.request is not None:
            request = prepared.request
            if (
                result.prompt_version != binding.prompt_version
                or result.workflow_version != binding.workflow_version
            ):
                raise GenerationBindingError(
                    "the result was produced by a different prompt or workflow version"
                )
            # 카드가 저장 직전에도 전부 활성인지 다시 본다.
            _load_cards(
                session,
                run.brokerage_id,
                prepared.anchor_card_id,
                prepared.candidate_card_ids,
            )
            validate_judgment_result(request, result)
            assert_no_personal_data_in_judgment(result.candidates)

            offsets = _quote_offsets(
                session,
                run.brokerage_id,
                (request.anchor.negotiation_side, request.anchor.card_id),
                {card.card_id: card.negotiation_side for card in request.candidates},
            )
            for candidate in result.candidates:
                stored = repository.insert_match_candidate_evaluation(
                    session,
                    MatchCandidateEvaluation(
                        brokerage_id=run.brokerage_id,
                        match_evaluation_id=header.id or 0,
                        candidate_position_analysis_id=candidate.card_id,
                        match_grade=candidate.grade.value,
                        match_rank=candidate.rank,
                        evaluation_basis=candidate.comparison_basis,
                        primary_obstacle=candidate.primary_obstacle,
                        possible_concession=candidate.possible_concession,
                        recommended_action=(
                            candidate.recommended_action.model_dump(mode="json")
                            if candidate.recommended_action
                            else {}
                        ),
                        # 기각 사유는 지우지 않는다. 무엇을 왜 걸렀는지 남아야 한다.
                        exclusion_reason=(
                            candidate.rejection_reason
                            if candidate.grade is MatchGrade.REJECTED
                            else None
                        ),
                    ),
                )
                repository.insert_match_candidate_evidence(
                    session,
                    _evidence_rows(run.brokerage_id, stored.id or 0, candidate, offsets),
                )
            stored_count = len(result.candidates)

        if (
            repository.finalize_match_evaluation(
                session, run.brokerage_id, header.id or 0, candidate_count=stored_count
            )
            != 1
        ):
            raise CandidateSelectionMissingError("the judgment header could not be finalized")

        changed = repository.advance_run_status(
            session,
            run_id,
            run.brokerage_id,
            worker_id,
            attempt_count,
            expected_status=expected_status,
            next_status=COMPLETED_STATUS,
            output_snapshot=_completion_snapshot(run, prepared, result, stored_count),
            completed=True,
            add_input_tokens=_usage(result, "input"),
            add_output_tokens=_usage(result, "output"),
            add_latency_ms=_latency(result),
        )
        if changed != 1:
            raise LeaseNotHeldError("the lease was lost before the run could complete")
        session.commit()
    except BaseException:
        session.rollback()
        raise

    return BrokerageJudgmentStored(
        run_id=run_id,
        match_evaluation_id=prepared.match_evaluation_id,
        candidate_count=stored_count,
    )


def _usage(result: BrokerageJudgmentResult | None, kind: str) -> int:
    usage = result.diagnostics.usage if result and result.diagnostics else None
    if usage is None:
        return 0
    # total 만 오는 Provider 가 있어 output 을 total 로 덮지 않는다.
    return usage.input_tokens if kind == "input" else (usage.output_tokens or 0)


def _latency(result: BrokerageJudgmentResult | None) -> int:
    diagnostics = result.diagnostics if result else None
    return int(diagnostics.latency_ms) if diagnostics else 0


async def judge_and_store(
    session: Session,
    *,
    run_id: int,
    worker_id: str,
    attempt_count: int,
    binding: JudgmentBinding,
) -> BrokerageJudgmentStored:
    """중개 판정을 **1회** 실행하고 결과를 저장한 뒤 `COMPLETED` 로 옮긴다 (F3-NF-04).

    후보가 0건이면 모델을 부르지 않고 빈 최종 결과를 원자 저장한다. AI 호출은 두 transaction
    사이에서 일어나며 그 동안 이 세션은 열린 transaction 을 갖지 않는다.
    """
    prepared = prepare_judgment(session, run_id, worker_id, attempt_count, binding)

    result: BrokerageJudgmentResult | None = None
    if prepared.request is not None:
        result = await binding.generator.judge_candidates(prepared.request)

    return store_judgment(session, run_id, worker_id, attempt_count, binding, prepared, result)
