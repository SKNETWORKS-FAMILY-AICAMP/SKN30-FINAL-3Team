"""Durable conditional precomputation on the existing PostgreSQL Worker queue."""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from sqlalchemy import text
from sqlmodel import Session

from core.errors import NotFoundError, ValidationError
from domain.agent_execution import freshness, service
from domain.agent_execution.models import AnchorType

logger = structlog.get_logger()
AUTO_CHANGE_TRIGGER_TYPE = "AUTO_CHANGE"


def expand_changes(session: Session, *, debounce_seconds: int, batch_size: int) -> int:
    """Consume coalesced events atomically; no model or queue command in this transaction.

    Conservative tenant fan-out also detects newly eligible opposite candidates. The semantic
    check at intake avoids inference for anchors whose actual selected inputs are unchanged.
    """
    rows = (
        session.execute(
            text("""SELECT brokerage_id, revision, changed_at
        FROM match_change_outbox
        WHERE changed_at + make_interval(secs => :delay) <= now()
        ORDER BY changed_at LIMIT :batch FOR UPDATE SKIP LOCKED"""),
            {"delay": debounce_seconds, "batch": batch_size},
        )
        .mappings()
        .all()
    )
    for row in rows:
        session.execute(
            text("""INSERT INTO match_target_state
            (brokerage_id,anchor_type,anchor_id,desired_revision,due_at)
            SELECT brokerage_id, 'LISTING', id, :revision, now()
            FROM property_listing WHERE brokerage_id=:tenant AND NOT is_deleted
            UNION ALL SELECT brokerage_id, 'REQUIREMENT', id, :revision, now()
            FROM property_requirement WHERE brokerage_id=:tenant AND NOT is_deleted
            ON CONFLICT (brokerage_id,anchor_type,anchor_id) DO UPDATE SET
                desired_revision=EXCLUDED.desired_revision, due_at=EXCLUDED.due_at"""),
            {"tenant": row["brokerage_id"], "revision": row["revision"]},
        )
        session.execute(
            text("DELETE FROM match_change_outbox WHERE brokerage_id=:tenant"),
            {"tenant": row["brokerage_id"]},
        )
    session.commit()
    return len(rows)


def schedule_refreshes(session: Session, *, batch_size: int) -> int:
    """Configuration/UTC expiration and bounded bootstrap; only called periodically."""
    tenants = (
        session.execute(
            text("""SELECT DISTINCT brokerage_id FROM match_target_state
        WHERE due_at IS NULL ORDER BY brokerage_id"""),
            {"batch": batch_size},
        )
        .scalars()
        .all()
    )
    scheduled = 0
    for tenant in tenants:
        config = freshness.configuration_identity(session, tenant)
        if scheduled >= batch_size:
            break
        ids = session.execute(
            text("""SELECT 1 FROM match_target_state s
            WHERE s.brokerage_id=:tenant AND s.due_at IS NULL
              AND (s.verified_day < :day OR s.config_identity IS DISTINCT FROM :config)
              AND NOT EXISTS (SELECT 1 FROM agent_run r WHERE r.brokerage_id=s.brokerage_id
                AND r.parent_run_id IS NULL AND r.run_type='CROSS_JUDGMENT'
                AND COALESCE(r.target_listing_id,r.target_requirement_id)=s.anchor_id
                AND (r.target_listing_id IS NOT NULL)=(s.anchor_type='LISTING')
                AND r.status IN ('QUEUED','RUNNING','ANCHOR_READY','CANDIDATES_READY',
                    'CANDIDATE_CARDS_READY','JUDGING')
                OR (r.brokerage_id=s.brokerage_id
                    AND COALESCE(r.target_listing_id,r.target_requirement_id)=s.anchor_id
                    AND (r.target_listing_id IS NOT NULL)=(s.anchor_type='LISTING')
                    AND r.status='FAILED_TERMINAL'
                    AND r.redacted_input_snapshot->'automation'->>'day'=CAST(:day AS TEXT)
                    AND r.redacted_input_snapshot->'automation'->>'configuration'=:config))
            LIMIT 1"""),
            {"tenant": tenant, "day": datetime.now(UTC).date(), "config": config},
        ).first()
        if ids is None:
            continue
        session.execute(
            text("""INSERT INTO match_change_outbox
            (brokerage_id,revision,source_table)
            VALUES (:tenant,:revision,'CONFIGURATION_OR_DATE')
            ON CONFLICT (brokerage_id) DO NOTHING"""),
            {"tenant": tenant, "revision": freshness.current_revision(session, tenant)},
        )
        scheduled += 1
    session.commit()
    return scheduled


def enqueue_changed_targets(session: Session, *, batch_size: int) -> int:
    queued = 0
    for _ in range(batch_size):
        row = (
            session.execute(
                text("""SELECT * FROM match_target_state
            WHERE due_at <= now() ORDER BY due_at,brokerage_id,anchor_type,anchor_id
            LIMIT 1 FOR UPDATE SKIP LOCKED""")
            )
            .mappings()
            .first()
        )
        if row is None:
            session.commit()
            break
        tenant, kind, anchor_id = (
            row["brokerage_id"],
            AnchorType(row["anchor_type"]),
            row["anchor_id"],
        )
        desired = row["desired_revision"]
        actor = session.execute(
            text("""SELECT id FROM app_user
            WHERE brokerage_id=:tenant AND is_active ORDER BY id LIMIT 1"""),
            {"tenant": tenant},
        ).scalar_one_or_none()
        # Release the projection row before intake's advisory lock; completion uses the reverse
        # order. Repeated consumers are harmless because intake itself is DB-idempotent.
        session.commit()
        if actor is not None:
            try:
                service.queue_cross_judgment_run(
                    session, tenant, actor, kind, anchor_id, trigger_type=AUTO_CHANGE_TRIGGER_TYPE
                )
                queued += 1
            except (NotFoundError, ValidationError):
                session.rollback()
        session.execute(
            text("""UPDATE match_target_state SET due_at=NULL
            WHERE brokerage_id=:tenant AND anchor_type=:kind AND anchor_id=:id
              AND desired_revision=:revision"""),
            {"tenant": tenant, "kind": kind.value, "id": anchor_id, "revision": desired},
        )
        session.commit()
    return queued


def tick(
    session: Session, *, debounce_seconds: int = 3, batch_size: int = 20, sweep: bool = False
) -> int:
    try:
        if sweep:
            schedule_refreshes(session, batch_size=batch_size)
        events = expand_changes(session, debounce_seconds=debounce_seconds, batch_size=batch_size)
        queued = enqueue_changed_targets(session, batch_size=batch_size)
        if events or queued:
            logger.info("f3_automation_tick", expanded_events=events, ensured_targets=queued)
        return queued
    except Exception as error:
        session.rollback()
        logger.warning("f3_automation_retry", error_type=type(error).__name__)
        return 0  # Durable outbox/projection remains available on the next polling cycle.
