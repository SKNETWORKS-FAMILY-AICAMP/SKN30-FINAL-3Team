"""F3 두 트리거의 흐름 제어.

    [저장]  자기 쪽 대리 1회 → 포지션 카드 1장                          LLM 1회
    [찾기]  ① 후보 추출      앵커 카드의 추정값 기준                    LLM 0회
            ② 후보 카드 확보  캐시 미스분만                             LLM 0~N회
            ③ 중개 판정      앵커1 + 후보N 일괄 1회                     LLM 1회
            ④ 등급 산출      게이트 + 5축 점수                          LLM 0회

등급은 ③이 아니라 ④가 정한다. 중개 판정은 걸림돌·양보·행동만 서술한다.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import uuid4

from brokerage_ai.f3 import PROMPT_VERSION
from brokerage_ai.f3.contracts import (
    AgentCallTrace,
    CandidateCardInput,
    PositionCard,
    PositionCardInput,
)
from brokerage_ai.f3.workflow import build_position_card, judge_matches
from brokerage_ai.providers.registry import ProviderRegistry
from sqlmodel import Session

from core.errors import NotFoundError, ValidationError
from domain.negotiation import ledger_view, repository
from domain.negotiation.candidates import (
    CandidateSelection,
    anchor_cap,
    select_candidates,
)
from domain.negotiation.grading import (
    AnchorFacts,
    CandidateFacts,
    GradeResult,
    grade,
)
from domain.negotiation.models import (
    AgentRun,
    MatchCandidateEvaluation,
    MatchEvaluation,
    NegotiationPositionAnalysis,
    NegotiationPositionEvidence,
)
from domain.property_ledger.models import ClientInteraction

WORKFLOW_VERSION = "f3-slice-1"

INTENT_CODE = {"있음": "PRESENT", "없음": "ABSENT", "불명": "UNKNOWN", "철회": "WITHDRAWN"}
URGENCY_CODE = {"급함": "URGENT", "보통": "NORMAL", "여유": "RELAXED", "불명": "UNKNOWN"}
CONTACT_CODE = {"양호": "GOOD", "주의": "CAUTION", "불가": "BLOCKED"}


@dataclass(frozen=True)
class CardOutcome:
    """카드 1장과 그것이 어디서 왔는지."""

    analysis_id: int
    card: PositionCard
    label: str
    cache_hit: bool


@dataclass(frozen=True)
class CandidateOutcome:
    unit_id: int
    label: str
    result: GradeResult
    blocker: str | None
    concession: str | None
    action: str | None


@dataclass(frozen=True)
class MatchOutcome:
    evaluation_id: int
    anchor_label: str
    selection: CandidateSelection
    candidates: tuple[CandidateOutcome, ...]
    llm_calls: int
    cache_hits: int


def _run_async[T](coroutine: asyncio.Future[T] | object) -> T:
    """sync 엔드포인트(워커 스레드)에서 async AI 호출을 돌린다.

    이 스레드에는 실행 중인 이벤트 루프가 없으므로 `asyncio.run` 이 안전하다. 전면 async
    전환은 이 슬라이스 범위 밖이다.
    """
    return asyncio.run(coroutine)  # pyright: ignore[reportArgumentType, reportReturnType]


def cache_key(kind: str, target_id: int, count: int, latest: datetime | None) -> str:
    """로그가 바뀌면 값이 바뀐다 — 그게 무효화 규칙의 전부다."""
    raw = f"{kind}:{target_id}:{PROMPT_VERSION}:{count}:{latest.isoformat() if latest else '-'}"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"{kind}:{target_id}:{digest}"


def _to_won(amount: float | None) -> int | None:
    if amount is None:
        return None
    return int(round(amount * ledger_view.WON_PER_EOK))


def _record_run(
    session: Session,
    *,
    brokerage_id: int,
    user_id: int,
    run_group_id: object,
    run_type: str,
    agent_type: str,
    trigger_type: str,
    trace: AgentCallTrace,
    unit_id: int | None = None,
    requirement_id: int | None = None,
    case_key: str | None = None,
) -> AgentRun:
    """추적 사슬의 시작점. 프롬프트 원문과 로그 본문은 남기지 않는다."""
    now = datetime.now(UTC)
    run = AgentRun(
        brokerage_id=brokerage_id,
        run_group_id=run_group_id,  # pyright: ignore[reportArgumentType]
        run_type=run_type,
        agent_type=agent_type,
        status="SUCCEEDED",
        trigger_type=trigger_type,
        model_snapshot={"provider": trace.provider, "model": trace.model},
        prompt_version=trace.prompt_version,
        workflow_version=WORKFLOW_VERSION,
        case_key=case_key,
        requested_by=user_id,
        target_unit_id=unit_id,
        target_requirement_id=requirement_id,
        input_tokens=trace.input_tokens or 0,
        output_tokens=trace.output_tokens or 0,
        latency_ms=int(trace.latency_ms),
        started_at=now,
        completed_at=now,
    )
    return repository.add_agent_run(session, run)


def _evidence_note(quote: str | None, *, traced: bool) -> str | None:
    if traced:
        return None
    return "근거 원문 없음 — 추정" if quote is None else "인용을 상담 로그에서 찾지 못함"


def _persist_card(
    session: Session,
    *,
    brokerage_id: int,
    agent_run_id: int,
    side: str,
    card: PositionCard,
    label: str,
    key: str,
    interaction_count: int,
    latest_interaction: datetime | None,
    unit_id: int | None,
    listing_id: int | None,
    requirement_id: int | None,
    interactions: list[ClientInteraction],
) -> NegotiationPositionAnalysis:
    analysis = NegotiationPositionAnalysis(
        brokerage_id=brokerage_id,
        agent_run_id=agent_run_id,
        negotiation_side="LISTING" if side == "매물" else "DEMAND",
        unit_id=unit_id,
        listing_id=listing_id,
        requirement_id=requirement_id,
        target_label=label,
        cache_key=key,
        source_interaction_count=interaction_count,
        last_interaction_at=latest_interaction,
        data_version=1,
        negotiation_intent=INTENT_CODE.get(card.intent.value, "UNKNOWN"),
        estimated_price_amount=_to_won(card.price.estimated),
        price_estimation_basis=card.price.basis,
        urgency=URGENCY_CODE.get(card.urgency.value, "UNKNOWN"),
        flexible_conditions=list(card.flexible),
        inflexible_conditions=list(card.inflexible),
        contactability_status=CONTACT_CODE.get(card.contactability.status, "CAUTION"),
        contactability_note=card.contactability.note,
        analysis_snapshot=card.model_dump(mode="json"),
    )
    evidence: list[NegotiationPositionEvidence] = []
    for order, (field_name, quote) in enumerate(
        (
            ("intent", card.intent.evidence),
            ("price", card.price.basis),
            ("urgency", card.urgency.evidence),
            ("deal_type_now", card.deal_type_now.ref),
        ),
        start=1,
    ):
        # QUOTE 근거는 원본 로그 행을 가리켜야 한다 (ck_position_evidence_source).
        # 되짚지 못한 인용은 추적 불가로 낮춰 기록한다 — 조용히 버리지 않는다.
        source = ledger_view.match_interaction(quote, interactions)
        traced = quote is not None and source is not None
        evidence.append(
            NegotiationPositionEvidence(
                brokerage_id=brokerage_id,
                position_analysis_id=0,
                field_name=field_name,
                evidence_type="QUOTE" if traced else "INFERENCE",
                interaction_id=source.id if source else None,
                quote_text=quote,
                note=_evidence_note(quote, traced=traced),
                display_order=order,
            )
        )
    return repository.add_position_analysis(session, analysis, evidence)


def ensure_unit_card(
    session: Session,
    registry: ProviderRegistry,
    *,
    brokerage_id: int,
    user_id: int,
    unit_id: int,
    run_group_id: object,
    trigger_type: str,
) -> CardOutcome:
    """세대 카드 1장을 확보한다. 캐시가 살아 있으면 LLM 을 타지 않는다."""
    unit = repository.find_unit(session, brokerage_id, unit_id)
    if unit is None:
        raise NotFoundError("property unit is not found")

    count, latest = repository.interaction_fingerprint(session, brokerage_id, unit_id=unit_id)
    key = cache_key("unit", unit_id, count, latest)
    cached = repository.find_valid_position_analysis(session, brokerage_id, key)
    if cached is not None:
        return CardOutcome(
            analysis_id=cached.id or 0,
            card=PositionCard.model_validate(cached.analysis_snapshot),
            label=cached.target_label or ledger_view.unit_label(unit),
            cache_hit=True,
        )

    listing = repository.latest_listing_for_unit(session, brokerage_id, unit_id)
    interactions = repository.unit_interactions(session, brokerage_id, unit_id)
    card_input = ledger_view.listing_card_input(unit, listing, interactions)

    result = _run_async(build_position_card(registry, card_input))
    run = _record_run(
        session,
        brokerage_id=brokerage_id,
        user_id=user_id,
        run_group_id=run_group_id,
        run_type="POSITION_ANALYSIS",
        agent_type="LISTING_DELEGATE",
        trigger_type=trigger_type,
        trace=result.trace,
        unit_id=unit_id,
    )
    analysis = _persist_card(
        session,
        brokerage_id=brokerage_id,
        agent_run_id=run.id or 0,
        side="매물",
        card=result.card,
        label=card_input.label,
        key=key,
        interaction_count=count,
        latest_interaction=latest,
        unit_id=unit_id,
        listing_id=listing.id if listing else None,
        requirement_id=None,
        interactions=interactions,
    )
    return CardOutcome(
        analysis_id=analysis.id or 0,
        card=result.card,
        label=card_input.label,
        cache_hit=False,
    )


def ensure_requirement_card(
    session: Session,
    registry: ProviderRegistry,
    *,
    brokerage_id: int,
    user_id: int,
    requirement_id: int,
    run_group_id: object,
    trigger_type: str,
) -> CardOutcome:
    """구입장 카드 1장을 확보한다."""
    found = repository.find_requirement(session, brokerage_id, requirement_id)
    if found is None:
        raise NotFoundError("property requirement is not found")
    requirement, party = found

    count, latest = repository.interaction_fingerprint(
        session, brokerage_id, requirement_id=requirement_id
    )
    key = cache_key("requirement", requirement_id, count, latest)
    cached = repository.find_valid_position_analysis(session, brokerage_id, key)
    if cached is not None:
        return CardOutcome(
            analysis_id=cached.id or 0,
            card=PositionCard.model_validate(cached.analysis_snapshot),
            label=cached.target_label or party.name,
            cache_hit=True,
        )

    interactions = repository.requirement_interactions(session, brokerage_id, requirement_id)
    card_input = ledger_view.requirement_card_input(requirement, party.name, interactions)

    result = _run_async(build_position_card(registry, card_input))
    run = _record_run(
        session,
        brokerage_id=brokerage_id,
        user_id=user_id,
        run_group_id=run_group_id,
        run_type="POSITION_ANALYSIS",
        agent_type="DEMAND_DELEGATE",
        trigger_type=trigger_type,
        trace=result.trace,
        requirement_id=requirement_id,
    )
    analysis = _persist_card(
        session,
        brokerage_id=brokerage_id,
        agent_run_id=run.id or 0,
        side="손님",
        card=result.card,
        label=card_input.label,
        key=key,
        interaction_count=count,
        latest_interaction=latest,
        unit_id=None,
        listing_id=None,
        requirement_id=requirement_id,
        interactions=interactions,
    )
    return CardOutcome(
        analysis_id=analysis.id or 0,
        card=result.card,
        label=card_input.label,
        cache_hit=False,
    )


def _candidate_facts(
    session: Session,
    brokerage_id: int,
    *,
    unit_id: int,
    label: str,
    card: PositionCard,
    anchor_card: PositionCard,
    desired_pyeong: float | None,
    as_of: date,
) -> CandidateFacts:
    """카드 값 + 장부에서 코드가 뽑은 값을 합쳐 등급 입력을 만든다."""
    unit = repository.find_unit(session, brokerage_id, unit_id)
    if unit is None:
        raise NotFoundError("property unit is not found")
    relations = repository.unit_relations(session, brokerage_id, unit_id)
    interactions = repository.unit_interactions(session, brokerage_id, unit_id)
    handover, _ = ledger_view.available_from(unit, as_of)

    hold = list(ledger_view.hold_flags(unit, relations, interactions, as_of))
    price = card.price
    if price.conflict:
        hold.append(
            f"가격 진술 상충 — {price.conflict} / "
            f"{price.speaker} {price.estimated}억 (덮지 않고 병기)"
        )
    if price.stated_by_tenant:
        hold.append("가격 진술 출처가 임차인(세) 발화 — 소유자 확인 필요")
    if card.contactability.status == "불가":
        hold.append(f"접촉 불가 — 진행 경로 없음 ({card.contactability.note or ''})")

    pyeong = ledger_view.to_float(unit.pyeong)
    meets_pyeong = desired_pyeong is None or (pyeong or 0) >= desired_pyeong
    violations = () if meets_pyeong else (f"평형 {pyeong}평 < 희망 {desired_pyeong}평",)

    inflexible = anchor_card.inflexible or []
    total = max(len(inflexible), 1)
    return CandidateFacts(
        id=str(unit_id),
        label=label,
        deal_type=card.deal_type_now.value,
        deal_type_ref=card.deal_type_now.ref,
        price_est=price.estimated,
        concession=price.concession or 0.0,
        available_from=handover,
        intent=card.intent.value,
        intent_ref=card.intent.evidence,
        contact=card.contactability.status,
        contact_route=card.contactability.route,
        cond_total=total,
        cond_met=1 if meets_pyeong else 0,
        cond_unknown=max(len(inflexible) - 1, 0),
        violates=violations,
        hold=tuple(hold),
    )


def evaluate_matches(
    session: Session,
    registry: ProviderRegistry,
    *,
    brokerage_id: int,
    user_id: int,
    requirement_id: int,
    as_of: date | None = None,
    case_key: str | None = None,
) -> MatchOutcome:
    """[찾기] 트리거. 후보 추출부터 등급 산출까지."""
    resolved_as_of = as_of or datetime.now(UTC).date()
    run_group_id = uuid4()
    llm_calls = 0
    cache_hits = 0

    anchor = ensure_requirement_card(
        session,
        registry,
        brokerage_id=brokerage_id,
        user_id=user_id,
        requirement_id=requirement_id,
        run_group_id=run_group_id,
        trigger_type="USER_FIND",
    )
    llm_calls += 0 if anchor.cache_hit else 1
    cache_hits += 1 if anchor.cache_hit else 0

    found = repository.find_requirement(session, brokerage_id, requirement_id)
    assert found is not None
    requirement, _ = found

    # ① 후보 추출 — LLM 0회. 상한은 장부 표기가 아니라 카드의 추정값이다 (수용 기준 7).
    book_budget = ledger_view.to_eok(requirement.max_budget_amount)
    cap = anchor_cap(anchor.card.price.estimated, book_budget)
    if cap is None:
        raise ValidationError("anchor has neither an estimated nor a recorded budget")

    deal_type = anchor.card.deal_type_now.value
    if deal_type == "불명":
        deal_type = ledger_view.DEMAND_TO_DEAL.get(requirement.demand_type, "매매")
    rows = repository.candidate_rows(session, brokerage_id, deal_type=deal_type)
    pyeongs = requirement.desired_pyeongs or []
    desired_pyeong = ledger_view.to_float(pyeongs[0]) if pyeongs else None
    selection = select_candidates(rows, cap=cap, desired_pyeong=desired_pyeong)

    # ② 후보 카드 확보 — 캐시 미스분만 LLM 을 탄다.
    cards: list[CardOutcome] = []
    for row in selection.kept:
        outcome = ensure_unit_card(
            session,
            registry,
            brokerage_id=brokerage_id,
            user_id=user_id,
            unit_id=row.unit_id,
            run_group_id=run_group_id,
            trigger_type="USER_FIND",
        )
        cards.append(outcome)
        llm_calls += 0 if outcome.cache_hit else 1
        cache_hits += 1 if outcome.cache_hit else 0

    # ③ 중개 판정 — 앵커1 + 후보N 을 한 번의 호출로 (수용 기준 5).
    verdict_by_id: dict[str, object] = {}
    judgement_run_id: int | None = None
    if cards:
        judgement = _run_async(
            judge_matches(
                registry,
                anchor_label=anchor.label,
                anchor_card=anchor.card,
                candidates=tuple(
                    CandidateCardInput(id=str(row.unit_id), label=outcome.label, card=outcome.card)
                    for row, outcome in zip(selection.kept, cards, strict=True)
                ),
            )
        )
        llm_calls += 1
        run = _record_run(
            session,
            brokerage_id=brokerage_id,
            user_id=user_id,
            run_group_id=run_group_id,
            run_type="MATCH_EVALUATION",
            agent_type="BROKER_JUDGE",
            trigger_type="USER_FIND",
            trace=judgement.trace,
            requirement_id=requirement_id,
            case_key=case_key,
        )
        judgement_run_id = run.id
        verdict_by_id = {verdict.id: verdict for verdict in judgement.verdicts}

    # ④ 등급 산출 — LLM 0회. 같은 입력이면 같은 등급이다 (F3-NF-08).
    anchor_facts = AnchorFacts(
        deal_type=deal_type,
        budget_est=cap,
        deadline=ledger_view.hard_deadline(requirement),
        intent=anchor.card.intent.value,
        intent_ref=anchor.card.intent.evidence,
        contact=anchor.card.contactability.status,
    )
    outcomes: list[CandidateOutcome] = []
    for row, outcome in zip(selection.kept, cards, strict=True):
        facts = _candidate_facts(
            session,
            brokerage_id,
            unit_id=row.unit_id,
            label=outcome.label,
            card=outcome.card,
            anchor_card=anchor.card,
            desired_pyeong=desired_pyeong,
            as_of=resolved_as_of,
        )
        verdict = verdict_by_id.get(str(row.unit_id))
        outcomes.append(
            CandidateOutcome(
                unit_id=row.unit_id,
                label=outcome.label,
                result=grade(anchor_facts, facts),
                blocker=getattr(verdict, "blocker", None),
                concession=getattr(verdict, "concession", None),
                action=getattr(verdict, "action", None),
            )
        )

    # 기각도 결과다 — 컷 없이 전부 저장하고 전부 응답한다 (수용 기준 9).
    ranked = sorted(
        outcomes,
        key=lambda item: (item.result.is_rejected, -(item.result.score or 0), item.unit_id),
    )
    evaluation = MatchEvaluation(
        brokerage_id=brokerage_id,
        agent_run_id=judgement_run_id or 0,
        anchor_position_analysis_id=anchor.analysis_id,
        candidate_count=len(ranked),
        data_version=1,
        candidate_selection_snapshot={
            "cap": cap,
            "gate": selection.gate,
            "considered": selection.total,
            "kept": len(selection.kept),
            "dropped": [
                {"unit_id": item.unit_id, "label": item.label, "reason": item.reason}
                for item in selection.dropped
            ],
        },
    )
    analysis_by_unit = {
        row.unit_id: card.analysis_id for row, card in zip(selection.kept, cards, strict=True)
    }
    rows_to_store = [
        MatchCandidateEvaluation(
            brokerage_id=brokerage_id,
            match_evaluation_id=0,
            candidate_position_analysis_id=analysis_by_unit[item.unit_id],
            match_grade=item.result.grade,
            match_rank=rank,
            evaluation_basis=json.dumps(
                {
                    "score": item.result.score,
                    "axes": {
                        name: {"points": axis.points, "note": axis.note}
                        for name, axis in item.result.axes.items()
                    },
                    "flags": list(item.result.flags),
                },
                ensure_ascii=False,
            ),
            primary_obstacle=item.blocker,
            possible_concession=item.concession,
            recommended_action={"action": item.action} if item.action else {},
            exclusion_reason="; ".join(item.result.hard) or None,
        )
        for rank, item in enumerate(ranked, start=1)
    ]
    stored = repository.add_match_evaluation(session, evaluation, rows_to_store) if ranked else None
    session.commit()

    return MatchOutcome(
        evaluation_id=stored.id or 0 if stored else 0,
        anchor_label=anchor.label,
        selection=selection,
        candidates=tuple(ranked),
        llm_calls=llm_calls,
        cache_hits=cache_hits,
    )


def create_position_card(
    session: Session,
    registry: ProviderRegistry,
    *,
    brokerage_id: int,
    user_id: int,
    unit_id: int | None,
    requirement_id: int | None,
) -> CardOutcome:
    """[저장] 트리거. 후보 조회도 중개 판정도 하지 않는다."""
    if (unit_id is None) == (requirement_id is None):
        raise ValidationError("exactly one of unit_id or requirement_id is required")

    run_group_id = uuid4()
    if unit_id is not None:
        outcome = ensure_unit_card(
            session,
            registry,
            brokerage_id=brokerage_id,
            user_id=user_id,
            unit_id=unit_id,
            run_group_id=run_group_id,
            trigger_type="USER_SAVE",
        )
    else:
        outcome = ensure_requirement_card(
            session,
            registry,
            brokerage_id=brokerage_id,
            user_id=user_id,
            requirement_id=requirement_id or 0,
            run_group_id=run_group_id,
            trigger_type="USER_SAVE",
        )
    session.commit()
    return outcome


def build_position_card_input(
    session: Session, brokerage_id: int, *, unit_id: int | None, requirement_id: int | None
) -> PositionCardInput:
    """대리에게 실제로 가는 입력. 격리 검증(수용 기준 3)이 이 함수를 본다."""
    if unit_id is not None:
        unit = repository.find_unit(session, brokerage_id, unit_id)
        if unit is None:
            raise NotFoundError("property unit is not found")
        listing = repository.latest_listing_for_unit(session, brokerage_id, unit_id)
        interactions = repository.unit_interactions(session, brokerage_id, unit_id)
        return ledger_view.listing_card_input(unit, listing, interactions)

    found = repository.find_requirement(session, brokerage_id, requirement_id or 0)
    if found is None:
        raise NotFoundError("property requirement is not found")
    requirement, party = found
    interactions = repository.requirement_interactions(session, brokerage_id, requirement_id or 0)
    return ledger_view.requirement_card_input(requirement, party.name, interactions)
