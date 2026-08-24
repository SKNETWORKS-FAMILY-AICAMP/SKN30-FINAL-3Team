"""F3 실행 결과 조회용 읽기 모델.

진행 중인 실행은 이미 저장된 안전한 단계까지만 조립한다. 공개 응답의 최종 필드 제한은
``api.schemas.f3_runs``가 소유하며, 이 모듈은 테넌트 범위가 적용된 영속 데이터를 화면 단위로
모으는 역할만 한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from brokerage_ai.f3 import InputPrivacyMode
from sqlmodel import Session

from domain.agent_execution import repository
from domain.agent_execution.candidates import CANDIDATE_SELECTION_SCHEMA_VERSION
from domain.agent_execution.models import (
    AgentRun,
    MatchCandidateEvaluation,
    MatchCandidateEvidence,
    NegotiationPositionAnalysis,
    NegotiationPositionEvidence,
)
from domain.agent_execution.service import require_cross_judgment_run


@dataclass(frozen=True)
class CardView:
    position_analysis_id: int
    negotiation_side: str
    target_label: str | None
    generated_at: datetime | None
    analysis: dict[str, Any]
    evidence: tuple[NegotiationPositionEvidence, ...]


@dataclass(frozen=True)
class CandidateView:
    """후보 한 건. 판정 전에는 SQL 순위·점수만 있고 AI 판정은 비어 있다."""

    candidate_id: int
    rank: int
    selected_for_cards: bool
    score: str | None
    price_amount: int | None
    monthly_amount: int | None
    received_at: str | None
    judgment: MatchCandidateEvaluation | None
    evidence: tuple[MatchCandidateEvidence, ...]


@dataclass(frozen=True)
class CandidatePage:
    items: tuple[CandidateView, ...]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True)
class RunResult:
    run: AgentRun
    anchor_card: CardView | None
    criteria: dict[str, Any] | None
    total_count: int
    carded_count: int
    remaining_count: int
    candidates: CandidatePage


def _card_view(session: Session, card: NegotiationPositionAnalysis) -> CardView:
    """저장 snapshot에서 공개 카드 본문만 꺼낸다.

    snapshot 전체에는 계약·프롬프트·워크플로·모델 진단이 들어갈 수 있으므로 ``analysis``만
    공개 읽기 모델에 싣는다.
    """
    snapshot = card.analysis_snapshot
    analysis = snapshot.get("analysis") if isinstance(snapshot, dict) else None
    return CardView(
        position_analysis_id=card.id or 0,
        negotiation_side=card.negotiation_side,
        target_label=card.target_label,
        generated_at=card.generated_at,
        analysis=analysis if isinstance(analysis, dict) else {},
        evidence=tuple(repository.list_card_evidence(session, card.brokerage_id, card.id or 0)),
    )


def _as_int(value: object, default: int = 0) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _as_text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _selection_entries(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """현재 schema의 전체 SQL 후보 목록만 읽는다."""
    if snapshot.get("schema") != CANDIDATE_SELECTION_SCHEMA_VERSION:
        return []
    entries = snapshot.get("candidates")
    return (
        [entry for entry in entries if isinstance(entry, dict)] if isinstance(entries, list) else []
    )


def _empty_result(run: AgentRun, limit: int, offset: int) -> RunResult:
    """실행 상태만 공개하고 카드·후보 내용은 비운다."""
    return RunResult(
        run=run,
        anchor_card=None,
        criteria=None,
        total_count=0,
        carded_count=0,
        remaining_count=0,
        candidates=CandidatePage(items=(), total=0, limit=limit, offset=offset),
    )


def _may_expose_prototype_content(run: AgentRun) -> bool:
    """저장 단계에서 확인된 합성 프로토타입 실행만 카드·근거를 공개한다."""
    return (
        run.redacted_output_snapshot.get("input_privacy_mode")
        == InputPrivacyMode.SYNTHETIC_PROTOTYPE.value
    )


def load_run_result(
    session: Session,
    brokerage_id: int,
    run_id: int,
    *,
    limit: int = 20,
    offset: int = 0,
) -> RunResult:
    """실행의 현재 결과를 조립한다.

    루트 CROSS_JUDGMENT 실행과 중개사무소 격리는 기존 상태 조회 유스케이스를 재사용한다.
    후보 목록은 카드화된 상위 후보만이 아니라 snapshot의 전체 SQL 후보를 페이지 처리한다.
    """
    run = require_cross_judgment_run(session, brokerage_id, run_id)

    # queued/running 실행과 이 표식이 생기기 전의 과거·수동 실행은 상태 자체는 조회할 수
    # 있지만 개인정보가 섞일 수 있는 카드와 근거는 반환하지 않는다.
    if not _may_expose_prototype_content(run):
        return _empty_result(run, limit, offset)

    card = repository.find_anchor_card_for_run(session, brokerage_id, run_id)
    anchor_card = _card_view(session, card) if card is not None else None

    header = repository.find_match_evaluation_for_run(session, brokerage_id, run_id)
    if header is None:
        empty = _empty_result(run, limit, offset)
        return RunResult(
            run=empty.run,
            anchor_card=anchor_card,
            criteria=empty.criteria,
            total_count=empty.total_count,
            carded_count=empty.carded_count,
            remaining_count=empty.remaining_count,
            candidates=empty.candidates,
        )

    snapshot = header.candidate_selection_snapshot
    entries = _selection_entries(snapshot)
    judgments = {
        judgment.candidate_position_analysis_id: judgment
        for judgment in repository.list_candidate_judgments(session, brokerage_id, header.id or 0)
    }

    # SQL 후보 장부 ID와 카드 ID를 잇는다. 판정 행은 후보 카드 ID를 참조한다.
    candidate_card_ids: dict[int, int] = {}
    stored_cards = snapshot.get("candidate_cards")
    for entry in stored_cards if isinstance(stored_cards, list) else []:
        if not isinstance(entry, dict):
            continue
        candidate_id = entry.get("candidate_id")
        position_analysis_id = entry.get("position_analysis_id")
        if isinstance(candidate_id, int) and isinstance(position_analysis_id, int):
            candidate_card_ids[candidate_id] = position_analysis_id

    evidence_by_judgment: dict[int, list[MatchCandidateEvidence]] = {}
    for evidence in repository.list_candidate_judgment_evidence(
        session, brokerage_id, [judgment.id or 0 for judgment in judgments.values()]
    ):
        evidence_by_judgment.setdefault(evidence.match_candidate_evaluation_id, []).append(evidence)

    views: list[CandidateView] = []
    for entry in entries:
        candidate_id = entry.get("candidate_id")
        if not isinstance(candidate_id, int):
            continue
        position_analysis_id = candidate_card_ids.get(candidate_id)
        judgment = judgments.get(position_analysis_id) if position_analysis_id is not None else None
        views.append(
            CandidateView(
                candidate_id=candidate_id,
                rank=judgment.match_rank if judgment else _as_int(entry.get("rank")),
                selected_for_cards=entry.get("selected_for_cards") is True,
                score=_as_text(entry.get("score")),
                price_amount=_as_int(entry.get("price_amount"), 0) or None,
                monthly_amount=_as_int(entry.get("monthly_amount"), 0) or None,
                received_at=_as_text(entry.get("received_at")),
                judgment=judgment,
                evidence=(
                    tuple(evidence_by_judgment.get(judgment.id or 0, [])) if judgment else ()
                ),
            )
        )

    criteria = snapshot.get("criteria")
    return RunResult(
        run=run,
        anchor_card=anchor_card,
        criteria=criteria if isinstance(criteria, dict) else None,
        total_count=_as_int(snapshot.get("total_count"), len(views)),
        carded_count=_as_int(snapshot.get("carded_count")),
        remaining_count=_as_int(snapshot.get("remaining_count")),
        candidates=CandidatePage(
            items=tuple(views[offset : offset + limit]),
            total=len(views),
            limit=limit,
            offset=offset,
        ),
    )
