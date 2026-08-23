"""실행 결과 조회를 위한 읽기 모델 조립.

화면이 필요로 하는 것을 한 번에 모은다. 실행 헤더, 앵커 카드와 그 근거, 후보 조회 조건,
후보별 등급·순위·근거다. 진행 중이면 확보된 데까지만 채운다. 빈 패널을 유지하지 않고 마지막
안전 단계를 보여주기 위해서다 (F3-CR-09).

**여기서 만드는 것은 공개 응답의 재료다.** 사무소 식별자, 요청자, 모델 설정과 스냅샷,
프롬프트, lease 와 내부 실패 원문은 담지 않는다. 무엇을 싣지 않는지는 `api/schemas/f3_runs.py`
가 최종으로 한 번 더 좁힌다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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
    """앵커 포지션 카드 한 장과 그 근거."""

    position_analysis_id: int
    negotiation_side: str
    target_label: str | None
    generated_at: Any
    analysis: dict[str, Any]
    evidence: tuple[NegotiationPositionEvidence, ...]


@dataclass(frozen=True)
class CandidateView:
    """후보 1건. 판정 전이면 SQL 점수만 있고 등급은 비어 있다.

    `CANDIDATES_READY` 까지는 SQL 후보이며 AI 등급이 아니다. 판정 전에 강함·약함·기각을
    노출하지 않는다.
    """

    candidate_id: int
    rank: int
    selected_for_cards: bool
    score: str | None
    price_amount: int | None
    received_at: str | None
    judgment: MatchCandidateEvaluation | None
    evidence: tuple[MatchCandidateEvidence, ...]


@dataclass(frozen=True)
class CandidatePage:
    """후보 목록 한 페이지. 15건 이후도 목록에는 남는다 (F3-BR-14)."""

    items: tuple[CandidateView, ...]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True)
class RunResult:
    """실행 하나의 현재 결과 전체."""

    run: AgentRun
    anchor_card: CardView | None
    criteria: dict[str, Any] | None
    total_count: int
    carded_count: int
    remaining_count: int
    candidates: CandidatePage


def _card_view(session: Session, card: NegotiationPositionAnalysis) -> CardView:
    """저장된 카드를 화면용 읽기 모델로.

    카드 본문은 `analysis_snapshot["analysis"]` 를 그대로 쓴다. 컬럼에서 다시 조립하면 저장
    당시 카드와 미묘하게 달라지고, snapshot 전체를 그대로 내보내면 계약 버전과 진단이 함께
    새어 나간다.
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
    """snapshot 은 JSONB 라 값 타입을 신뢰할 수 없다. 숫자가 아니면 기본값으로 둔다."""
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _as_text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _selection_entries(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """후보 snapshot 의 전체 후보 목록. 읽을 수 없으면 빈 목록으로 다룬다."""
    if snapshot.get("schema") != CANDIDATE_SELECTION_SCHEMA_VERSION:
        return []
    entries = snapshot.get("candidates")
    return (
        [entry for entry in entries if isinstance(entry, dict)] if isinstance(entries, list) else []
    )


def load_run_result(
    session: Session,
    brokerage_id: int,
    run_id: int,
    *,
    limit: int = 20,
    offset: int = 0,
) -> RunResult:
    """실행 하나의 현재 결과를 조립한다. 사무소 범위 밖이면 호출자가 이미 걸렀다.

    후보 목록은 **전체** 후보를 대상으로 페이징한다. 상위 15건만 카드화·판정되지만 나머지도
    조회 조건에 맞는 후보이므로 목록에서 지우지 않는다 (F3-BR-14). 판정이 없는 후보는
    등급·근거가 비어 있고 `selected_for_cards` 가 거짓이다.
    """
    run = require_cross_judgment_run(session, brokerage_id, run_id)

    card = repository.find_anchor_card_for_run(session, brokerage_id, run_id)
    anchor_card = _card_view(session, card) if card is not None else None

    header = repository.find_match_evaluation_for_run(session, brokerage_id, run_id)
    if header is None:
        # 후보 추출 전이다. 앵커 카드까지만 보여준다.
        return RunResult(
            run=run,
            anchor_card=anchor_card,
            criteria=None,
            total_count=0,
            carded_count=0,
            remaining_count=0,
            candidates=CandidatePage(items=(), total=0, limit=limit, offset=offset),
        )

    snapshot = header.candidate_selection_snapshot
    entries = _selection_entries(snapshot)
    judgments = {
        judgment.candidate_position_analysis_id: judgment
        for judgment in repository.list_candidate_judgments(session, brokerage_id, header.id or 0)
    }
    # 후보 장부 ID 에서 그 후보의 카드 ID 로 가는 색인. 판정은 카드 ID 를 가리킨다.
    stored_cards = snapshot.get("candidate_cards")
    card_ids: dict[int, int] = {}
    for entry in stored_cards if isinstance(stored_cards, list) else []:
        if not isinstance(entry, dict):
            continue
        ledger_id = entry.get("candidate_id")
        analysis_id = entry.get("position_analysis_id")
        if isinstance(ledger_id, int) and isinstance(analysis_id, int):
            card_ids[ledger_id] = analysis_id
    evidence_by_candidate: dict[int, list[MatchCandidateEvidence]] = {}
    for item in repository.list_candidate_judgment_evidence(
        session, brokerage_id, [judgment.id or 0 for judgment in judgments.values()]
    ):
        evidence_by_candidate.setdefault(item.match_candidate_evaluation_id, []).append(item)

    views: list[CandidateView] = []
    for entry in entries:
        candidate_id = entry.get("candidate_id")
        if not isinstance(candidate_id, int):
            continue
        analysis_id = card_ids.get(candidate_id)
        judgment = judgments.get(analysis_id) if analysis_id is not None else None
        views.append(
            CandidateView(
                candidate_id=candidate_id,
                rank=judgment.match_rank if judgment else _as_int(entry.get("rank")),
                selected_for_cards=bool(entry.get("selected_for_cards")),
                score=_as_text(entry.get("score")),
                price_amount=_as_int(entry.get("price_amount"), 0) or None,
                received_at=_as_text(entry.get("received_at")),
                judgment=judgment,
                evidence=tuple(evidence_by_candidate.get(judgment.id or 0, [])) if judgment else (),
            )
        )

    window = views[offset : offset + limit]
    return RunResult(
        run=run,
        anchor_card=anchor_card,
        criteria=criteria if isinstance(criteria := snapshot.get("criteria"), dict) else None,
        total_count=_as_int(snapshot.get("total_count"), len(views)),
        carded_count=_as_int(snapshot.get("carded_count")),
        remaining_count=_as_int(snapshot.get("remaining_count")),
        candidates=CandidatePage(items=tuple(window), total=len(views), limit=limit, offset=offset),
    )
