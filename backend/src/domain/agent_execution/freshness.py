"""F3 freshness and semantic identity. Reads never enqueue or invoke a model.

Source revision is a conservative, cheap invalidation fence. The command/Worker verifies
actual model inputs and the SQL candidate set before reusing a completed result.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from brokerage_ai.f3 import (
    BROKERAGE_JUDGMENT_PROMPT_VERSION,
    BROKERAGE_JUDGMENT_WORKFLOW_VERSION,
    POSITION_CARD_PROMPT_VERSION,
    POSITION_CARD_WORKFLOW_VERSION,
    InputPrivacyMode,
)
from sqlalchemy import text
from sqlmodel import Session

from core.errors import NotFoundError
from domain.agent_execution import repository, snapshot
from domain.agent_execution.fingerprint import input_fingerprint
from domain.agent_execution.models import AgentRun, AnchorType, InputVersionChangedError, anchor_of


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def current_revision(session: Session, brokerage_id: int, *, lock: bool = False) -> int:
    suffix = " FOR SHARE" if lock else ""
    return (
        session.execute(
            text("SELECT revision FROM match_source_revision WHERE brokerage_id=:tenant" + suffix),
            {"tenant": brokerage_id},
        ).scalar_one_or_none()
        or 0
    )


def configuration_identity(session: Session, brokerage_id: int) -> str:
    from domain.agent_execution.candidates import (
        ACTIVE_LISTING_STATUSES,
        ACTIVE_REQUIREMENT_STATUSES,
        AREA_WEIGHT,
        CANDIDATE_CARD_LIMIT,
        CANDIDATE_SELECTION_SCHEMA_VERSION,
        PRICE_TOLERANCE_RATIO,
        PRICE_WEIGHT,
        PYEONG_TOLERANCE,
        RECENCY_WEIGHT,
    )

    policy = [
        CANDIDATE_SELECTION_SCHEMA_VERSION,
        CANDIDATE_CARD_LIMIT,
        str(PRICE_TOLERANCE_RATIO),
        str(PYEONG_TOLERANCE),
        str(PRICE_WEIGHT),
        str(AREA_WEIGHT),
        str(RECENCY_WEIGHT),
        sorted(ACTIVE_LISTING_STATUSES),
        sorted(ACTIVE_REQUIREMENT_STATUSES),
    ]
    rows = (
        session.execute(
            text("""
        SELECT DISTINCT ON (capability) capability, id, config_key, config_version,
            provider, model_name, model_version, endpoint_alias
        FROM ai_model_config WHERE brokerage_id=:tenant AND is_active
          AND capability IN ('POSITION_CARD', 'BROKERAGE_JUDGMENT')
        ORDER BY capability, config_version DESC, id DESC
    """),
            {"tenant": brokerage_id},
        )
        .mappings()
        .all()
    )
    return digest(
        [
            *[dict(row) for row in rows],
            POSITION_CARD_PROMPT_VERSION,
            POSITION_CARD_WORKFLOW_VERSION,
            BROKERAGE_JUDGMENT_PROMPT_VERSION,
            BROKERAGE_JUDGMENT_WORKFLOW_VERSION,
            policy,
        ]
    )


def target_state(
    session: Session, brokerage_id: int, anchor_type: AnchorType, anchor_id: int
) -> dict[str, Any] | None:
    row = (
        session.execute(
            text("""SELECT * FROM match_target_state WHERE brokerage_id=:tenant
        AND anchor_type=:kind AND anchor_id=:id"""),
            {"tenant": brokerage_id, "kind": anchor_type.value, "id": anchor_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def read_currentness(
    session: Session,
    run: AgentRun,
    *,
    state: dict[str, Any] | None = None,
    revision: int | None = None,
    config_identity: str | None = None,
) -> str:
    """Pass batch-loaded state/revision/config to avoid per-row SQL on list endpoints."""
    if run.status != "COMPLETED":
        return "NONE"
    kind, anchor_id = anchor_of(run)
    state = state if state is not None else target_state(session, run.brokerage_id, kind, anchor_id)
    if not state or state["current_run_id"] != run.id:
        return "STALE"
    revision = current_revision(session, run.brokerage_id) if revision is None else revision
    config_identity = config_identity or configuration_identity(session, run.brokerage_id)
    if (
        state["verified_revision"] != revision
        or str(state["verified_day"]) != datetime.now(UTC).date().isoformat()
        or state["config_identity"] != config_identity
    ):
        return "STALE"
    return "CURRENT"


def eligibility(
    session: Session, brokerage_id: int, kind: AnchorType, anchor_id: int
) -> tuple[str, str | None]:
    from domain.agent_execution.candidates import (
        ACTIVE_LISTING_STATUSES,
        ACTIVE_REQUIREMENT_STATUSES,
        DEMAND_TYPE_TO_PRICE_KIND,
    )

    if kind is AnchorType.LISTING:
        target = repository.find_listing_anchor(session, brokerage_id, anchor_id)
        if target is None:
            raise NotFoundError()
        if target.status not in ACTIVE_LISTING_STATUSES:
            return "INELIGIBLE", "진행 중인 매물만 분석할 수 있습니다"
        if not (
            target.is_sale_available
            or target.is_jeonse_available
            or target.is_monthly_rent_available
        ):
            return "INSUFFICIENT_INPUT", "거래 유형을 입력해 주세요"
    else:
        target = repository.find_requirement_anchor(session, brokerage_id, anchor_id)
        if target is None:
            raise NotFoundError()
        if target.status not in ACTIVE_REQUIREMENT_STATUSES:
            return "INELIGIBLE", "진행 중인 손님 조건만 분석할 수 있습니다"
        if target.demand_type not in DEMAND_TYPE_TO_PRICE_KIND:
            return "INSUFFICIENT_INPUT", "지원하는 거래 유형을 입력해 주세요"
    return "ELIGIBLE", None


def anchor_identity(session: Session, tenant: int, kind: AnchorType, anchor_id: int) -> str:
    assembled = snapshot.build_anchor_snapshot(
        session,
        tenant,
        kind,
        anchor_id,
        as_of=datetime.now(UTC),
        input_privacy_mode=InputPrivacyMode.SYNTHETIC_PROTOTYPE,
    )
    # Row versions also change for operational edits not present in model inputs.
    request = assembled.request.model_copy(
        update={"source": assembled.request.source.model_copy(update={"data_version": 1})}
    )
    return digest([input_fingerprint(request), assembled.scope.identity()])


def complete_input_identity(session: Session, run: AgentRun) -> tuple[str, str]:
    """Requery candidates using the stored anchor card; no narrow pre-card price gate."""
    from domain.agent_execution.candidates import _require_anchor_card, select_candidates

    kind, anchor_id = anchor_of(run)
    anchor = anchor_identity(session, run.brokerage_id, kind, anchor_id)
    card = _require_anchor_card(session, run, kind, anchor_id)
    selection = select_candidates(
        session, run.brokerage_id, card, kind, as_of=datetime.now(UTC).date()
    )
    opposite = AnchorType.REQUIREMENT if kind is AnchorType.LISTING else AnchorType.LISTING
    selected = [
        (item.candidate_id, anchor_identity(session, run.brokerage_id, opposite, item.candidate_id))
        for item in selection.carded
    ]
    payload = [
        anchor,
        selection.criteria.as_snapshot(),
        [
            item.as_snapshot(index + 1, index < len(selection.carded))
            for index, item in enumerate(selection.ordered)
        ],
        selected,
        configuration_identity(session, run.brokerage_id),
    ]
    return digest(payload), anchor


def intake_metadata(session: Session, tenant: int) -> dict[str, object]:
    return {
        "revision": current_revision(session, tenant),
        "day": datetime.now(UTC).date().isoformat(),
        "configuration": configuration_identity(session, tenant),
    }


def verify_run_fence(session: Session, run: AgentRun) -> None:
    marker = run.redacted_input_snapshot.get("automation")
    if not isinstance(marker, dict):
        return  # Legacy jobs retain their existing per-card fencing and publish as stale.
    actual = intake_metadata(session, run.brokerage_id)
    actual["revision"] = current_revision(session, run.brokerage_id, lock=True)
    if marker != actual:
        raise InputVersionChangedError("the source or execution configuration changed")


def publish_result(session: Session, run: AgentRun, result_id: int) -> None:
    """Called inside the judgment transaction after fencing; never commits itself."""
    verify_run_fence(session, run)
    if not isinstance(run.redacted_input_snapshot.get("automation"), dict):
        return
    identity, anchor = complete_input_identity(session, run)
    kind, anchor_id = anchor_of(run)
    marker = intake_metadata(session, run.brokerage_id)
    session.execute(
        text("""INSERT INTO match_target_state
        (brokerage_id, anchor_type, anchor_id, desired_revision, verified_revision,
         verified_day, config_identity, input_identity, anchor_identity,
         current_run_id, current_result_id, verified_at, meaningful_changed_at)
        VALUES (:tenant,:kind,:anchor,:revision,:revision,:day,:config,:identity,
                :anchor_identity,:run,:result,now(),now())
        ON CONFLICT (brokerage_id,anchor_type,anchor_id) DO UPDATE SET
          desired_revision=GREATEST(match_target_state.desired_revision,EXCLUDED.desired_revision),
          verified_revision=EXCLUDED.verified_revision, verified_day=EXCLUDED.verified_day,
          config_identity=EXCLUDED.config_identity, input_identity=EXCLUDED.input_identity,
          anchor_identity=EXCLUDED.anchor_identity,current_run_id=EXCLUDED.current_run_id,
          current_result_id=EXCLUDED.current_result_id,verified_at=now(),
          meaningful_changed_at=now(), due_at=NULL"""),
        {
            "tenant": run.brokerage_id,
            "kind": kind.value,
            "anchor": anchor_id,
            "revision": marker["revision"],
            "day": marker["day"],
            "config": marker["configuration"],
            "identity": identity,
            "anchor_identity": anchor,
            "run": run.id,
            "result": result_id,
        },
    )


def reusable_completed_run(
    session: Session, tenant: int, kind: AnchorType, anchor_id: int
) -> AgentRun | None:
    state = target_state(session, tenant, kind, anchor_id)
    if not state or not state["current_run_id"]:
        return None
    run = repository.find_root_cross_judgment_run(session, tenant, state["current_run_id"])
    if run is None or run.status != "COMPLETED":
        return None
    if read_currentness(session, run, state=state) == "CURRENT":
        return run
    marker = intake_metadata(session, tenant)
    if state["anchor_identity"] != anchor_identity(session, tenant, kind, anchor_id):
        return None
    from domain.agent_execution.candidates import AnchorCardMissingError

    try:
        identity, _ = complete_input_identity(session, run)
    except (AnchorCardMissingError, NotFoundError):
        return None
    if identity != state["input_identity"]:
        return None
    if current_revision(session, tenant, lock=True) != marker["revision"]:
        return None
    session.execute(
        text("""UPDATE match_target_state SET desired_revision=GREATEST(desired_revision,:revision),
        verified_revision=:revision,
        verified_day=:day,config_identity=:config,verified_at=now(),due_at=NULL
        WHERE brokerage_id=:tenant AND anchor_type=:kind AND anchor_id=:id"""),
        {
            "revision": marker["revision"],
            "day": marker["day"],
            "config": marker["configuration"],
            "tenant": tenant,
            "kind": kind.value,
            "id": anchor_id,
        },
    )
    return run


def read_currentness_many(session: Session, runs: list[AgentRun]) -> dict[int, str]:
    output: dict[int, str] = {}
    for tenant in {run.brokerage_id for run in runs}:
        revision = current_revision(session, tenant)
        config = configuration_identity(session, tenant)
        ids = [run.id for run in runs if run.brokerage_id == tenant and run.id]
        states = (
            session.execute(
                text("""SELECT * FROM match_target_state
            WHERE brokerage_id=:tenant AND current_run_id=ANY(:ids)"""),
                {"tenant": tenant, "ids": ids},
            )
            .mappings()
            .all()
        )
        by_run = {row["current_run_id"]: dict(row) for row in states}
        for run in runs:
            if run.brokerage_id != tenant:
                continue
            output[run.id or 0] = read_currentness(
                session,
                run,
                state=by_run.get(run.id, {}),
                revision=revision,
                config_identity=config,
            )
    return output
