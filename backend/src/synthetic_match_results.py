"""Prepare synthetic matching results through the real persistence and execution pipeline."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TypedDict

from sqlalchemy import Engine, text
from sqlmodel import Session, col, select

from core.errors import NotFoundError
from domain.agent_execution import freshness, pipeline, repository, service
from domain.agent_execution.anchor_card import GenerationBinding
from domain.agent_execution.judgment import JudgmentBinding
from domain.agent_execution.models import (
    BROKERAGE_JUDGMENT_CAPABILITY,
    POSITION_CARD_CAPABILITY,
    AgentRun,
    AnchorType,
)
from f3_worker_reliability import execution_slot, renew_lease
from synthetic_match_generators import (
    SYNTHETIC_MATCH_FIXTURE,
    SyntheticBrokerageJudgments,
    SyntheticPositionCards,
)
from synthetic_seed import F3_SYNTHETIC_BROKERAGE_NAME, SyntheticSeedError


class _SeedCounts(TypedDict):
    total: int
    eligible: int
    completed: int
    reused: int
    ineligible: int
    insufficient_input: int


@dataclass(frozen=True)
class MatchResultSeedSummary:
    total: int
    eligible: int
    completed: int
    reused: int
    ineligible: int
    insufficient_input: int
    candidate_count: int
    judged_count: int
    unjudged_count: int
    no_candidate_results: int
    grades: dict[str, int] = field(default_factory=dict)
    status: str = "COMPLETED"
    model_inference: bool = False


def _require_scope(session: Session, brokerage_id: int, user_id: int) -> None:
    matched = session.execute(
        text("""SELECT 1 FROM brokerage b JOIN app_user u
        ON u.brokerage_id=b.id WHERE b.id=:tenant AND b.name=:name
          AND u.id=:user AND u.is_active AND u.login_id='f3_synthetic_dev'"""),
        {"tenant": brokerage_id, "name": F3_SYNTHETIC_BROKERAGE_NAME, "user": user_id},
    ).scalar()
    if matched != 1:
        raise SyntheticSeedError(
            "matching seed requires the dedicated synthetic brokerage and user"
        )


def _bindings(session: Session, brokerage_id: int) -> pipeline.ExecutionBindings:
    configs = {
        capability: repository.find_active_model_config(session, brokerage_id, capability)
        for capability in (POSITION_CARD_CAPABILITY, BROKERAGE_JUDGMENT_CAPABILITY)
    }
    if any(config is None for config in configs.values()):
        raise SyntheticSeedError("matching seed requires both selected F3 model configurations")
    from brokerage_ai.f3 import InputPrivacyMode

    card = configs[POSITION_CARD_CAPABILITY]
    judgment = configs[BROKERAGE_JUDGMENT_CAPABILITY]
    assert card is not None and judgment is not None
    return pipeline.ExecutionBindings(
        card=GenerationBinding(
            generator=SyntheticPositionCards(),
            model_config_id=card.id or 0,
            input_privacy_mode=InputPrivacyMode.SYNTHETIC_PROTOTYPE,
        ),
        judgment=JudgmentBinding(
            generator=SyntheticBrokerageJudgments(),
            model_config_id=judgment.id or 0,
            input_privacy_mode=InputPrivacyMode.SYNTHETIC_PROTOTYPE,
        ),
    )


def _claim_only_seed_run(
    session: Session, brokerage_id: int, run_id: int, worker_id: str
) -> AgentRun:
    run = (
        session.execute(
            select(AgentRun)
            .where(
                col(AgentRun.id) == run_id,
                col(AgentRun.brokerage_id) == brokerage_id,
                col(AgentRun.run_type) == "CROSS_JUDGMENT",
                col(AgentRun.parent_run_id).is_(None),
            )
            .with_for_update()
        )
        .scalars()
        .one()
    )
    if run.status != "QUEUED" or run.lease_owner is not None:
        session.rollback()
        raise SyntheticSeedError("matching seed requires its target run to be unclaimed and queued")
    # Provenance is attached before any work, independently of output snapshot stage replacement.
    run.redacted_input_snapshot = {
        **run.redacted_input_snapshot,
        "synthetic_fixture": dict(SYNTHETIC_MATCH_FIXTURE),
    }
    session.add(run)
    session.flush()
    claimed = repository.mark_run_claimed(session, run, worker_id, service.LEASE_DURATION_SECONDS)
    session.commit()
    return claimed


def _ensure_projection(
    session: Session, tenant: int, kind: AnchorType, anchor_id: int, revision: int
) -> None:
    session.execute(
        text("""INSERT INTO match_target_state
        (brokerage_id,anchor_type,anchor_id,desired_revision)
        VALUES (:tenant,:kind,:id,:revision)
        ON CONFLICT (brokerage_id,anchor_type,anchor_id) DO UPDATE
        SET desired_revision=EXCLUDED.desired_revision,due_at=NULL"""),
        {"tenant": tenant, "kind": kind.value, "id": anchor_id, "revision": revision},
    )
    session.commit()


def _summarize(
    session: Session, tenant: int, counts: _SeedCounts, run_ids: list[int]
) -> MatchResultSeedSummary:
    headers = (
        session.execute(
            text("""SELECT m.candidate_count,
        jsonb_array_length(COALESCE(m.candidate_selection_snapshot->'candidates',
                                   '[]'::jsonb)) AS total
        FROM match_target_state s JOIN match_evaluation m
          ON m.brokerage_id=s.brokerage_id AND m.id=s.current_result_id
        WHERE s.brokerage_id=:tenant AND s.current_run_id=ANY(:runs)"""),
            {"tenant": tenant, "runs": run_ids},
        )
        .mappings()
        .all()
    )
    rows = (
        session.execute(
            text("""SELECT c.match_grade,count(*) AS total
        FROM match_target_state s JOIN match_candidate_evaluation c
          ON c.brokerage_id=s.brokerage_id AND c.match_evaluation_id=s.current_result_id
        WHERE s.brokerage_id=:tenant AND s.current_run_id=ANY(:runs)
        GROUP BY c.match_grade"""),
            {"tenant": tenant, "runs": run_ids},
        )
        .mappings()
        .all()
    )
    return MatchResultSeedSummary(
        **counts,
        candidate_count=sum(row["total"] for row in headers),
        judged_count=sum(row["candidate_count"] for row in headers),
        unjudged_count=sum(row["total"] - row["candidate_count"] for row in headers),
        no_candidate_results=sum(row["total"] == 0 for row in headers),
        grades={row["match_grade"]: row["total"] for row in rows},
    )


def seed_match_results(engine: Engine, brokerage_id: int, user_id: int) -> MatchResultSeedSummary:
    """Generate eligible targets only; preserve selected real model configuration and other tenants.

    The caller owns local/dev confirmation and ledger seeding. No environment, provider client,
    test fixture, or broad queue claim is used. A source change aborts without clearing new events.
    """
    with execution_slot(engine) as acquired:
        if not acquired:
            raise SyntheticSeedError(
                "stop the active Worker before preparing matching seed results"
            )
        with Session(engine) as session, asyncio.Runner() as runner:
            _require_scope(session, brokerage_id, user_id)
            bindings = _bindings(session, brokerage_id)
            marker = freshness.intake_metadata(session, brokerage_id)
            source_revision = marker["revision"]
            assert isinstance(source_revision, int)
            targets = (
                session.execute(
                    text("""SELECT 'LISTING' AS kind,id FROM property_listing
                WHERE brokerage_id=:tenant AND NOT is_deleted
                UNION ALL SELECT 'REQUIREMENT',id FROM property_requirement
                WHERE brokerage_id=:tenant AND NOT is_deleted ORDER BY kind,id"""),
                    {"tenant": brokerage_id},
                )
                .mappings()
                .all()
            )
            counts: _SeedCounts = {
                "total": len(targets),
                "eligible": 0,
                "completed": 0,
                "reused": 0,
                "ineligible": 0,
                "insufficient_input": 0,
            }
            run_ids: list[int] = []
            worker_id = f"synthetic-match-seed-{brokerage_id}"
            session.commit()
            for target in targets:
                kind, anchor_id = AnchorType(target["kind"]), target["id"]
                try:
                    status, _reason = freshness.eligibility(session, brokerage_id, kind, anchor_id)
                except NotFoundError:
                    status = "INELIGIBLE"
                if status != "ELIGIBLE":
                    counts["ineligible" if status == "INELIGIBLE" else "insufficient_input"] += 1
                    _ensure_projection(session, brokerage_id, kind, anchor_id, source_revision)
                    continue
                counts["eligible"] += 1
                requested = service.queue_cross_judgment_run(
                    session, brokerage_id, user_id, kind, anchor_id, trigger_type="SYNTHETIC_SEED"
                )
                if requested.status == "COMPLETED":
                    counts["reused"] += 1
                    run_ids.append(requested.id or 0)
                    continue
                run = _claim_only_seed_run(session, brokerage_id, requested.id or 0, worker_id)
                with renew_lease(engine, run, worker_id):
                    outcome = pipeline.drive_run(
                        session, run, worker_id, bindings, runner.get_loop()
                    )
                if outcome is not pipeline.StepOutcome.COMPLETED:
                    raise SyntheticSeedError(
                        f"matching seed execution did not complete: {outcome.value}"
                    )
                session.refresh(run)
                run.redacted_output_snapshot = {
                    **run.redacted_output_snapshot,
                    "synthetic_fixture": dict(SYNTHETIC_MATCH_FIXTURE),
                }
                session.add(run)
                session.commit()
                if freshness.read_currentness(session, run) != "CURRENT":
                    raise SyntheticSeedError("matching seed did not publish a current result")
                counts["completed"] += 1
                run_ids.append(run.id or 0)
            if freshness.intake_metadata(session, brokerage_id) != marker:
                raise SyntheticSeedError(
                    "synthetic ledger changed while preparing matching results"
                )
            revision = freshness.current_revision(session, brokerage_id, lock=True)
            if revision != source_revision:
                raise SyntheticSeedError(
                    "synthetic ledger changed before completing matching results"
                )
            session.execute(
                text(
                    "DELETE FROM match_change_outbox WHERE brokerage_id=:tenant "
                    "AND revision<=:revision"
                ),
                {"tenant": brokerage_id, "revision": revision},
            )
            session.execute(
                text(
                    "UPDATE match_target_state SET due_at=NULL WHERE brokerage_id=:tenant "
                    "AND desired_revision<=:revision"
                ),
                {"tenant": brokerage_id, "revision": revision},
            )
            session.commit()
            return _summarize(session, brokerage_id, counts, run_ids)
