"""앵커 포지션 카드 생성·저장 수직 슬라이스 검증.

Repository 를 mock 하지 않는다. 실제 PostgreSQL 에 붙고 AI 호출 경계만 fake generator 로
바꾼다. 확인하는 것은 네 가지다. 무엇을 AI 로 보내는가, 모델을 기다리는 동안 DB 를 쥐고
있지 않은가, 저장 직전에 무엇을 다시 확인하는가, 실패하면 무엇이 남는가.
"""

from __future__ import annotations

import asyncio
import os
import threading
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from anchor_card_fixtures import (
    AS_OF,
    ATTEMPT,
    BUYER_NAME,
    BUYER_QUOTE,
    OWNER_NAME,
    OWNER_PHONE,
    OWNER_QUOTE,
    WORKER,
    FakeGenerator,
    Fixture,
    binding,
    run_use_case,
)
from brokerage_ai.f3 import (
    InputPrivacyMode,
    NegotiationSide,
)
from f3_committed_db import db_session
from f3_committed_db import remove_committed_rows as remove_committed_rows
from sqlalchemy import text
from sqlmodel import Session, create_engine

from domain.agent_execution import repository
from domain.agent_execution.anchor_card import (
    GenerationBinding,
    GenerationBindingError,
    SourceChangedError,
    generate_and_store_anchor_position_card,
)
from domain.agent_execution.models import InputVersionChangedError, LeaseNotHeldError

requires_database = pytest.mark.skipif(
    not os.getenv("TEST_DB_URL"),
    reason="TEST_DB_URL is required for PostgreSQL integration tests",
)


@requires_database
def test_listing_cache_miss_generates_stores_and_advances_to_anchor_ready() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.interaction(content=f"{OWNER_NAME} 통화. {OWNER_QUOTE}.", at=AS_OF)
        run_id = fixture.run()
        generator = FakeGenerator()

        result = run_use_case(session, run_id, generator, fixture.model_config_id)

        assert generator.calls == 1
        assert generator.requests[0].input_privacy_mode is InputPrivacyMode.SYNTHETIC_PROTOTYPE
        assert result.cache_hit is False
        assert result.negotiation_side is NegotiationSide.LISTING
        cards = fixture.cards()
        assert len(cards) == 1
        card = cards[0]
        assert card["id"] == result.position_analysis_id
        assert card["negotiation_side"] == "LISTING"
        assert card["listing_id"] == fixture.listing_id
        assert card["unit_id"] == fixture.unit_id
        assert card["negotiation_intent"] == "PRESENT"
        assert card["urgency"] == "RELAXED"
        assert card["contactability_status"] == "GOOD"
        assert card["source_interaction_count"] == 1
        assert card["data_version"] == 1
        assert card["cache_key"].startswith("position-card:v3:")
        stored = fixture.stored_run(run_id)
        assert stored["status"] == "ANCHOR_READY"
        assert stored["completed_at"] is None
        assert stored["lease_owner"] == WORKER
        assert stored["attempt_count"] == ATTEMPT
        assert stored["lease_expires_at"] is not None
        assert stored["input_tokens"] == 200
        assert stored["output_tokens"] == 80
        assert stored["latency_ms"] == 31


@requires_database
def test_requirement_cache_miss_stores_its_own_card() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.interaction(content=f"{BUYER_NAME} 상담. {BUYER_QUOTE}.", at=AS_OF, listing=False)
        run_id = fixture.run(listing=False)
        generator = FakeGenerator()

        result = run_use_case(session, run_id, generator, fixture.model_config_id)

        assert generator.calls == 1
        card = fixture.cards()[0]
        assert card["negotiation_side"] == "REQUIREMENT"
        assert card["requirement_id"] == fixture.requirement_id
        assert card["listing_id"] is None
        assert fixture.stored_run(run_id)["status"] == "ANCHOR_READY"
        (price,) = fixture.prices(result.position_analysis_id)
        assert price["price_kind"] == "BUDGET"
        assert price["stated_amount"] == 2_850_000_000


@requires_database
def test_cache_hit_reuses_the_card_without_calling_the_model() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.interaction(content=f"{OWNER_NAME} 통화. {OWNER_QUOTE}.", at=AS_OF)
        first_run = fixture.run()
        first = run_use_case(session, first_run, FakeGenerator(), fixture.model_config_id)

        second_run = fixture.run()
        generator = FakeGenerator()
        second = run_use_case(session, second_run, generator, fixture.model_config_id)

        assert generator.calls == 0
        assert second.cache_hit is True
        assert second.position_analysis_id == first.position_analysis_id
        assert len(fixture.cards()) == 1
        assert len(fixture.prices(first.position_analysis_id)) == 1
        assert fixture.stored_run(second_run)["status"] == "ANCHOR_READY"


# --- AI 로 나가는 입력 -----------------------------------------------------------


@requires_database
def test_the_opposite_side_logs_never_reach_the_request() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.interaction(content=f"소유자. {OWNER_QUOTE}.", at=AS_OF)
        fixture.interaction(content=f"손님. {BUYER_QUOTE}.", at=AS_OF, listing=False)
        generator = FakeGenerator()

        run_use_case(session, fixture.run(), generator, fixture.model_config_id)

        (request,) = generator.requests
        rendered = request.model_dump_json()
        assert OWNER_QUOTE in rendered
        assert BUYER_QUOTE not in rendered


@requires_database
def test_voided_logs_are_excluded_and_the_rest_arrive_in_order() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        old = fixture.interaction(
            content=f"과거 상담. {OWNER_QUOTE}.", at=datetime(2026, 8, 10, 1, 0, tzinfo=UTC)
        )
        voided = fixture.interaction(
            content="무효 처리된 상담", at=datetime(2026, 8, 12, 1, 0, tzinfo=UTC), voided=True
        )
        recent = fixture.interaction(content="최근 상담", at=AS_OF)
        generator = FakeGenerator()

        run_use_case(session, fixture.run(), generator, fixture.model_config_id)

        (request,) = generator.requests
        identifiers = [log.interaction_id for log in request.consultation_logs]
        assert identifiers == [old, recent]
        assert voided not in identifiers
        assert request.source.interaction_count == 2
        assert request.source.max_interaction_id == recent
        assert request.source.last_interaction_at == AS_OF


@requires_database
def test_a_run_only_ever_sees_its_own_brokerage() -> None:
    """실행의 사무소로만 장부를 읽는다. 옆 사무소의 로그가 요청에 섞이면 안 된다."""
    with db_session() as session:
        mine = Fixture(session)
        theirs = Fixture(session, name="남의 사무소")
        mine.interaction(content=f"우리 사무소. {OWNER_QUOTE}.", at=AS_OF)
        theirs.interaction(content=f"남의 사무소. {OWNER_QUOTE}.", at=AS_OF)
        generator = FakeGenerator()

        run_use_case(session, theirs.run(), generator, theirs.model_config_id)

        (request,) = generator.requests
        rendered = request.model_dump_json()
        assert "남의 사무소" in rendered
        assert "우리 사무소" not in rendered
        assert request.anchor_id == theirs.listing_id
        # 우리 사무소에는 카드가 생기지 않는다.
        assert mine.cards() == []
        assert len(theirs.cards()) == 1


@requires_database
def test_a_run_cannot_point_at_another_brokerage_ledger_row() -> None:
    """복합 외래키가 사무소를 넘는 앵커 자체를 막는다."""
    from sqlalchemy.exc import IntegrityError

    with db_session() as session:
        mine = Fixture(session)
        theirs = Fixture(session, name="남의 사무소")

        with pytest.raises(IntegrityError):
            session.execute(
                text(
                    "INSERT INTO agent_run (brokerage_id, run_group_id, run_type, agent_type,"
                    " status, trigger_type, requested_by, target_listing_id, input_data_version)"
                    " VALUES (:b, :g, 'CROSS_JUDGMENT', 'BROKERAGE_WORKFLOW', 'RUNNING',"
                    " 'USER_REQUEST', :u, :l, 1)"
                ),
                {
                    "b": theirs.brokerage_id,
                    "g": str(uuid4()),
                    "u": theirs.user_id,
                    "l": mine.listing_id,
                },
            )
        session.rollback()


# --- 모델 호출 중 DB 를 쥐지 않는다 -------------------------------------------------


@requires_database
def test_no_row_lock_is_held_while_the_model_runs() -> None:
    """모델이 대기하는 동안 다른 커넥션이 같은 장부 행을 고칠 수 있어야 한다."""
    with db_session() as session:
        fixture = Fixture(session)
        fixture.interaction(content=f"소유자. {OWNER_QUOTE}.", at=AS_OF)
        run_id = fixture.run()

        released = threading.Event()
        resume = threading.Event()
        changed = threading.Event()
        generator = FakeGenerator(before_return=resume, released=released)

        def change_the_ledger() -> None:
            assert released.wait(timeout=10)
            engine = create_engine(os.environ["TEST_DB_URL"])
            with Session(engine) as other:
                other.execute(
                    text("UPDATE property_listing SET memo = 'touched' WHERE id = :i"),
                    {"i": fixture.listing_id},
                )
                other.commit()
            engine.dispose()
            changed.set()
            resume.set()

        worker = threading.Thread(target=change_the_ledger)
        worker.start()
        run_use_case(session, run_id, generator, fixture.model_config_id)
        worker.join(timeout=15)

        assert changed.is_set(), "모델 대기 중 다른 커넥션이 장부를 고치지 못했다"
        assert fixture.stored_run(run_id)["status"] == "ANCHOR_READY"


# --- 저장 직전 재검증 -------------------------------------------------------------


def _expect_rejection(fixture: Fixture, run_id: int, generator: FakeGenerator, error):
    with pytest.raises(error):
        run_use_case(fixture.session, run_id, generator, fixture.model_config_id)
    assert fixture.cards() == []
    assert fixture.stored_run(run_id)["status"] == "RUNNING"


def _mutating_generator(fixture: Fixture, sql: str, **params: object) -> FakeGenerator:
    """모델이 응답하기 직전에 다른 커넥션으로 DB 를 바꾼다."""
    released = threading.Event()
    resume = threading.Event()

    def mutate() -> None:
        assert released.wait(timeout=10)
        engine = create_engine(os.environ["TEST_DB_URL"])
        with Session(engine) as other:
            other.execute(text(sql), params)
            other.commit()
        engine.dispose()
        resume.set()

    threading.Thread(target=mutate, daemon=True).start()
    return FakeGenerator(before_return=resume, released=released)


@requires_database
def test_a_row_version_change_during_generation_is_rejected() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.interaction(content=f"소유자. {OWNER_QUOTE}.", at=AS_OF)
        run_id = fixture.run()
        generator = _mutating_generator(
            fixture,
            "UPDATE property_listing SET row_version = row_version + 1 WHERE id = :i",
            i=fixture.listing_id,
        )

        _expect_rejection(fixture, run_id, generator, InputVersionChangedError)


@requires_database
def test_a_new_log_during_generation_is_rejected() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.interaction(content=f"소유자. {OWNER_QUOTE}.", at=AS_OF)
        run_id = fixture.run()
        generator = _mutating_generator(
            fixture,
            "INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_content,"
            " unit_id, party_id) VALUES (:b, now(), '생성 중 추가된 상담', :u, :p)",
            b=fixture.brokerage_id,
            u=fixture.unit_id,
            p=fixture.owner_party_id,
        )

        _expect_rejection(fixture, run_id, generator, SourceChangedError)


@requires_database
def test_voiding_a_log_during_generation_is_rejected() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        first = fixture.interaction(
            content=f"소유자. {OWNER_QUOTE}.", at=datetime(2026, 8, 10, 1, 0, tzinfo=UTC)
        )
        fixture.interaction(content="두 번째 상담", at=AS_OF)
        run_id = fixture.run()
        generator = _mutating_generator(
            fixture, "UPDATE client_interaction SET is_voided = true WHERE id = :i", i=first
        )

        _expect_rejection(fixture, run_id, generator, SourceChangedError)


@requires_database
def test_a_stolen_lease_is_rejected() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.interaction(content=f"소유자. {OWNER_QUOTE}.", at=AS_OF)
        run_id = fixture.run()
        generator = _mutating_generator(
            fixture, "UPDATE agent_run SET lease_owner = 'other-worker' WHERE id = :i", i=run_id
        )

        with pytest.raises(LeaseNotHeldError):
            run_use_case(session, run_id, generator, fixture.model_config_id)
        assert fixture.cards() == []


@requires_database
def test_an_expired_lease_is_rejected() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.interaction(content=f"소유자. {OWNER_QUOTE}.", at=AS_OF)
        run_id = fixture.run()
        generator = _mutating_generator(
            fixture,
            "UPDATE agent_run SET lease_expires_at = now() - interval '1 minute' WHERE id = :i",
            i=run_id,
        )

        with pytest.raises(LeaseNotHeldError):
            run_use_case(session, run_id, generator, fixture.model_config_id)
        assert fixture.cards() == []


@requires_database
def test_a_changed_attempt_count_is_rejected() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.interaction(content=f"소유자. {OWNER_QUOTE}.", at=AS_OF)
        run_id = fixture.run()
        generator = _mutating_generator(
            fixture,
            "UPDATE agent_run SET attempt_count = attempt_count + 1 WHERE id = :i",
            i=run_id,
        )

        with pytest.raises(LeaseNotHeldError):
            run_use_case(session, run_id, generator, fixture.model_config_id)
        assert fixture.cards() == []


# --- AI 결과 거절 ---------------------------------------------------------------


@requires_database
def test_every_open_trade_type_is_stored_in_the_price_child_table() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        session.execute(
            text(
                "UPDATE property_listing SET is_jeonse_available = true,"
                " jeonse_deposit_amount = 1500000000, is_monthly_rent_available = true,"
                " monthly_rent_deposit_amount = 100000000, monthly_rent_amount = 3000000"
                " WHERE id = :i"
            ),
            {"i": fixture.listing_id},
        )
        session.commit()
        fixture.interaction(content=f"소유자. {OWNER_QUOTE}.", at=AS_OF)
        run_id = fixture.run()

        result = run_use_case(session, run_id, FakeGenerator(), fixture.model_config_id)

        prices = fixture.prices(result.position_analysis_id)
        assert [row["price_kind"] for row in prices] == ["SALE", "JEONSE", "MONTHLY_RENT"]
        assert prices[0]["stated_amount"] == 2_880_000_000
        assert prices[2]["stated_monthly_amount"] == 3_000_000
        card = fixture.cards()[0]
        # 여러 개일 때는 대표값을 고르지 않는다.
        assert card["stated_price_amount"] is None
        assert card["estimated_price_amount"] is None


@requires_database
def test_a_single_price_fills_the_compatibility_projection() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.interaction(content=f"소유자. {OWNER_QUOTE}.", at=AS_OF)
        run_id = fixture.run()

        result = run_use_case(session, run_id, FakeGenerator(), fixture.model_config_id)

        assert len(fixture.prices(result.position_analysis_id)) == 1
        assert fixture.cards()[0]["stated_price_amount"] == 2_880_000_000


@requires_database
def test_quote_and_inference_evidence_are_both_stored_with_offsets() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        interaction_id = fixture.interaction(content=f"{OWNER_NAME} 통화. {OWNER_QUOTE}.", at=AS_OF)
        run_id = fixture.run()

        result = run_use_case(session, run_id, FakeGenerator(), fixture.model_config_id)

        rows = fixture.evidence(result.position_analysis_id)
        quotes = [row for row in rows if row["evidence_type"] == "QUOTE"]
        inferences = [row for row in rows if row["evidence_type"] == "INFERENCE"]
        assert {row["field_name"] for row in rows} >= {
            "intent",
            "urgency",
            "contactability",
            "flexible.0",
        }
        assert quotes and inferences
        for row in quotes:
            assert row["interaction_id"] == interaction_id
            assert row["quote_text"] == OWNER_QUOTE
            assert row["quote_start_offset"] is not None
            assert row["quote_end_offset"] == row["quote_start_offset"] + len(OWNER_QUOTE)
            original = session.execute(
                text("SELECT interaction_content FROM client_interaction WHERE id = :i"),
                {"i": interaction_id},
            ).scalar_one()
            # 합성 프로토타입은 본문을 변환하지 않아 Provider 입력과 원문의 위치가 같다.
            assert original[row["quote_start_offset"] : row["quote_end_offset"]] == OWNER_QUOTE
        for row in inferences:
            assert row["interaction_id"] is None
            assert row["quote_text"] is None
            assert row["quote_start_offset"] is None
            assert row["note"]


@requires_database
def test_no_personal_data_reaches_the_stored_snapshots() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.interaction(content=f"{OWNER_NAME}({OWNER_PHONE}) 통화. {OWNER_QUOTE}.", at=AS_OF)
        run_id = fixture.run()

        run_use_case(session, run_id, FakeGenerator(), fixture.model_config_id)

        card = fixture.cards()[0]
        stored = fixture.stored_run(run_id)
        rendered = f"{card['analysis_snapshot']}{stored['redacted_output_snapshot']}"
        for secret in (OWNER_NAME, OWNER_PHONE):
            assert secret not in rendered
        assert "requested_by" not in str(stored["redacted_output_snapshot"])
        # 실행 snapshot 은 요약만 담는다. 카드 본문과 상담 로그를 중복 저장하지 않는다.
        assert OWNER_QUOTE not in str(stored["redacted_output_snapshot"])
        assert set(stored["redacted_output_snapshot"]) == {
            "anchor_type",
            "anchor_id",
            "target_label",
            "input_data_version",
            "position_analysis_id",
            "cache_hit",
            "input_privacy_mode",
            "contract_version",
            "prompt_version",
            "workflow_version",
            "provider",
            "model",
        }


# --- 저장 경합 -----------------------------------------------------------------


@requires_database
def test_two_runs_racing_on_the_same_cache_key_leave_exactly_one_card() -> None:
    """진 쪽은 실패하지 않고 이긴 쪽의 카드를 재사용한다."""
    with db_session() as session:
        fixture = Fixture(session)
        fixture.interaction(content=f"소유자. {OWNER_QUOTE}.", at=AS_OF)
        first_run = fixture.run()
        second_run = fixture.run()

        released = threading.Event()
        resume = threading.Event()
        loser = FakeGenerator(before_return=resume, released=released)

        def win_the_race() -> None:
            assert released.wait(timeout=10)
            engine = create_engine(os.environ["TEST_DB_URL"])
            with Session(engine) as other:
                asyncio.run(
                    generate_and_store_anchor_position_card(
                        other,
                        run_id=second_run,
                        worker_id=WORKER,
                        attempt_count=ATTEMPT,
                        binding=binding(FakeGenerator(), fixture.model_config_id),
                        as_of=AS_OF,
                    )
                )
            engine.dispose()
            resume.set()

        winner = threading.Thread(target=win_the_race)
        winner.start()
        result = run_use_case(session, first_run, loser, fixture.model_config_id)
        winner.join(timeout=20)

        cards = fixture.cards()
        assert len(cards) == 1
        assert result.position_analysis_id == cards[0]["id"]
        assert len(fixture.prices(cards[0]["id"])) == 1
        assert fixture.stored_run(first_run)["status"] == "ANCHOR_READY"
        assert fixture.stored_run(second_run)["status"] == "ANCHOR_READY"


# --- 실패 시 rollback -----------------------------------------------------------


@requires_database
def test_a_failure_while_advancing_the_run_rolls_back_the_whole_card() -> None:
    """상태 전이가 실패하면 카드·가격·근거가 모두 사라져야 한다."""
    with db_session() as session:
        fixture = Fixture(session)
        fixture.interaction(content=f"소유자. {OWNER_QUOTE}.", at=AS_OF)
        run_id = fixture.run()

        original = repository.mark_run_anchor_ready

        def refuse(*args: object, **kwargs: object) -> int:
            return 0

        repository.mark_run_anchor_ready = refuse  # type: ignore[assignment]
        try:
            with pytest.raises(LeaseNotHeldError):
                run_use_case(session, run_id, FakeGenerator(), fixture.model_config_id)
        finally:
            repository.mark_run_anchor_ready = original  # type: ignore[assignment]

        assert fixture.cards() == []
        # 카드가 사라졌으면 그 자식도 남아 있으면 안 된다.
        assert (
            session.execute(
                text("SELECT count(*) FROM negotiation_position_price WHERE brokerage_id = :b"),
                {"b": fixture.brokerage_id},
            ).scalar_one()
            == 0
        )
        assert (
            session.execute(
                text("SELECT count(*) FROM negotiation_position_evidence WHERE brokerage_id = :b"),
                {"b": fixture.brokerage_id},
            ).scalar_one()
            == 0
        )
        assert fixture.stored_run(run_id)["status"] == "RUNNING"


@requires_database
def test_a_failure_while_storing_evidence_rolls_back_the_card_and_prices() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.interaction(content=f"소유자. {OWNER_QUOTE}.", at=AS_OF)
        run_id = fixture.run()

        original = repository.insert_position_evidence

        def explode(*args: object, **kwargs: object) -> None:
            raise RuntimeError("evidence insert failed")

        repository.insert_position_evidence = explode  # type: ignore[assignment]
        try:
            with pytest.raises(RuntimeError, match="evidence insert failed"):
                run_use_case(session, run_id, FakeGenerator(), fixture.model_config_id)
        finally:
            repository.insert_position_evidence = original  # type: ignore[assignment]

        assert fixture.cards() == []
        assert fixture.stored_run(run_id)["status"] == "RUNNING"


@requires_database
def test_a_provider_failure_leaves_no_card_and_no_state_change() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.interaction(content=f"소유자. {OWNER_QUOTE}.", at=AS_OF)
        run_id = fixture.run()

        class FailingGenerator(FakeGenerator):
            async def generate_position_card(self, request):  # type: ignore[override]
                from brokerage_ai.core.errors import ProviderTimeoutError

                raise ProviderTimeoutError()

        with pytest.raises(Exception) as raised:
            run_use_case(session, run_id, FailingGenerator(), fixture.model_config_id)

        assert str(raised.value) == "provider request timed out"
        assert fixture.cards() == []
        stored = fixture.stored_run(run_id)
        assert stored["status"] == "RUNNING"
        assert stored["failure_code"] is None
        assert stored["failure_message"] is None


@requires_database
def test_masked_mode_is_rejected_until_real_f1_masking_is_implemented() -> None:
    """ADR-0014 예외가 실사용 F1 입력의 무마스킹 통로가 되면 안 된다."""
    with db_session() as session:
        fixture = Fixture(session)
        fixture.interaction(content=f"합성 소유자. {OWNER_QUOTE}.", at=AS_OF)
        run_id = fixture.run()
        generator = FakeGenerator()

        with pytest.raises(GenerationBindingError, match="masked F1 snapshot"):
            asyncio.run(
                generate_and_store_anchor_position_card(
                    session,
                    run_id=run_id,
                    worker_id=WORKER,
                    attempt_count=ATTEMPT,
                    binding=GenerationBinding(
                        generator=generator,
                        model_config_id=fixture.model_config_id,
                        input_privacy_mode=InputPrivacyMode.MASKED,
                    ),
                    as_of=AS_OF,
                )
            )

        assert generator.calls == 0
        assert fixture.cards() == []
        assert fixture.stored_run(run_id)["status"] == "RUNNING"
