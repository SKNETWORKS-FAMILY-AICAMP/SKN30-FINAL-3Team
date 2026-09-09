"""Conditional F3 automation against PostgreSQL, with only model I/O replaced.

Tests commit real transactions so source invalidation, independent readers, Worker
restart, and late publication are exercised across actual database boundaries.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from brokerage_ai.f3 import InputPrivacyMode
from brokerage_judgment_fixtures import FakeCardGenerator, FakeJudgmentGenerator, Fixture
from sqlalchemy import text
from sqlmodel import Session, create_engine

from domain.agent_execution import automation, freshness, pipeline, service
from domain.agent_execution.anchor_card import GenerationBinding
from domain.agent_execution.models import AnchorType
from f3_worker_reliability import execution_slot

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DB_URL"), reason="TEST_DB_URL is required for PostgreSQL integration tests"
)


@contextmanager
def automation_fixture() -> Iterator[tuple[Session, Fixture]]:
    engine = create_engine(os.environ["TEST_DB_URL"])
    fixture = None
    try:
        with Session(engine) as session:
            fixture = Fixture(session, name="자동 판정 합성 검증")
            yield session, fixture
    finally:
        if fixture is not None:
            with Session(engine) as cleanup:
                for table in (
                    "match_target_state",
                    "match_candidate_evidence",
                    "match_candidate_evaluation",
                    "match_evaluation",
                    "negotiation_position_evidence",
                    "negotiation_position_price",
                    "negotiation_position_analysis",
                    "agent_capability_call",
                    "agent_run",
                    "client_interaction",
                    "property_listing",
                    "property_unit_party_relation",
                    "property_requirement_complex",
                    "property_requirement",
                    "party_contact",
                    "party",
                    "property_unit",
                    "property_complex",
                    "ai_model_config",
                    "app_user",
                    # Ledger DELETE triggers run during cleanup; remove their events last.
                    "match_change_outbox",
                    "match_source_revision",
                ):
                    cleanup.execute(
                        text(f"DELETE FROM {table} WHERE brokerage_id=:tenant"),
                        {"tenant": fixture.brokerage_id},
                    )
                cleanup.execute(
                    text("DELETE FROM brokerage WHERE id=:tenant"),
                    {"tenant": fixture.brokerage_id},
                )
                cleanup.commit()
        engine.dispose()


def listing_run(session: Session, fixture: Fixture):
    return service.queue_cross_judgment_run(
        session, fixture.brokerage_id, fixture.user_id, AnchorType.LISTING, fixture.listing_id
    )


def drive(session: Session, fixture: Fixture, run, generator: FakeJudgmentGenerator):
    bindings = pipeline.ExecutionBindings(
        card=GenerationBinding(
            generator=FakeCardGenerator(),
            model_config_id=fixture.card_config_id,
            input_privacy_mode=InputPrivacyMode.SYNTHETIC_PROTOTYPE,
        ),
        judgment=fixture.judgment_binding(generator),
    )
    with asyncio.Runner() as runner:
        return pipeline.drive_run(
            session, run, run.lease_owner, lambda _: bindings, runner.get_loop()
        )


def complete_listing(session: Session, fixture: Fixture, generator: FakeJudgmentGenerator):
    requested = listing_run(session, fixture)
    assert requested.id is not None
    claimed = service.claim_next_run(session, "automation-worker")
    assert claimed is not None and claimed.id == requested.id
    assert drive(session, fixture, claimed, generator) is pipeline.StepOutcome.COMPLETED
    return service.require_cross_judgment_run(session, fixture.brokerage_id, requested.id)


def tenant_count(session: Session, fixture: Fixture, table: str) -> int:
    return session.execute(
        text(f"SELECT count(*) FROM {table} WHERE brokerage_id=:tenant"),
        {"tenant": fixture.brokerage_id},
    ).scalar_one()


def test_non_input_edits_do_not_invalidate_or_publish_an_event() -> None:
    with automation_fixture() as (session, fixture):
        revision = freshness.current_revision(session, fixture.brokerage_id)
        session.execute(
            text("DELETE FROM match_change_outbox WHERE brokerage_id=:tenant"),
            {"tenant": fixture.brokerage_id},
        )
        session.commit()
        session.execute(
            text("""UPDATE property_listing SET sale_price=sale_price,
                memo='합성 내부 배정 메모', assigned_user_id=:actor,
                row_version=row_version+1, updated_at=now() WHERE id=:listing"""),
            {"actor": fixture.user_id, "listing": fixture.listing_id},
        )
        session.commit()
        assert freshness.current_revision(session, fixture.brokerage_id) == revision
        assert tenant_count(session, fixture, "match_change_outbox") == 0


def test_ledger_revision_and_outbox_rollback_together() -> None:
    with automation_fixture() as (session, fixture):
        revision = freshness.current_revision(session, fixture.brokerage_id)
        session.execute(
            text("DELETE FROM match_change_outbox WHERE brokerage_id=:tenant"),
            {"tenant": fixture.brokerage_id},
        )
        session.commit()
        session.execute(
            text("UPDATE property_listing SET sale_price=2800000000 WHERE id=:id"),
            {"id": fixture.listing_id},
        )
        assert freshness.current_revision(session, fixture.brokerage_id) == revision + 1
        assert tenant_count(session, fixture, "match_change_outbox") == 1
        session.rollback()
        with Session(session.get_bind()) as reader:
            assert freshness.current_revision(reader, fixture.brokerage_id) == revision
            assert tenant_count(reader, fixture, "match_change_outbox") == 0
            assert (
                reader.execute(
                    text("SELECT sale_price FROM property_listing WHERE id=:id"),
                    {"id": fixture.listing_id},
                ).scalar_one()
                == 2_880_000_000
            )


def test_repeated_price_changes_coalesce_and_wait_for_debounce() -> None:
    with automation_fixture() as (session, fixture):
        before = freshness.current_revision(session, fixture.brokerage_id)
        for price in (2_870_000_000, 2_860_000_000, 2_850_000_000):
            session.execute(
                text("UPDATE property_listing SET sale_price=:price WHERE id=:id"),
                {"price": price, "id": fixture.listing_id},
            )
            session.commit()
        row = (
            session.execute(
                text("SELECT * FROM match_change_outbox WHERE brokerage_id=:tenant"),
                {"tenant": fixture.brokerage_id},
            )
            .mappings()
            .one()
        )
        assert row["revision"] == before + 3
        assert set(row) == {"brokerage_id", "revision", "source_table", "source_id", "changed_at"}
        assert automation.expand_changes(session, debounce_seconds=60, batch_size=20) == 0
        assert automation.expand_changes(session, debounce_seconds=0, batch_size=20) == 1
        assert tenant_count(session, fixture, "match_change_outbox") == 0
        state = freshness.target_state(
            session, fixture.brokerage_id, AnchorType.LISTING, fixture.listing_id
        )
        assert state is not None and state["desired_revision"] == before + 3


def test_new_opposite_candidate_invalidates_existing_anchors_without_prior_match() -> None:
    with automation_fixture() as (session, fixture):
        automation.expand_changes(session, debounce_seconds=0, batch_size=20)
        previous = freshness.current_revision(session, fixture.brokerage_id)
        requirement_id = fixture.requirement(budget=3_000_000_000, party_name="합성 신규 손님")
        assert tenant_count(session, fixture, "match_evaluation") == 0
        assert automation.expand_changes(session, debounce_seconds=0, batch_size=20) == 1
        states = session.execute(
            text(
                "SELECT anchor_type, anchor_id, desired_revision FROM match_target_state"
                " WHERE brokerage_id=:tenant"
            ),
            {"tenant": fixture.brokerage_id},
        ).all()
        assert {(row.anchor_type, row.anchor_id) for row in states} == {
            ("LISTING", fixture.listing_id),
            ("REQUIREMENT", requirement_id),
        }
        assert all(row.desired_revision > previous for row in states)


def test_auto_tick_queues_full_workflow_once_and_skips_closed_targets() -> None:
    with automation_fixture() as (session, fixture):
        requirement_id = fixture.requirement(budget=3_000_000_000, party_name="합성 종료 손님")
        session.execute(
            text("UPDATE property_requirement SET status='종료' WHERE id=:id"),
            {"id": requirement_id},
        )
        session.commit()
        assert automation.tick(session, debounce_seconds=0, batch_size=20) == 1
        rows = session.execute(
            text("SELECT id,status,trigger_type FROM agent_run WHERE brokerage_id=:tenant"),
            {"tenant": fixture.brokerage_id},
        ).all()
        assert len(rows) == 1 and rows[0].status == "QUEUED"
        assert rows[0].trigger_type == "AUTO_CHANGE"
        assert automation.tick(session, debounce_seconds=0, batch_size=20) == 0
        assert tenant_count(session, fixture, "agent_run") == 1
        claimed = service.claim_next_run(session, "automatic-completion")
        assert claimed is not None and claimed.id == rows[0].id
        generator = FakeJudgmentGenerator()
        assert drive(session, fixture, claimed, generator) is pipeline.StepOutcome.COMPLETED
        assert generator.calls == 0  # No eligible candidates: skip final AI judgment.


def test_completed_result_is_reused_without_another_judgment() -> None:
    with automation_fixture() as (session, fixture):
        fixture.requirement(budget=3_000_000_000, party_name="합성 유효 손님")
        generator = FakeJudgmentGenerator()
        completed = complete_listing(session, fixture, generator)
        assert generator.calls == 1
        assert freshness.read_currentness(session, completed) == "CURRENT"
        before = tenant_count(session, fixture, "agent_run")
        for _ in range(5):
            assert listing_run(session, fixture).id == completed.id
        assert generator.calls == 1
        assert tenant_count(session, fixture, "agent_run") == before


def test_same_final_ai_input_reuses_persisted_judgment_when_projection_is_rebuilt() -> None:
    with automation_fixture() as (session, fixture):
        fixture.requirement(budget=3_000_000_000, party_name="합성 판정 캐시 손님")
        first_generator = FakeJudgmentGenerator()
        first = complete_listing(session, fixture, first_generator)
        assert first_generator.calls == 1
        # Projection recovery may need a new run while immutable card/result inputs survive.
        session.execute(
            text("DELETE FROM match_target_state WHERE brokerage_id=:tenant"),
            {"tenant": fixture.brokerage_id},
        )
        session.commit()
        repeated_generator = FakeJudgmentGenerator()
        rebuilt = complete_listing(session, fixture, repeated_generator)
        assert rebuilt.id != first.id
        assert repeated_generator.calls == 0
        assert freshness.read_currentness(session, rebuilt) == "CURRENT"
        assert tenant_count(session, fixture, "match_candidate_evaluation") == 2


def test_unrelated_change_revalidates_identity_without_reordering_result() -> None:
    with automation_fixture() as (session, fixture):
        generator = FakeJudgmentGenerator()
        completed = complete_listing(session, fixture, generator)
        before = freshness.target_state(
            session, fixture.brokerage_id, AnchorType.LISTING, fixture.listing_id
        )
        fixture.party("판정과 무관한 합성 인물")
        assert freshness.read_currentness(session, completed) == "STALE"
        assert listing_run(session, fixture).id == completed.id
        after = freshness.target_state(
            session, fixture.brokerage_id, AnchorType.LISTING, fixture.listing_id
        )
        assert before is not None and after is not None
        assert after["verified_revision"] > before["verified_revision"]
        assert after["meaningful_changed_at"] == before["meaningful_changed_at"]
        assert freshness.read_currentness(session, completed) == "CURRENT"
        assert generator.calls == 0


def test_new_candidate_makes_success_stale_and_requires_new_run() -> None:
    with automation_fixture() as (session, fixture):
        completed = complete_listing(session, fixture, FakeJudgmentGenerator())
        fixture.requirement(budget=3_000_000_000, party_name="이후 등록된 합성 손님")
        assert freshness.read_currentness(session, completed) == "STALE"
        replacement = listing_run(session, fixture)
        assert replacement.id != completed.id and replacement.status == "QUEUED"
        assert tenant_count(session, fixture, "match_evaluation") == 1


def test_late_judgment_after_source_change_is_not_published() -> None:
    with automation_fixture() as (session, fixture):
        fixture.requirement(budget=3_000_000_000, party_name="합성 대기 손님")
        requested = listing_run(session, fixture)
        claimed = service.claim_next_run(session, "late-worker")
        assert claimed is not None and claimed.id == requested.id

        class ChangedWhileInferring(FakeJudgmentGenerator):
            async def judge_candidates(self, request):
                with Session(session.get_bind()) as editor:
                    editor.execute(
                        text("UPDATE property_listing SET sale_price=2700000000 WHERE id=:id"),
                        {"id": fixture.listing_id},
                    )
                    editor.commit()
                return await super().judge_candidates(request)

        generator = ChangedWhileInferring()
        assert drive(session, fixture, claimed, generator) is pipeline.StepOutcome.SUPERSEDED
        assert generator.calls == 1
        # Candidate selection has a persisted header, but no judgment may be published.
        assert tenant_count(session, fixture, "match_candidate_evaluation") == 0
        assert requested.id is not None
        assert fixture.stored_run(requested.id)["status"] == "SUPERSEDED"
        state = freshness.target_state(
            session, fixture.brokerage_id, AnchorType.LISTING, fixture.listing_id
        )
        assert state is None or state["current_result_id"] is None


def test_worker_restart_reclaims_expired_lease_and_completes_same_run() -> None:
    with automation_fixture() as (session, fixture):
        requested = listing_run(session, fixture)
        first = service.claim_next_run(session, "stopped-worker")
        assert first is not None and first.id == requested.id
        session.execute(
            text("UPDATE agent_run SET lease_expires_at=now()-interval '1 second' WHERE id=:id"),
            {"id": first.id},
        )
        session.commit()
        with Session(session.get_bind()) as restarted:
            recovered = service.claim_next_run(restarted, "restarted-worker")
            assert recovered is not None and recovered.id == requested.id
            assert recovered.attempt_count == 2
            assert recovered.lease_owner == "restarted-worker"
            assert drive(restarted, fixture, recovered, FakeJudgmentGenerator()) is (
                pipeline.StepOutcome.COMPLETED
            )


def test_non_input_edit_during_judgment_preserves_the_result() -> None:
    with automation_fixture() as (session, fixture):
        fixture.requirement(budget=3_000_000_000, party_name="합성 비입력 변경 손님")
        requested = listing_run(session, fixture)
        claimed = service.claim_next_run(session, "operational-edit-worker")
        assert claimed is not None and claimed.id == requested.id

        class OperationalEditWhileInferring(FakeJudgmentGenerator):
            async def judge_candidates(self, request):
                with Session(session.get_bind()) as editor:
                    editor.execute(
                        text("""UPDATE property_listing SET memo='합성 업무 배정',
                            assigned_user_id=:actor, row_version=row_version+1 WHERE id=:id"""),
                        {"id": fixture.listing_id, "actor": fixture.user_id},
                    )
                    editor.commit()
                return await super().judge_candidates(request)

        generator = OperationalEditWhileInferring()
        assert drive(session, fixture, claimed, generator) is pipeline.StepOutcome.COMPLETED
        assert requested.id is not None
        completed = service.require_cross_judgment_run(session, fixture.brokerage_id, requested.id)
        assert freshness.read_currentness(session, completed) == "CURRENT"
        assert generator.calls == 1


def test_execution_slot_excludes_independent_workers_and_releases_after_failure() -> None:
    first_engine = create_engine(os.environ["TEST_DB_URL"])
    second_engine = create_engine(os.environ["TEST_DB_URL"])
    try:
        with (
            pytest.raises(RuntimeError, match="synthetic worker failure"),
            execution_slot(first_engine) as first,
        ):
            assert first
            with execution_slot(second_engine) as second:
                assert not second
            raise RuntimeError("synthetic worker failure")
        with execution_slot(second_engine) as recovered:
            assert recovered
    finally:
        first_engine.dispose()
        second_engine.dispose()


def test_expired_day_schedules_durable_revalidation_without_starting_inference() -> None:
    with automation_fixture() as (session, fixture):
        completed = complete_listing(session, fixture, FakeJudgmentGenerator())
        session.execute(
            text("DELETE FROM match_change_outbox WHERE brokerage_id=:tenant"),
            {"tenant": fixture.brokerage_id},
        )
        session.execute(
            text(
                "UPDATE match_target_state SET verified_day=CURRENT_DATE-1 "
                "WHERE brokerage_id=:tenant"
            ),
            {"tenant": fixture.brokerage_id},
        )
        session.commit()
        assert freshness.read_currentness(session, completed) == "STALE"
        assert automation.schedule_refreshes(session, batch_size=20) == 1
        assert tenant_count(session, fixture, "match_change_outbox") == 1
        assert completed.id is not None
        assert fixture.stored_run(completed.id)["status"] == "COMPLETED"


def test_coalesced_outbox_keeps_other_tenant_beyond_batch_and_later_revision():
    with (
        automation_fixture() as (owner_session, first),
        automation_fixture() as (_, second),
        Session(owner_session.get_bind()) as session,
    ):
        tenants = [first.brokerage_id, second.brokerage_id]
        for price in (2800000000, 2810000000, 2820000000):
            session.execute(
                text("UPDATE property_listing SET sale_price=:price WHERE id=:id"),
                {"price": price, "id": first.listing_id},
            )
        session.execute(
            text(
                "UPDATE match_change_outbox SET changed_at='2000-01-01T00:00:00Z' "
                "WHERE brokerage_id=ANY(:ids)"
            ),
            {"ids": tenants},
        )
        session.commit()

        def pending():
            return set(
                session.execute(
                    text(
                        "SELECT brokerage_id FROM match_change_outbox WHERE brokerage_id=ANY(:ids)"
                    ),
                    {"ids": tenants},
                ).scalars()
            )

        assert pending() == set(tenants)
        # 같은 사무소의 여러 변경은 PK 행 하나에 병합되며 배치 밖 사무소는 남는다.
        assert automation.expand_changes(session, debounce_seconds=0, batch_size=1) == 1
        remaining = pending()
        assert len(remaining) == 1
        assert automation.expand_changes(session, debounce_seconds=0, batch_size=1) == 1
        assert pending() == set()
        old_revision = freshness.current_revision(session, first.brokerage_id)
        session.execute(
            text("UPDATE property_listing SET sale_price=2830000000 WHERE id=:id"),
            {"id": first.listing_id},
        )
        session.execute(
            text(
                "UPDATE match_change_outbox SET changed_at='2000-01-01T00:00:00Z' "
                "WHERE brokerage_id=:b"
            ),
            {"b": first.brokerage_id},
        )
        session.commit()
        assert pending() == {first.brokerage_id}
        assert automation.expand_changes(session, debounce_seconds=0, batch_size=1) == 1
        assert pending() == set()
        assert (
            session.execute(
                text(
                    "SELECT desired_revision FROM match_target_state WHERE brokerage_id=:b "
                    "AND anchor_type='LISTING' AND anchor_id=:id"
                ),
                {"b": first.brokerage_id, "id": first.listing_id},
            ).scalar_one()
            == old_revision + 1
        )
