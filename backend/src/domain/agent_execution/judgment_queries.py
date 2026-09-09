"""사무소 공유 F3 결과 read model. 모든 유스케이스는 조회만 수행한다."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlmodel import Session, col, select

from core.errors import NotFoundError, ValidationError
from domain.agent_execution import repository, results
from domain.agent_execution.judgment_content import (
    allowed_logs,
    candidate_summary,
    enrich_selected,
    public_card,
)
from domain.agent_execution.judgment_targets import TargetLabel, load_target_labels, require_label
from domain.agent_execution.models import (
    AgentRun,
    AnchorType,
    MatchCandidateEvaluation,
    MatchEvaluation,
    NegotiationPositionAnalysis,
    anchor_of,
)

FILTERS = ("HAS_MATCH", "HAS_STRONG", "HAS_UNJUDGED", "NEEDS_ATTENTION", "ALL")


@dataclass
class ReadContext:
    labels: dict[int, TargetLabel]
    counterparts: dict[int, TargetLabel]
    latest: dict[int, AgentRun]
    completed: dict[int, AgentRun]
    headers: dict[int, MatchEvaluation]
    judgments: dict[int, list[MatchCandidateEvaluation]]
    valid_cards: set[int]
    freshness: dict[int, str]
    states: dict[int, dict[str, Any]]


def _load_context(
    session: Session, b: int, kind: AnchorType, anchor_id: int | None = None
) -> ReadContext:
    labels = load_target_labels(
        session, b, kind, ids=[anchor_id] if anchor_id is not None else None
    )
    other = AnchorType.REQUIREMENT if kind is AnchorType.LISTING else AnchorType.LISTING
    # 최신 실행과 마지막 성공을 따로 읽어 갱신 실패에도 성공 결과를 보존한다.
    target_column = "target_listing_id" if kind is AnchorType.LISTING else "target_requirement_id"
    ids = (
        session.execute(
            text(f"""
        SELECT DISTINCT ON ({target_column}, completed) id
        FROM (
            SELECT id, {target_column}, (status='COMPLETED') AS completed
            FROM agent_run WHERE brokerage_id=:b AND parent_run_id IS NULL
              AND run_type='CROSS_JUDGMENT' AND {target_column} IS NOT NULL
              AND purged_at IS NULL
              AND (CAST(:anchor_id AS bigint) IS NULL OR {target_column}=:anchor_id)
        ) r ORDER BY {target_column}, completed, id DESC
    """),
            {"b": b, "anchor_id": anchor_id},
        )
        .scalars()
        .all()
    )
    runs = (
        list(
            session.execute(
                select(AgentRun).where(col(AgentRun.brokerage_id) == b, col(AgentRun.id).in_(ids))
            ).scalars()
        )
        if ids
        else []
    )
    completed, latest = {}, {}
    for run in runs:
        _, run_anchor_id = anchor_of(run)
        if run_anchor_id not in labels:
            continue
        if run_anchor_id not in latest or (run.id or 0) > (latest[run_anchor_id].id or 0):
            latest[run_anchor_id] = run
        if run.status == "COMPLETED":
            completed[run_anchor_id] = run
    completed_ids = [run.id for run in completed.values()]
    headers = (
        {
            h.agent_run_id: h
            for h in session.execute(
                select(MatchEvaluation).where(
                    col(MatchEvaluation.brokerage_id) == b,
                    col(MatchEvaluation.agent_run_id).in_(completed_ids),
                )
            ).scalars()
        }
        if completed_ids
        else {}
    )
    candidate_ids = [
        int(entry["candidate_id"])
        for header in headers.values()
        for entry in results._selection_entries(header.candidate_selection_snapshot)
        if isinstance(entry.get("candidate_id"), int)
    ]
    counterparts = load_target_labels(
        session, b, other, ids=candidate_ids if anchor_id is not None else None
    )
    header_ids = [header.id for header in headers.values()]
    judgments: dict[int, list[MatchCandidateEvaluation]] = {}
    if header_ids:
        for judgment in session.execute(
            select(MatchCandidateEvaluation).where(
                col(MatchCandidateEvaluation.brokerage_id) == b,
                col(MatchCandidateEvaluation.match_evaluation_id).in_(header_ids),
            )
        ).scalars():
            judgments.setdefault(judgment.match_evaluation_id, []).append(judgment)
    card_ids = [h.anchor_position_analysis_id for h in headers.values()]
    card_ids.extend(j.candidate_position_analysis_id for group in judgments.values() for j in group)
    valid_cards = (
        set(
            session.execute(
                select(col(NegotiationPositionAnalysis.id)).where(
                    col(NegotiationPositionAnalysis.brokerage_id) == b,
                    col(NegotiationPositionAnalysis.id).in_(card_ids),
                    col(NegotiationPositionAnalysis.invalidated_at).is_(None),
                )
            ).scalars()
        )
        if card_ids
        else set()
    )
    from domain.agent_execution.freshness import read_currentness_many

    freshness = read_currentness_many(session, list(completed.values()))
    states = {
        row["anchor_id"]: dict(row)
        for row in session.execute(
            text("""SELECT * FROM match_target_state WHERE brokerage_id=:b AND anchor_type=:kind
                AND (CAST(:anchor_id AS bigint) IS NULL OR anchor_id=:anchor_id)"""),
            {"b": b, "kind": kind.value, "anchor_id": anchor_id},
        ).mappings()
    }
    return ReadContext(
        labels, counterparts, latest, completed, headers, judgments, valid_cards, freshness, states
    )


def _label_eligibility(label: TargetLabel) -> str:
    return label.eligibility


def _views(header: MatchEvaluation, context: ReadContext) -> list[results.CandidateView]:
    snapshot = header.candidate_selection_snapshot
    cards = snapshot.get("candidate_cards")
    cards_by_candidate = (
        {
            entry["candidate_id"]: entry["position_analysis_id"]
            for entry in cards
            if isinstance(entry, dict)
            and isinstance(entry.get("candidate_id"), int)
            and isinstance(entry.get("position_analysis_id"), int)
        }
        if isinstance(cards, list)
        else {}
    )
    judgments = {
        j.candidate_position_analysis_id: j for j in context.judgments.get(header.id or 0, [])
    }
    views = []
    for entry in results._selection_entries(snapshot):
        candidate_id = entry.get("candidate_id")
        if not isinstance(candidate_id, int) or candidate_id not in context.counterparts:
            continue
        # 현재 적격성과 당시 후보 집합은 별개다. 종료·조건 미충족만으로 과거 후보를 지우지 않는다.
        # 삭제·권한 밖 후보는 위의 현재 사무소 표기 조회에서 계속 제외한다.
        card_id = cards_by_candidate.get(candidate_id)
        judgment = judgments.get(card_id) if card_id in context.valid_cards else None
        views.append(
            results.CandidateView(
                candidate_id=candidate_id,
                rank=judgment.match_rank if judgment else results._as_int(entry.get("rank")),
                selected_for_cards=entry.get("selected_for_cards") is True,
                score=results._as_text(entry.get("score")),
                price_amount=results._as_int(entry.get("price_amount")) or None,
                monthly_amount=results._as_int(entry.get("monthly_amount")) or None,
                received_at=results._as_text(entry.get("received_at")),
                judgment=judgment,
                evidence=(),
            )
        )
    return views


def _is_synthetic_fixture(run: AgentRun | None) -> bool:
    marker = run.redacted_output_snapshot.get("synthetic_fixture") if run else None
    return isinstance(marker, dict) and marker.get("kind") == "DETERMINISTIC_MATCH_SEED"


def _target(context: ReadContext, anchor_id: int) -> dict[str, Any]:
    label = require_label(context.labels, anchor_id)
    run = context.completed.get(anchor_id)
    latest = context.latest.get(anchor_id)
    header = context.headers.get(run.id or 0) if run else None
    eligibility = _label_eligibility(label)
    available = bool(
        eligibility == "ELIGIBLE"
        and run
        and header
        and results._may_expose_prototype_content(run)
        and header.anchor_position_analysis_id in context.valid_cards
    )
    views = _views(header, context) if header and available else []
    summary = None
    if available:
        grades = [view.judgment.match_grade for view in views if view.judgment]
        summary = {
            "total_count": len(views),
            "judged_count": len(grades),
            "strong_count": grades.count("STRONG"),
            "weak_count": grades.count("WEAK"),
            "rejected_count": grades.count("REJECTED"),
            "unjudged_count": len(views) - len(grades),
        }
    representatives = sorted(
        (view for view in views if view.judgment and view.judgment.match_grade != "REJECTED"),
        key=lambda view: view.rank,
    )[:3]
    state = context.states.get(anchor_id, {})
    generation = "IDLE"
    if latest and latest.status in {"FAILED_TERMINAL", "SUPERSEDED"}:
        generation = "FAILED"
    elif latest and latest.status not in {"COMPLETED", "CANCELLED"}:
        generation = "QUEUED" if latest.status == "QUEUED" else "RUNNING"
    if generation == "IDLE" and state.get("due_at") is not None:
        generation = "QUEUED"
    return {
        "anchor": label.public(),
        "is_synthetic_fixture": _is_synthetic_fixture(run),
        "result_id": header.id if header else None,
        "run_id": latest.id if latest else None,
        "eligibility": eligibility,
        "eligibility_reason": None
        if eligibility == "ELIGIBLE"
        else "활성 거래 조건을 확인해 주세요",
        "content_availability": "AVAILABLE" if available else "UNAVAILABLE",
        "freshness": context.freshness.get(run.id or 0, "STALE") if run else "NONE",
        "generation": generation,
        "generated_at": run.completed_at if run else None,
        "meaningful_changed_at": state.get("meaningful_changed_at")
        or (run.completed_at if run else None),
        "summary": summary,
        "representative_candidates": [
            candidate_summary(view, context.counterparts[view.candidate_id])
            for view in representatives
        ],
    }


def _matches(item: dict[str, Any], filter_name: str) -> bool:
    summary = item["summary"] or {}
    current = item["freshness"] == "CURRENT" and item["content_availability"] == "AVAILABLE"
    if filter_name == "HAS_MATCH":
        return current and bool(summary.get("strong_count", 0) + summary.get("weak_count", 0))
    if filter_name == "HAS_STRONG":
        return current and bool(summary.get("strong_count", 0))
    if filter_name == "HAS_UNJUDGED":
        return bool(summary.get("unjudged_count", 0))
    if filter_name == "NEEDS_ATTENTION":
        return not current or item["generation"] == "FAILED" or item["eligibility"] != "ELIGIBLE"
    return True


def _cursor(offset: int, identity: str) -> str:
    return base64.urlsafe_b64encode(json.dumps([offset, identity]).encode()).decode()


def _offset(cursor: str | None, identity: str) -> int:
    if cursor is None:
        return 0
    try:
        offset, saved = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
        if type(offset) is not int or offset < 0 or saved != identity:
            raise ValueError
        return offset
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        raise ValidationError(
            "목록이 변경되었습니다. 첫 페이지부터 다시 확인해 주세요", "F3_CURSOR_INVALID"
        ) from error


def list_judgments(
    session: Session,
    brokerage_id: int,
    anchor_type: AnchorType,
    *,
    filter_name: str = "HAS_MATCH",
    trade_type: str | None = None,
    complex_id: int | None = None,
    assignee_id: int | None = None,
    q: str | None = None,
    cursor: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    context = _load_context(session, brokerage_id, anchor_type)
    items = []
    for anchor_id, label in context.labels.items():
        if trade_type and trade_type not in label.trade_types:
            continue
        if complex_id is not None and complex_id not in label.complex_ids:
            continue
        if assignee_id is not None and label.assignee_id != assignee_id:
            continue
        item = _target(context, anchor_id)
        if q:
            searchable = label.display_name + " " + (label.complex_name or "")
            run = context.completed.get(anchor_id)
            header = context.headers.get(run.id or 0) if run else None
            if header and item["content_availability"] == "AVAILABLE":
                searchable += " ".join(
                    context.counterparts[v.candidate_id].display_name
                    for v in _views(header, context)
                )
            if q.casefold() not in searchable.casefold():
                continue
        items.append(item)
    counts = {name: sum(_matches(item, name) for item in items) for name in FILTERS}
    # revision은 원문을 담지 않는 digest다. 상태 변화 사이에 cursor를 재사용하지 않는다.
    revision = hashlib.sha256(json.dumps(items, sort_keys=True, default=str).encode()).hexdigest()[
        :24
    ]
    identity = hashlib.sha256(
        json.dumps(
            [
                brokerage_id,
                anchor_type.value,
                filter_name,
                trade_type,
                complex_id,
                assignee_id,
                q,
                revision,
            ]
        ).encode()
    ).hexdigest()
    offset = _offset(cursor, identity)
    items = [item for item in items if _matches(item, filter_name)]
    items.sort(
        key=lambda item: (str(item["meaningful_changed_at"] or ""), item["anchor"]["anchor_id"]),
        reverse=True,
    )
    assignees = [
        dict(row)
        for row in session.execute(
            text(
                "SELECT id, display_name FROM app_user WHERE brokerage_id=:b AND is_active "
                "ORDER BY display_name,id"
            ),
            {"b": brokerage_id},
        ).mappings()
    ]
    return {
        "assignees": assignees,
        "items": items[offset : offset + limit],
        "counts": counts,
        "revision": revision,
        "next_cursor": _cursor(offset + limit, identity) if offset + limit < len(items) else None,
        "checked_at": datetime.now(UTC),
    }


def get_target(
    session: Session, brokerage_id: int, anchor_type: AnchorType, anchor_id: int
) -> dict[str, Any]:
    return _target(_load_context(session, brokerage_id, anchor_type, anchor_id), anchor_id)


def get_judgment(
    session: Session,
    brokerage_id: int,
    result_id: int,
    *,
    cursor: str | None = None,
    limit: int = 20,
    candidate_id: int | None = None,
) -> dict[str, Any]:
    header = (
        session.execute(
            select(MatchEvaluation).where(
                col(MatchEvaluation.brokerage_id) == brokerage_id,
                col(MatchEvaluation.id) == result_id,
            )
        )
        .scalars()
        .first()
    )
    if header is None:
        raise NotFoundError("judgment result is not found")
    run = repository.find_root_cross_judgment_run(session, brokerage_id, header.agent_run_id)
    if run is None or run.status != "COMPLETED" or run.purged_at is not None:
        raise NotFoundError("judgment result is not found")
    kind, anchor_id = anchor_of(run)
    context = _load_context(session, brokerage_id, kind, anchor_id)
    current = _target(context, anchor_id)
    anchor = require_label(context.labels, anchor_id)
    raw = results.load_run_result(session, brokerage_id, run.id or 0, limit=1)
    value = {
        **current,
        "result_id": result_id,
        "current_result_id": current["result_id"],
        "is_synthetic_fixture": _is_synthetic_fixture(run),
        "generated_at": run.completed_at,
        "anchor_card": None,
        "candidates": [],
        "selected_candidate": None,
        "next_cursor": None,
    }
    from domain.agent_execution.freshness import read_currentness

    value["freshness"] = read_currentness(session, run)
    if raw.anchor_card is None or current["eligibility"] != "ELIGIBLE":
        value.update(content_availability="UNAVAILABLE", summary=None, representative_candidates=[])
        return value
    old_ids = [
        int(entry["candidate_id"])
        for entry in results._selection_entries(header.candidate_selection_snapshot)
        if isinstance(entry.get("candidate_id"), int)
    ]
    opposite = AnchorType.REQUIREMENT if kind is AnchorType.LISTING else AnchorType.LISTING
    context.counterparts.update(load_target_labels(session, brokerage_id, opposite, ids=old_ids))
    context.valid_cards.add(header.anchor_position_analysis_id)
    # 과거 snapshot을 읽되 현재 삭제된 후보는 노출하지 않는다.
    context.headers[run.id or 0] = header
    context.judgments[header.id or 0] = repository.list_candidate_judgments(
        session, brokerage_id, result_id
    )
    old_cards = [j.candidate_position_analysis_id for j in context.judgments[result_id]]
    context.valid_cards.update(
        card.id or 0 for card in repository.list_position_cards(session, brokerage_id, old_cards)
    )
    context.completed[anchor_id] = run
    context.freshness[run.id or 0] = read_currentness(session, run)
    snapshot_value = _target(context, anchor_id)
    value.update(snapshot_value, result_id=result_id, current_result_id=current["result_id"])
    logs = allowed_logs(session, brokerage_id, anchor)
    anchor_log_ids = {item.id for item in logs if item.id is not None}
    value["anchor_card"] = public_card(raw.anchor_card, anchor_log_ids)
    views = _views(header, context)
    identity = hashlib.sha256(
        json.dumps([brokerage_id, result_id, [v.candidate_id for v in views]]).encode()
    ).hexdigest()
    offset = _offset(cursor, identity)
    page = views[offset : offset + limit]
    value["candidates"] = [
        candidate_summary(view, context.counterparts[view.candidate_id]) for view in page
    ]
    selected = (
        next((v for v in views if v.candidate_id == candidate_id), None)
        if candidate_id
        else (page[0] if page else None)
    )
    if candidate_id is not None and selected is None:
        raise NotFoundError("judgment candidate is not found")
    if selected:
        evidence = (
            tuple(
                repository.list_candidate_judgment_evidence(
                    session, brokerage_id, [selected.judgment.id or 0]
                )
            )
            if selected.judgment
            else ()
        )
        from dataclasses import replace

        selected = replace(selected, evidence=evidence)
        value["selected_candidate"] = enrich_selected(
            session,
            brokerage_id,
            header,
            selected,
            anchor,
            context.counterparts[selected.candidate_id],
            anchor_log_ids,
        )
    value["next_cursor"] = (
        _cursor(offset + limit, identity) if offset + limit < len(views) else None
    )
    return value
