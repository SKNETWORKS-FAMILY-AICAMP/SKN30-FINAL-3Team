from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import brokerage_ai
import pytest
from sqlalchemy import text
from sqlmodel import Session, create_engine

from domain.agent_execution import repository, service
from domain.agent_execution.models import (
    CROSS_JUDGMENT_RUN_TYPE,
    AgentRunAnchorError,
    AnchorType,
    InputVersionChangedError,
    LeaseNotHeldError,
)

requires_database = pytest.mark.skipif(
    not os.getenv("TEST_DB_URL"),
    reason="TEST_DB_URL is required for PostgreSQL integration tests",
)

WORKER = "worker-anchor"
ATTEMPT = 1


@contextmanager
def anchor_session() -> Iterator[Session]:
    """실제 PostgreSQL에 붙되 종료 시 전부 롤백한다."""
    engine = create_engine(os.environ["TEST_DB_URL"])
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


def scalar(session: Session, sql: str, **params: object) -> int:
    return session.execute(text(sql), params).scalar_one()


class Fixture:
    """한 사무소의 매물·구입장 앵커와 선점된 실행을 만든다."""

    def __init__(self, session: Session, name: str = "카드 검증 사무소") -> None:
        self.session = session
        self.brokerage_id = scalar(
            session, "INSERT INTO brokerage (name) VALUES (:n) RETURNING id", n=name
        )
        self.user_id = scalar(
            session,
            "INSERT INTO app_user (brokerage_id, login_id, password_hash, display_name, role)"
            " VALUES (:b, :l, 'unused', '검증', 'OWNER') RETURNING id",
            b=self.brokerage_id,
            l=f"card-{self.brokerage_id}",
        )
        complex_id = scalar(
            session,
            "INSERT INTO property_complex (brokerage_id, name)"
            " VALUES (:b, '카드단지') RETURNING id",
            b=self.brokerage_id,
        )
        self.unit_id = scalar(
            session,
            "INSERT INTO property_unit (brokerage_id, complex_id, unit_number)"
            " VALUES (:b, :c, '101') RETURNING id",
            b=self.brokerage_id,
            c=complex_id,
        )
        self.listing_id = scalar(
            session,
            "INSERT INTO property_listing (brokerage_id, unit_id) VALUES (:b, :u) RETURNING id",
            b=self.brokerage_id,
            u=self.unit_id,
        )
        self.party_id = scalar(
            session,
            "INSERT INTO party (brokerage_id, party_type, name) VALUES (:b, 'PERSON', '손님')"
            " RETURNING id",
            b=self.brokerage_id,
        )
        self.requirement_id = scalar(
            session,
            "INSERT INTO property_requirement (brokerage_id, party_id, demand_type)"
            " VALUES (:b, :p, '매수') RETURNING id",
            b=self.brokerage_id,
            p=self.party_id,
        )

    def run(
        self,
        *,
        listing: bool = True,
        requirement: bool = False,
        status: str = "RUNNING",
        lease_owner: str | None = WORKER,
        attempt_count: int = ATTEMPT,
        lease_expires_at: datetime | None = None,
        parent_run_id: int | None = None,
        run_type: str = CROSS_JUDGMENT_RUN_TYPE,
        input_data_version: int = 1,
    ) -> int:
        return scalar(
            self.session,
            "INSERT INTO agent_run (brokerage_id, run_group_id, parent_run_id, run_type,"
            " agent_type, status, trigger_type, requested_by, target_listing_id, target_unit_id,"
            " target_requirement_id, input_data_version, attempt_count, lease_owner,"
            " lease_expires_at)"
            " VALUES (:b, :g, :parent, :rt, 'BROKERAGE_WORKFLOW', :st, 'USER_REQUEST', :u, :l,"
            " :unit, :r, :v, :a, :owner, :exp) RETURNING id",
            b=self.brokerage_id,
            g=str(uuid4()),
            parent=parent_run_id,
            rt=run_type,
            st=status,
            u=self.user_id,
            l=self.listing_id if listing else None,
            unit=self.unit_id if listing else None,
            r=self.requirement_id if requirement else None,
            v=input_data_version,
            a=attempt_count,
            owner=lease_owner,
            exp=lease_expires_at or datetime.now(UTC) + timedelta(minutes=5),
        )

    def interaction(self, *, at: datetime, unit: bool = True) -> int:
        return scalar(
            self.session,
            "INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_content,"
            " unit_id, requirement_id) VALUES (:b, :at, '상담 내용', :u, :r) RETURNING id",
            b=self.brokerage_id,
            at=at,
            u=self.unit_id if unit else None,
            r=None if unit else self.requirement_id,
        )

    def card(
        self,
        run_id: int,
        *,
        cache_key: str,
        side: str = "LISTING",
        listing: bool = True,
        data_version: int = 1,
        invalidated: bool = False,
        interaction_count: int = 0,
        last_interaction_at: datetime | None = None,
    ) -> int:
        return scalar(
            self.session,
            "INSERT INTO negotiation_position_analysis (brokerage_id, agent_run_id,"
            " negotiation_side, listing_id, requirement_id, cache_key, data_version,"
            " source_interaction_count, last_interaction_at, invalidated_at)"
            " VALUES (:b, :run, :side, :l, :r, :k, :v, :cnt, :at, :inv) RETURNING id",
            b=self.brokerage_id,
            run=run_id,
            side=side,
            l=self.listing_id if listing else None,
            r=None if listing else self.requirement_id,
            k=cache_key,
            v=data_version,
            cnt=interaction_count,
            at=last_interaction_at,
            inv=datetime.now(UTC) if invalidated else None,
        )

    def card_for(self, run_id: int, lookup: service.AnchorCardLookup, **overrides: object) -> int:
        """현재 조회 결과와 source 가 일치하는 카드. 재사용 조건을 실제로 만족한다."""
        request = lookup.generation_request
        assert request is not None
        defaults: dict = {
            "cache_key": lookup.cache_key,
            "interaction_count": request.interaction_count,
            "last_interaction_at": request.last_interaction_at,
        }
        return self.card(run_id, **{**defaults, **overrides})


def prepare(session: Session, run_id: int, **overrides: object) -> service.AnchorCardLookup:
    return service.prepare_anchor_position_card(
        session,
        run_id,
        str(overrides.get("worker_id", WORKER)),
        int(overrides.get("attempt_count", ATTEMPT)),  # pyright: ignore[reportArgumentType]
    )


def agent_run_row(session: Session, run_id: int) -> dict:
    return dict(
        session.execute(text("SELECT * FROM agent_run WHERE id = :i"), {"i": run_id})
        .mappings()
        .one()
    )


@requires_database
def test_valid_lease_holder_gets_a_cache_miss_with_a_generation_request() -> None:
    with anchor_session() as session:
        fixture = Fixture(session)
        run_id = fixture.run()
        fixture.interaction(at=datetime(2026, 8, 18, 3, 0, tzinfo=UTC))
        fixture.interaction(at=datetime(2026, 8, 19, 4, 0, tzinfo=UTC))

        result = prepare(session, run_id)

        assert result.cache_hit is False
        assert result.position_analysis_id is None
        assert result.anchor_type is AnchorType.LISTING
        assert result.anchor_id == fixture.listing_id
        assert result.data_version == 1
        assert result.negotiation_side == "LISTING"

        request = result.generation_request
        assert request is not None
        assert request.cache_key == result.cache_key
        assert request.interaction_count == 2
        assert request.last_interaction_at == datetime(2026, 8, 19, 4, 0, tzinfo=UTC)
        assert request.agent_type == "BROKERAGE_WORKFLOW"
        assert request.model_config_id is None


@requires_database
def test_requirement_anchor_counts_only_its_own_interactions() -> None:
    with anchor_session() as session:
        fixture = Fixture(session)
        run_id = fixture.run(listing=False, requirement=True)
        fixture.interaction(at=datetime(2026, 8, 18, 3, 0, tzinfo=UTC), unit=True)
        fixture.interaction(at=datetime(2026, 8, 19, 5, 0, tzinfo=UTC), unit=False)

        result = prepare(session, run_id)

        assert result.anchor_type is AnchorType.REQUIREMENT
        assert result.anchor_id == fixture.requirement_id
        assert result.negotiation_side == "REQUIREMENT"
        request = result.generation_request
        assert request is not None
        assert request.interaction_count == 1
        assert request.last_interaction_at == datetime(2026, 8, 19, 5, 0, tzinfo=UTC)


@requires_database
def test_no_interactions_normalize_to_null_and_zero() -> None:
    with anchor_session() as session:
        fixture = Fixture(session)

        request = prepare(session, fixture.run()).generation_request

        assert request is not None
        assert request.interaction_count == 0
        assert request.last_interaction_at is None


@requires_database
def test_active_card_with_the_same_key_is_reused() -> None:
    with anchor_session() as session:
        fixture = Fixture(session)
        run_id = fixture.run()
        miss = prepare(session, run_id)
        card_id = fixture.card_for(run_id, miss)

        hit = prepare(session, run_id)

        assert hit.cache_hit is True
        assert hit.position_analysis_id == card_id
        assert hit.cache_key == miss.cache_key
        assert hit.generation_request is None


@requires_database
@pytest.mark.parametrize(
    "overrides",
    [
        {"invalidated": True},
        {"cache_key": "position-card:v2:다른키"},
        {"side": "REQUIREMENT"},
        {"listing": False},
        {"data_version": 2},
        {"interaction_count": 99},
        {"last_interaction_at": datetime(2000, 1, 1, tzinfo=UTC)},
    ],
    ids=[
        "무효화됨",
        "다른_cache_key",
        "다른_측면",
        "다른_대상",
        "다른_버전",
        "다른_상담건수",
        "다른_마지막상담시각",
    ],
)
def test_cards_that_do_not_match_are_not_reused(overrides: dict) -> None:
    with anchor_session() as session:
        fixture = Fixture(session)
        run_id = fixture.run()
        miss = prepare(session, run_id)
        fixture.card_for(run_id, miss, **overrides)

        assert prepare(session, run_id).cache_hit is False


@requires_database
def test_another_brokerage_card_is_never_reused() -> None:
    with anchor_session() as session:
        mine = Fixture(session)
        other = Fixture(session, name="남의 사무소")
        run_id = mine.run()
        miss = prepare(session, run_id)
        other.card(other.run(), cache_key=miss.cache_key)  # 같은 키, 다른 사무소

        assert prepare(session, run_id).cache_hit is False


@requires_database
@pytest.mark.parametrize(
    ("run_kwargs", "call_kwargs"),
    [
        ({}, {"worker_id": "다른-worker"}),
        ({}, {"attempt_count": 2}),
        ({"lease_expires_at": datetime.now(UTC) - timedelta(seconds=1)}, {}),
        ({"status": "QUEUED", "lease_owner": None}, {}),
        ({"status": "COMPLETED"}, {}),
        ({"run_type": "POSITION_ANALYSIS"}, {}),
    ],
    ids=["다른_worker", "다른_attempt", "만료된_lease", "QUEUED", "COMPLETED", "다른_run_type"],
)
def test_invalid_lease_is_rejected(run_kwargs: dict, call_kwargs: dict) -> None:
    with anchor_session() as session:
        fixture = Fixture(session)
        run_id = fixture.run(**run_kwargs)

        with pytest.raises(LeaseNotHeldError):
            prepare(session, run_id, **call_kwargs)


@requires_database
def test_child_run_is_rejected() -> None:
    with anchor_session() as session:
        fixture = Fixture(session)
        parent = fixture.run()
        child = fixture.run(parent_run_id=parent)

        with pytest.raises(LeaseNotHeldError):
            prepare(session, child)


@requires_database
def test_changed_anchor_version_stops_the_lookup() -> None:
    with anchor_session() as session:
        fixture = Fixture(session)
        run_id = fixture.run(input_data_version=1)
        session.execute(
            text("UPDATE property_listing SET row_version = 2 WHERE id = :i"),
            {"i": fixture.listing_id},
        )

        with pytest.raises(InputVersionChangedError):
            prepare(session, run_id)


@requires_database
@pytest.mark.parametrize(
    ("listing", "requirement"), [(False, False), (True, True)], ids=["앵커_없음", "앵커_둘"]
)
def test_run_without_exactly_one_anchor_raises_the_existing_invariant_error(
    listing: bool, requirement: bool
) -> None:
    with anchor_session() as session:
        fixture = Fixture(session)
        run_id = fixture.run(listing=listing, requirement=requirement)

        with pytest.raises(AgentRunAnchorError):
            prepare(session, run_id)


@requires_database
def test_result_carries_no_personal_data() -> None:
    with anchor_session() as session:
        fixture = Fixture(session)
        run_id = fixture.run()
        fixture.interaction(at=datetime(2026, 8, 19, 4, 0, tzinfo=UTC))

        rendered = repr(prepare(session, run_id))

        for secret in ["상담 내용", "손님", "카드단지"]:
            assert secret not in rendered


@requires_database
def test_lookup_modifies_neither_the_run_nor_the_cards(monkeypatch) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("카드 조회는 AI runtime을 호출하지 않는다")

    monkeypatch.setattr(brokerage_ai, "create_ai_runtime", fail)
    monkeypatch.setattr(brokerage_ai, "load_ai_config", fail)

    with anchor_session() as session:
        fixture = Fixture(session)
        run_id = fixture.run()
        miss = prepare(session, run_id)
        fixture.card_for(run_id, miss)
        session.commit()

        before_run = agent_run_row(session, run_id)
        before_cards = (
            session.execute(
                text(
                    "SELECT * FROM negotiation_position_analysis "
                    "WHERE brokerage_id = :b ORDER BY id"
                ),
                {"b": fixture.brokerage_id},
            )
            .mappings()
            .all()
        )

        assert prepare(session, run_id).cache_hit is True
        assert prepare(session, run_id).cache_hit is True

        assert agent_run_row(session, run_id) == before_run
        after_cards = (
            session.execute(
                text(
                    "SELECT * FROM negotiation_position_analysis "
                    "WHERE brokerage_id = :b ORDER BY id"
                ),
                {"b": fixture.brokerage_id},
            )
            .mappings()
            .all()
        )
        assert after_cards == before_cards


@requires_database
def test_repository_lookup_is_scoped_to_the_owning_brokerage() -> None:
    with anchor_session() as session:
        mine = Fixture(session)
        other = Fixture(session, name="격리 확인 사무소")
        key = "position-card:v2:공유키"
        other.card(other.run(), cache_key=key)

        # brokerage_id 를 빼면 남의 카드가 그대로 나오도록 나머지 조건은 전부 맞춘다.
        found = repository.find_active_position_card(
            session,
            mine.brokerage_id,
            cache_key=key,
            negotiation_side="LISTING",
            listing_id=other.listing_id,
            requirement_id=None,
            data_version=1,
            interactions=repository.InteractionSummary(0, None, None),
        )

        assert found is None
        assert (
            repository.find_active_position_card(
                session,
                other.brokerage_id,
                cache_key=key,
                negotiation_side="LISTING",
                listing_id=other.listing_id,
                requirement_id=None,
                data_version=1,
                interactions=repository.InteractionSummary(0, None, None),
            )
            is not None
        )


@requires_database
def test_unchanged_interactions_keep_the_same_cache_key() -> None:
    with anchor_session() as session:
        fixture = Fixture(session)
        run_id = fixture.run()
        fixture.interaction(at=datetime(2026, 8, 19, 4, 0, tzinfo=UTC))

        assert prepare(session, run_id).cache_key == prepare(session, run_id).cache_key


@requires_database
@pytest.mark.parametrize(
    "added_at",
    [
        datetime(2026, 8, 1, 1, 0, tzinfo=UTC),
        datetime(2026, 8, 19, 4, 0, tzinfo=UTC),
        datetime(2026, 8, 20, 9, 0, tzinfo=UTC),
    ],
    ids=["과거_시각_로그", "같은_시각_로그", "최신_로그"],
)
def test_adding_an_interaction_invalidates_the_existing_card(added_at: datetime) -> None:
    """MAX(interaction_at) 이 그대로여도 로그 집합이 바뀌면 기존 카드를 재사용하면 안 된다."""
    with anchor_session() as session:
        fixture = Fixture(session)
        run_id = fixture.run()
        fixture.interaction(at=datetime(2026, 8, 19, 4, 0, tzinfo=UTC))
        before = prepare(session, run_id)
        fixture.card_for(run_id, before)
        assert prepare(session, run_id).cache_hit is True

        fixture.interaction(at=added_at)

        after = prepare(session, run_id)
        assert after.cache_hit is False
        assert after.cache_key != before.cache_key
        assert after.generation_request is not None
        assert after.generation_request.interaction_count == 2


@requires_database
def test_voiding_an_interaction_invalidates_the_existing_card() -> None:
    with anchor_session() as session:
        fixture = Fixture(session)
        run_id = fixture.run()
        fixture.interaction(at=datetime(2026, 8, 18, 3, 0, tzinfo=UTC))
        voided = fixture.interaction(at=datetime(2026, 8, 19, 4, 0, tzinfo=UTC))
        before = prepare(session, run_id)
        fixture.card_for(run_id, before)
        assert prepare(session, run_id).cache_hit is True

        session.execute(
            text("UPDATE client_interaction SET is_voided = true WHERE id = :i"), {"i": voided}
        )

        after = prepare(session, run_id)
        assert after.cache_hit is False
        assert after.cache_key != before.cache_key
        assert after.generation_request is not None
        assert after.generation_request.interaction_count == 1
        assert after.generation_request.last_interaction_at == datetime(
            2026, 8, 18, 3, 0, tzinfo=UTC
        )


@requires_database
def test_generation_request_carries_the_full_source_identity() -> None:
    with anchor_session() as session:
        fixture = Fixture(session)
        run_id = fixture.run()
        fixture.interaction(at=datetime(2026, 8, 18, 3, 0, tzinfo=UTC))
        latest = fixture.interaction(at=datetime(2026, 8, 19, 4, 0, tzinfo=UTC))

        request = prepare(session, run_id).generation_request

        assert request is not None
        assert request.interaction_count == 2
        assert request.last_interaction_at == datetime(2026, 8, 19, 4, 0, tzinfo=UTC)
        assert request.max_interaction_id == latest


@requires_database
def test_summary_of_an_anchor_without_interactions_is_empty() -> None:
    with anchor_session() as session:
        fixture = Fixture(session)

        summary = repository.summarize_interactions(
            session, fixture.brokerage_id, unit_id=fixture.unit_id, listing_id=fixture.listing_id
        )

        assert summary == repository.InteractionSummary(0, None, None)
