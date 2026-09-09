"""Use the existing isolated TEST_DB_URL; never create or replace a developer database."""

from __future__ import annotations

import asyncio
import os
from contextlib import contextmanager

import pytest
from brokerage_ai.f3 import (
    POSITION_CARD_PROMPT_VERSION,
    POSITION_CARD_WORKFLOW_VERSION,
    InputPrivacyMode,
    PositionCardGeneratorVersions,
)
from sqlalchemy import text
from sqlmodel import create_engine
from test_f3_automation import automation_fixture

from domain.agent_execution import freshness, judgment_queries, pipeline, service
from domain.agent_execution.anchor_card import GenerationBinding
from domain.agent_execution.models import AnchorType
from synthetic_match_generators import SYNTHETIC_MATCH_FIXTURE, SyntheticPositionCards
from synthetic_match_results import seed_match_results
from synthetic_seed import (
    F3_SEED_DATA,
    F3_SEED_RESET,
    F3_SYNTHETIC_BROKERAGE_NAME,
    SyntheticSeedError,
    model_profile_path,
    read_psql_script,
)

pytestmark = pytest.mark.skipif(not os.getenv("TEST_DB_URL"), reason="TEST_DB_URL is required")


@contextmanager
def seed_fixture():
    with automation_fixture() as (session, fixture):
        session.execute(
            text("UPDATE brokerage SET name=:name WHERE id=:id"),
            {"name": F3_SYNTHETIC_BROKERAGE_NAME, "id": fixture.brokerage_id},
        )
        session.execute(
            text("UPDATE app_user SET login_id='f3_synthetic_dev' WHERE id=:id"),
            {"id": fixture.user_id},
        )
        session.commit()
        engine = create_engine(os.environ["TEST_DB_URL"])
        try:
            yield engine, session, fixture
        finally:
            engine.dispose()


def test_seed_generates_both_sides_and_real_coverage_without_model_configuration_changes():
    with seed_fixture() as (engine, session, fixture), automation_fixture() as (other, foreign):
        for index, budget in enumerate(
            (
                2900000000,
                2840000000,
                3000000000,
                2700000000,
                3100000000,
                2600000000,
                3200000000,
                1000000000,
            )
        ):
            requirement_id = fixture.requirement(budget=budget, party_name=f"합성 수요 {index}")
            if budget == 3200000000:
                session.execute(
                    text(
                        "UPDATE property_requirement SET desired_move_in_date="
                        "(now() AT TIME ZONE 'UTC')::date + 700 WHERE id=:id"
                    ),
                    {"id": requirement_id},
                )
        unsupported = fixture.requirement(budget=2900000000, party_name="합성 매도 수요")
        ended = fixture.requirement(budget=2900000000, party_name="합성 종료 수요")
        session.execute(
            text("UPDATE property_requirement SET demand_type='매도' WHERE id=:id"),
            {"id": unsupported},
        )
        session.execute(
            text("UPDATE property_requirement SET status='CLOSED' WHERE id=:id"), {"id": ended}
        )
        session.commit()
        foreign_run = service.queue_cross_judgment_run(
            other, foreign.brokerage_id, foreign.user_id, AnchorType.LISTING, foreign.listing_id
        )
        foreign_id = foreign_run.id
        before = [
            dict(row)
            for row in session.execute(
                text("SELECT * FROM ai_model_config WHERE brokerage_id=:tenant ORDER BY id"),
                {"tenant": fixture.brokerage_id},
            ).mappings()
        ]
        result = seed_match_results(engine, fixture.brokerage_id, fixture.user_id)
        assert result.status == "COMPLETED" and result.model_inference is False
        assert (result.total, result.eligible, result.completed, result.reused) == (11, 9, 9, 0)
        assert (result.ineligible, result.insufficient_input) == (1, 1)
        assert result.unjudged_count > 0 and result.no_candidate_results > 0
        assert set(result.grades) == {"STRONG", "WEAK", "REJECTED"}
        assert result.judged_count + result.unjudged_count == result.candidate_count
        after = [
            dict(row)
            for row in session.execute(
                text("SELECT * FROM ai_model_config WHERE brokerage_id=:tenant ORDER BY id"),
                {"tenant": fixture.brokerage_id},
            ).mappings()
        ]
        assert after == before
        runs = (
            session.execute(
                text(
                    "SELECT id,status,input_tokens,output_tokens,"
                    "redacted_input_snapshot,redacted_output_snapshot FROM agent_run "
                    "WHERE brokerage_id=:tenant"
                ),
                {"tenant": fixture.brokerage_id},
            )
            .mappings()
            .all()
        )
        assert len(runs) == 9 and {run["status"] for run in runs} == {"COMPLETED"}
        assert all(run["input_tokens"] == 0 and run["output_tokens"] == 0 for run in runs)
        assert all(
            run["redacted_input_snapshot"]["synthetic_fixture"] == SYNTHETIC_MATCH_FIXTURE
            and run["redacted_output_snapshot"]["synthetic_fixture"] == SYNTHETIC_MATCH_FIXTURE
            for run in runs
        )
        for run in runs:
            stored = service.require_cross_judgment_run(session, fixture.brokerage_id, run["id"])
            assert freshness.read_currentness(session, stored) == "CURRENT"
        for side in (AnchorType.LISTING, AnchorType.REQUIREMENT):
            page = judgment_queries.list_judgments(
                session, fixture.brokerage_id, side, filter_name="ALL", limit=50
            )
            completed_items = [item for item in page["items"] if item["result_id"]]
            assert completed_items
            assert all(
                item["is_synthetic_fixture"] and item["freshness"] == "CURRENT"
                for item in completed_items
            )
        assert (
            session.execute(
                text("SELECT count(*) FROM match_change_outbox WHERE brokerage_id=:tenant"),
                {"tenant": fixture.brokerage_id},
            ).scalar_one()
            == 0
        )
        assert (
            session.execute(
                text(
                    "SELECT count(*) FROM match_target_state "
                    "WHERE brokerage_id=:tenant AND due_at IS NOT NULL"
                ),
                {"tenant": fixture.brokerage_id},
            ).scalar_one()
            == 0
        )
        assert (
            other.execute(
                text("SELECT status FROM agent_run WHERE id=:id"), {"id": foreign_id}
            ).scalar_one()
            == "QUEUED"
        )
        assert (
            other.execute(
                text("SELECT count(*) FROM match_change_outbox WHERE brokerage_id=:t"),
                {"t": foreign.brokerage_id},
            ).scalar_one()
            == 1
        )


def test_repeated_seed_reuses_current_runs_and_preserves_fixture_markers():
    with seed_fixture() as (engine, session, fixture):
        fixture.requirement(budget=2900000000, party_name="합성 반복 검증")
        first = seed_match_results(engine, fixture.brokerage_id, fixture.user_id)
        before = session.execute(
            text(
                "SELECT id,meaningful_changed_at,current_result_id "
                "FROM (SELECT anchor_id AS id,meaningful_changed_at,current_result_id FROM "
                "match_target_state WHERE brokerage_id=:tenant) s ORDER BY id,current_result_id"
            ),
            {"tenant": fixture.brokerage_id},
        ).all()
        second = seed_match_results(engine, fixture.brokerage_id, fixture.user_id)
        assert first.completed == 2
        assert second.completed == 0 and second.reused == 2
        assert second.grades == first.grades
        after = session.execute(
            text(
                "SELECT id,meaningful_changed_at,current_result_id "
                "FROM (SELECT anchor_id AS id,meaningful_changed_at,current_result_id FROM "
                "match_target_state WHERE brokerage_id=:tenant) s ORDER BY id,current_result_id"
            ),
            {"tenant": fixture.brokerage_id},
        ).all()
        assert before == after
        assert (
            session.execute(
                text(
                    "SELECT count(*) FROM agent_run WHERE brokerage_id=:tenant "
                    "AND redacted_output_snapshot->'synthetic_fixture'->>'kind'="
                    "'DETERMINISTIC_MATCH_SEED'"
                ),
                {"tenant": fixture.brokerage_id},
            ).scalar_one()
            == 2
        )


def test_arbitrary_brokerage_cannot_receive_matching_seed():
    with automation_fixture() as (session, fixture):
        engine = create_engine(os.environ["TEST_DB_URL"])
        try:
            with pytest.raises(SyntheticSeedError, match="dedicated synthetic"):
                seed_match_results(engine, fixture.brokerage_id, fixture.user_id)
            assert (
                session.execute(
                    text("SELECT count(*) FROM agent_run WHERE brokerage_id=:tenant"),
                    {"tenant": fixture.brokerage_id},
                ).scalar_one()
                == 0
            )
        finally:
            engine.dispose()


def test_reusing_an_existing_current_result_does_not_relabel_its_provenance():
    with seed_fixture() as (engine, session, fixture):
        seed_match_results(engine, fixture.brokerage_id, fixture.user_id)
        session.execute(
            text(
                "UPDATE agent_run SET redacted_output_snapshot="
                "redacted_output_snapshot - 'synthetic_fixture', redacted_input_snapshot="
                "redacted_input_snapshot - 'synthetic_fixture' WHERE brokerage_id=:tenant"
            ),
            {"tenant": fixture.brokerage_id},
        )
        session.commit()
        repeated = seed_match_results(engine, fixture.brokerage_id, fixture.user_id)
        assert repeated.completed == 0 and repeated.reused == 1
        page = judgment_queries.list_judgments(
            session, fixture.brokerage_id, AnchorType.LISTING, filter_name="ALL"
        )
        assert page["items"][0]["freshness"] == "CURRENT"
        assert page["items"][0]["is_synthetic_fixture"] is False


def test_full_ledger_seed_has_current_results_and_the_three_planned_case_a_grades():
    """Use an existing TEST_DB_URL and only create/clean this test's synthetic tenant."""
    from synthetic_match_seed import complete_match_seed

    engine = create_engine(os.environ["TEST_DB_URL"])
    with engine.connect() as connection:
        if connection.execute(
            text("SELECT id FROM brokerage WHERE name=:name"),
            {"name": F3_SYNTHETIC_BROKERAGE_NAME},
        ).first():
            pytest.skip("full seed fixture requires no pre-existing synthetic tenant")
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.exec_driver_sql(
                read_psql_script(F3_SEED_DATA), execution_options={"no_parameters": True}
            )
            connection.exec_driver_sql(read_psql_script(model_profile_path("local-openai")))
        summary = complete_match_seed(engine, "local-openai")
        assert summary["verification_checks"] == 12
        generation = summary["generation"]
        assert isinstance(generation, dict)
        assert generation["completed"] == 81
        assert set(generation["grades"]) == {"STRONG", "WEAK", "REJECTED"}
        with engine.connect() as connection:
            rows = connection.execute(
                text("""SELECT r.custom_fields->>'seed_key',c.match_grade
                FROM property_listing l JOIN match_target_state s
                  ON s.brokerage_id=l.brokerage_id AND s.anchor_type='LISTING' AND s.anchor_id=l.id
                JOIN match_candidate_evaluation c ON c.match_evaluation_id=s.current_result_id
                  AND c.brokerage_id=s.brokerage_id
                JOIN negotiation_position_analysis p ON p.id=c.candidate_position_analysis_id
                  AND p.brokerage_id=c.brokerage_id
                JOIN property_requirement r ON r.id=p.requirement_id
                  AND r.brokerage_id=c.brokerage_id
                WHERE l.brokerage_id=:tenant AND l.custom_fields->>'seed_key'='L1'"""),
                {"tenant": summary["brokerage_id"]},
            ).all()
            assert {row[0]: row[1] for row in rows} == {
                "R1": "STRONG",
                "R2": "WEAK",
                "R3": "REJECTED",
            }
    finally:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.exec_driver_sql(read_psql_script(F3_SEED_RESET))
            connection.execute(
                text(
                    "DELETE FROM app_user WHERE brokerage_id IN "
                    "(SELECT id FROM brokerage WHERE name=:name)"
                ),
                {"name": F3_SYNTHETIC_BROKERAGE_NAME},
            )
            connection.execute(
                text("DELETE FROM brokerage WHERE name=:name"),
                {"name": F3_SYNTHETIC_BROKERAGE_NAME},
            )
        engine.dispose()


def test_production_version_generator_does_not_reuse_synthetic_seed_cards():
    from brokerage_judgment_fixtures import FakeJudgmentGenerator

    class ProductionVersionCards(SyntheticPositionCards):
        calls = 0

        @property
        def versions(self):
            return PositionCardGeneratorVersions(
                prompt_version=POSITION_CARD_PROMPT_VERSION,
                workflow_version=POSITION_CARD_WORKFLOW_VERSION,
            )

        async def generate_position_card(self, request):
            self.calls += 1
            return await super().generate_position_card(request)

    with seed_fixture() as (engine, session, fixture):
        fixture.requirement(budget=2900000000, party_name="합성 캐시 분리")
        seed_match_results(engine, fixture.brokerage_id, fixture.user_id)
        session.execute(
            text("DELETE FROM match_target_state WHERE brokerage_id=:tenant"),
            {"tenant": fixture.brokerage_id},
        )
        session.commit()
        requested = service.queue_cross_judgment_run(
            session, fixture.brokerage_id, fixture.user_id, AnchorType.LISTING, fixture.listing_id
        )
        run = service.claim_next_run(session, "production-version-test")
        assert run is not None and run.id == requested.id
        card_generator = ProductionVersionCards()
        judgments = FakeJudgmentGenerator()
        bindings = pipeline.ExecutionBindings(
            card=GenerationBinding(
                generator=card_generator,
                model_config_id=fixture.card_config_id,
                input_privacy_mode=InputPrivacyMode.SYNTHETIC_PROTOTYPE,
            ),
            judgment=fixture.judgment_binding(judgments),
        )
        with asyncio.Runner() as runner:
            outcome = pipeline.drive_run(
                session, run, "production-version-test", bindings, runner.get_loop()
            )
        assert outcome is pipeline.StepOutcome.COMPLETED
        assert card_generator.calls == 2 and judgments.calls == 1
        assert freshness.read_currentness(session, run) == "CURRENT"
