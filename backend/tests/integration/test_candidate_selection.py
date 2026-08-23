"""결정적 SQL 후보 추출의 수직 슬라이스.

실제 PostgreSQL 에 붙는다. 확인하는 것은 넷이다. 어느 장부에서 후보를 찾는가, 무엇을
조건으로 거르는가, 15건을 넘으면 나머지를 보존하는가, 그리고 사무소와 삭제 범위를
지키는가. 모델은 이 단계에 등장하지 않는다 (F3-SQ-01).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.pool import NullPool
from sqlmodel import Session, create_engine

from domain.agent_execution import repository
from domain.agent_execution.candidates import (
    CANDIDATE_CARD_LIMIT,
    AnchorCardMissingError,
    select_candidates,
    store_candidate_selection,
)
from domain.agent_execution.models import (
    ANCHOR_READY_STATUS,
    CANDIDATES_READY_STATUS,
    AnchorType,
    InputVersionChangedError,
    LeaseNotHeldError,
)

requires_database = pytest.mark.skipif(
    not os.getenv("TEST_DB_URL"),
    reason="TEST_DB_URL is required for PostgreSQL integration tests",
)

WORKER = "worker-candidates"
ATTEMPT = 1
AS_OF = datetime(2026, 8, 23, 1, 0, tzinfo=UTC)

CREATED_BROKERAGES: list[int] = []

_CLEANUP_ORDER = (
    "DELETE FROM match_candidate_evidence WHERE brokerage_id = ANY(:ids)",
    "DELETE FROM match_candidate_evaluation WHERE brokerage_id = ANY(:ids)",
    "DELETE FROM match_evaluation WHERE brokerage_id = ANY(:ids)",
    "DELETE FROM negotiation_position_evidence WHERE brokerage_id = ANY(:ids)",
    "DELETE FROM negotiation_position_price WHERE brokerage_id = ANY(:ids)",
    "DELETE FROM negotiation_position_analysis WHERE brokerage_id = ANY(:ids)",
    "DELETE FROM agent_run WHERE brokerage_id = ANY(:ids)",
    "DELETE FROM client_interaction WHERE brokerage_id = ANY(:ids)",
    "DELETE FROM property_listing WHERE brokerage_id = ANY(:ids)",
    "DELETE FROM property_unit_party_relation WHERE brokerage_id = ANY(:ids)",
    "DELETE FROM property_requirement_complex WHERE brokerage_id = ANY(:ids)",
    "DELETE FROM property_requirement WHERE brokerage_id = ANY(:ids)",
    "DELETE FROM party_contact WHERE brokerage_id = ANY(:ids)",
    "DELETE FROM party WHERE brokerage_id = ANY(:ids)",
    "DELETE FROM property_unit WHERE brokerage_id = ANY(:ids)",
    "DELETE FROM property_complex WHERE brokerage_id = ANY(:ids)",
    "DELETE FROM ai_model_config WHERE brokerage_id = ANY(:ids)",
    "DELETE FROM app_user WHERE brokerage_id = ANY(:ids)",
    "DELETE FROM brokerage WHERE id = ANY(:ids)",
)


@pytest.fixture(autouse=True)
def remove_committed_rows() -> Iterator[None]:
    """남긴 `RUNNING` 실행이 다른 테스트의 claim 대상이 되므로 반드시 지운다."""
    CREATED_BROKERAGES.clear()
    yield
    if not CREATED_BROKERAGES or not os.getenv("TEST_DB_URL"):
        return
    engine = create_engine(os.environ["TEST_DB_URL"], poolclass=NullPool)
    with Session(engine) as session:
        for statement in _CLEANUP_ORDER:
            session.execute(text(statement), {"ids": list(CREATED_BROKERAGES)})
        session.commit()
    engine.dispose()
    CREATED_BROKERAGES.clear()


@contextmanager
def db_session() -> Iterator[Session]:
    engine = create_engine(os.environ["TEST_DB_URL"], poolclass=NullPool)
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


class Fixture:
    """한 사무소의 단지·세대·매물·구입장과 앵커 카드를 실제로 커밋해 만든다."""

    def __init__(self, session: Session, name: str = "후보 추출 검증") -> None:
        self.session = session
        self.brokerage_id = self._scalar(
            "INSERT INTO brokerage (name) VALUES (:n) RETURNING id", n=f"{name} {uuid4().hex[:6]}"
        )
        CREATED_BROKERAGES.append(self.brokerage_id)
        self.user_id = self._scalar(
            "INSERT INTO app_user (brokerage_id, login_id, password_hash, display_name, role)"
            " VALUES (:b, :l, 'unused', '담당자', 'OWNER') RETURNING id",
            b=self.brokerage_id,
            l=f"agent-{uuid4().hex[:8]}",
        )
        self.complex_id = self._scalar(
            "INSERT INTO property_complex (brokerage_id, name) VALUES (:b, '검증단지')"
            " RETURNING id",
            b=self.brokerage_id,
        )
        self.other_complex_id = self._scalar(
            "INSERT INTO property_complex (brokerage_id, name) VALUES (:b, '다른단지')"
            " RETURNING id",
            b=self.brokerage_id,
        )
        self.unit_id = self.unit(pyeong=33)
        self.owner_party_id = self.party("김소유")
        self.listing_id = self.listing(self.unit_id, sale_price=2_880_000_000)
        self.buyer_party_id = self.party("박손님")
        self.requirement_id = self.requirement(
            self.buyer_party_id, budget=2_850_000_000, pyeongs=[33]
        )
        session.commit()

    def _scalar(self, sql: str, **params: object) -> int:
        return self.session.execute(text(sql), params).scalar_one()

    def party(self, name: str, *, deleted: bool = False) -> int:
        stored = self._scalar(
            "INSERT INTO party (brokerage_id, party_type, name, is_deleted)"
            " VALUES (:b, 'PERSON', :n, :d) RETURNING id",
            b=self.brokerage_id,
            n=name,
            d=deleted,
        )
        self.session.commit()
        return stored

    def unit(
        self, *, pyeong: int | None = 33, deleted: bool = False, complex_id: int | None = None
    ) -> int:
        stored = self._scalar(
            "INSERT INTO property_unit (brokerage_id, complex_id, unit_number, pyeong, is_deleted)"
            " VALUES (:b, :c, :u, :p, :d) RETURNING id",
            b=self.brokerage_id,
            c=complex_id or self.complex_id,
            u=uuid4().hex[:8],
            p=pyeong,
            d=deleted,
        )
        self.session.commit()
        return stored

    def listing(
        self,
        unit_id: int,
        *,
        sale_price: int | None,
        deleted: bool = False,
        received_at: date | None = None,
    ) -> int:
        stored = self._scalar(
            "INSERT INTO property_listing (brokerage_id, unit_id, is_sale_available, sale_price,"
            " is_deleted, received_at) VALUES (:b, :u, true, :s, :d, :r) RETURNING id",
            b=self.brokerage_id,
            u=unit_id,
            s=sale_price,
            d=deleted,
            r=received_at or date(2026, 8, 1),
        )
        self.session.commit()
        return stored

    def requirement(
        self,
        party_id: int,
        *,
        budget: int | None,
        pyeongs: list[int] | None = None,
        deleted: bool = False,
        received_at: date | None = None,
        complex_ids: list[int] | None = None,
    ) -> int:
        stored = self._scalar(
            "INSERT INTO property_requirement (brokerage_id, party_id, demand_type,"
            " max_budget_amount, desired_pyeongs, is_deleted, received_at)"
            " VALUES (:b, :p, '매수', :m, :y, :d, :r) RETURNING id",
            b=self.brokerage_id,
            p=party_id,
            m=budget,
            y=pyeongs,
            d=deleted,
            r=received_at or date(2026, 8, 1),
        )
        for order, complex_id in enumerate(complex_ids or []):
            self.session.execute(
                text(
                    "INSERT INTO property_requirement_complex (brokerage_id, requirement_id,"
                    " complex_id, preference_order) VALUES (:b, :r, :c, :o)"
                ),
                {"b": self.brokerage_id, "r": stored, "c": complex_id, "o": order},
            )
        self.session.commit()
        return stored

    def anchor_card(
        self,
        run_id: int,
        *,
        listing: bool,
        stated_amount: int,
        estimated_amount: int | None,
        price_kind: str = "SALE",
    ) -> int:
        """앵커 카드와 그 카드의 거래 유형별 금액. 후보 조회는 이 추정값을 쓴다."""
        card_id = self._scalar(
            "INSERT INTO negotiation_position_analysis (brokerage_id, agent_run_id,"
            " negotiation_side, unit_id, listing_id, requirement_id, cache_key, data_version)"
            " VALUES (:b, :r, :s, :u, :l, :q, :k, 1) RETURNING id",
            b=self.brokerage_id,
            r=run_id,
            s="LISTING" if listing else "REQUIREMENT",
            u=self.unit_id if listing else None,
            l=self.listing_id if listing else None,
            q=None if listing else self.requirement_id,
            k=f"test:{uuid4().hex}",
        )
        self._scalar(
            "INSERT INTO negotiation_position_price (brokerage_id, position_analysis_id,"
            " price_kind, stated_amount, estimated_amount, display_order)"
            " VALUES (:b, :p, :k, :s, :e, 0) RETURNING id",
            b=self.brokerage_id,
            p=card_id,
            k=price_kind,
            s=stated_amount,
            e=estimated_amount,
        )
        self.session.execute(
            text(
                "UPDATE agent_run SET redacted_output_snapshot ="
                " jsonb_build_object('position_analysis_id', :c) WHERE id = :r"
            ),
            {"c": card_id, "r": run_id},
        )
        self.session.commit()
        return card_id

    def run(self, *, listing: bool = True, status: str = ANCHOR_READY_STATUS) -> int:
        stored = self._scalar(
            "INSERT INTO agent_run (brokerage_id, run_group_id, run_type, agent_type, status,"
            " trigger_type, requested_by, target_listing_id, target_unit_id,"
            " target_requirement_id, input_data_version, attempt_count, lease_owner,"
            " lease_expires_at)"
            " VALUES (:b, :g, 'CROSS_JUDGMENT', 'BROKERAGE_WORKFLOW', :st, 'USER_REQUEST',"
            " :u, :l, :unit, :r, 1, :a, :owner, :exp) RETURNING id",
            b=self.brokerage_id,
            g=str(uuid4()),
            st=status,
            u=self.user_id,
            l=self.listing_id if listing else None,
            unit=self.unit_id if listing else None,
            r=None if listing else self.requirement_id,
            a=ATTEMPT,
            owner=WORKER,
            exp=datetime.now(UTC) + timedelta(minutes=5),
        )
        self.session.commit()
        return stored

    def stored_run(self, run_id: int) -> dict:
        return dict(
            self.session.execute(text("SELECT * FROM agent_run WHERE id = :i"), {"i": run_id})
            .mappings()
            .one()
        )

    def header(self) -> dict:
        return dict(
            self.session.execute(
                text("SELECT * FROM match_evaluation WHERE brokerage_id = :b"),
                {"b": self.brokerage_id},
            )
            .mappings()
            .one()
        )


@requires_database
def test_a_listing_anchor_looks_for_requirement_candidates() -> None:
    """매물 앵커는 반대편 장부인 구입장에서 후보를 찾는다."""
    with db_session() as session:
        fixture = Fixture(session)
        run_id = fixture.run(listing=True)
        fixture.anchor_card(
            run_id, listing=True, stated_amount=2_880_000_000, estimated_amount=2_800_000_000
        )

        selection = store_candidate_selection(session, run_id, WORKER, ATTEMPT, as_of=AS_OF)

        assert selection.criteria.candidate_side is AnchorType.REQUIREMENT
        assert [item.candidate_id for item in selection.ordered] == [fixture.requirement_id]
        assert fixture.stored_run(run_id)["status"] == CANDIDATES_READY_STATUS


@requires_database
def test_a_requirement_anchor_looks_for_listing_candidates() -> None:
    """구입장 앵커는 반대편 장부인 매물에서 후보를 찾는다."""
    with db_session() as session:
        fixture = Fixture(session)
        run_id = fixture.run(listing=False)
        fixture.anchor_card(
            run_id,
            listing=False,
            stated_amount=2_850_000_000,
            estimated_amount=3_000_000_000,
            price_kind="BUDGET",
        )

        selection = store_candidate_selection(session, run_id, WORKER, ATTEMPT, as_of=AS_OF)

        assert selection.criteria.candidate_side is AnchorType.LISTING
        assert [item.candidate_id for item in selection.ordered] == [fixture.listing_id]


@requires_database
def test_the_query_uses_the_card_estimate_rather_than_the_ledger_price() -> None:
    """표기 예산 28.5억이어도 추정 상한 30억이면 30억 이하를 조회한다 (F3-SQ-03)."""
    with db_session() as session:
        fixture = Fixture(session)
        # 표기 예산으로는 살 수 없지만 추정 상한으로는 닿는 매물.
        reachable_unit = fixture.unit(pyeong=33)
        reachable = fixture.listing(reachable_unit, sale_price=2_950_000_000)
        # 추정 상한에 10% 밴드를 더해도 닿지 않는 매물.
        far_unit = fixture.unit(pyeong=33)
        fixture.listing(far_unit, sale_price=9_000_000_000)

        run_id = fixture.run(listing=False)
        fixture.anchor_card(
            run_id,
            listing=False,
            stated_amount=2_850_000_000,
            estimated_amount=3_000_000_000,
            price_kind="BUDGET",
        )

        selection = store_candidate_selection(session, run_id, WORKER, ATTEMPT, as_of=AS_OF)

        found = {item.candidate_id for item in selection.ordered}
        assert reachable in found
        assert selection.criteria.price_is_estimated is True
        assert selection.criteria.price_amount == 3_000_000_000
        assert all(item.price_amount != 9_000_000_000 for item in selection.ordered)


@requires_database
def test_another_brokerage_and_deleted_rows_never_become_candidates() -> None:
    """F1 에서 보이지 않는 대상은 후보로 나오지 않는다."""
    with db_session() as session:
        fixture = Fixture(session)
        other = Fixture(session, name="다른 사무소")
        deleted_party = fixture.party("삭제된손님", deleted=True)
        deleted_requirement = fixture.requirement(deleted_party, budget=3_000_000_000)
        soft_deleted = fixture.requirement(
            fixture.party("소프트삭제"), budget=3_000_000_000, deleted=True
        )

        run_id = fixture.run(listing=True)
        fixture.anchor_card(
            run_id, listing=True, stated_amount=2_880_000_000, estimated_amount=2_800_000_000
        )

        selection = store_candidate_selection(session, run_id, WORKER, ATTEMPT, as_of=AS_OF)

        found = {item.candidate_id for item in selection.ordered}
        assert fixture.requirement_id in found
        assert deleted_requirement not in found
        assert soft_deleted not in found
        assert other.requirement_id not in found


@requires_database
def test_a_listing_whose_parent_unit_is_deleted_is_not_a_candidate() -> None:
    """세대 소프트 삭제는 매물 행을 건드리지 않으므로 매물 표시만 봐서는 안 된다."""
    with db_session() as session:
        fixture = Fixture(session)
        hidden_unit = fixture.unit(deleted=True)
        hidden = fixture.listing(hidden_unit, sale_price=2_000_000_000)

        run_id = fixture.run(listing=False)
        fixture.anchor_card(
            run_id,
            listing=False,
            stated_amount=2_850_000_000,
            estimated_amount=3_000_000_000,
            price_kind="BUDGET",
        )

        selection = store_candidate_selection(session, run_id, WORKER, ATTEMPT, as_of=AS_OF)

        assert hidden not in {item.candidate_id for item in selection.ordered}


@requires_database
def test_a_requirement_that_wants_another_complex_is_excluded() -> None:
    """희망 단지를 밝힌 손님은 그 단지의 매물에만 붙는다."""
    with db_session() as session:
        fixture = Fixture(session)
        elsewhere = fixture.requirement(
            fixture.party("다른단지손님"),
            budget=3_000_000_000,
            complex_ids=[fixture.other_complex_id],
        )
        here = fixture.requirement(
            fixture.party("같은단지손님"), budget=3_000_000_000, complex_ids=[fixture.complex_id]
        )

        run_id = fixture.run(listing=True)
        fixture.anchor_card(
            run_id, listing=True, stated_amount=2_880_000_000, estimated_amount=2_800_000_000
        )

        selection = store_candidate_selection(session, run_id, WORKER, ATTEMPT, as_of=AS_OF)

        found = {item.candidate_id for item in selection.ordered}
        assert here in found
        # 희망 단지를 아예 밝히지 않은 손님은 단지를 가리지 않으므로 남는다.
        assert fixture.requirement_id in found
        assert elsewhere not in found


@requires_database
def test_no_candidate_is_a_normal_result_that_still_stores_the_criteria() -> None:
    """후보가 0건이어도 조회 조건과 함께 정상 완료한다 (F3-CR-11)."""
    with db_session() as session:
        fixture = Fixture(session)
        # 앵커 추정가를 크게 올려 모든 구입장 예산이 하한에 미치지 못하게 만든다.
        run_id = fixture.run(listing=True)
        fixture.anchor_card(
            run_id, listing=True, stated_amount=2_880_000_000, estimated_amount=90_000_000_000
        )

        selection = store_candidate_selection(session, run_id, WORKER, ATTEMPT, as_of=AS_OF)

        assert selection.total_count == 0
        assert fixture.stored_run(run_id)["status"] == CANDIDATES_READY_STATUS
        snapshot = fixture.header()["candidate_selection_snapshot"]
        assert snapshot["total_count"] == 0
        assert snapshot["candidates"] == []
        assert snapshot["criteria"]["price_floor_amount"] == 81_000_000_000
        assert snapshot["criteria"]["price_source"] == "ESTIMATED"


@requires_database
def test_more_than_the_card_limit_preserves_the_total_and_the_remainder() -> None:
    """15건을 넘어도 컷이 아니라 페이징이다 (F3-BR-13, F3-BR-14)."""
    with db_session() as session:
        fixture = Fixture(session)
        for index in range(19):
            fixture.requirement(
                fixture.party(f"손님{index}"), budget=3_000_000_000 + index, pyeongs=[33]
            )

        run_id = fixture.run(listing=True)
        fixture.anchor_card(
            run_id, listing=True, stated_amount=2_880_000_000, estimated_amount=2_800_000_000
        )

        selection = store_candidate_selection(session, run_id, WORKER, ATTEMPT, as_of=AS_OF)

        assert selection.total_count == 20
        assert len(selection.carded) == CANDIDATE_CARD_LIMIT
        assert selection.remaining_count == 5

        header = fixture.header()
        snapshot = header["candidate_selection_snapshot"]
        assert header["candidate_count"] == CANDIDATE_CARD_LIMIT
        assert snapshot["total_count"] == 20
        assert snapshot["remaining_count"] == 5
        # 15건 이후를 조용히 지우지 않는다.
        assert len(snapshot["candidates"]) == 20
        assert [item["rank"] for item in snapshot["candidates"]] == list(range(1, 21))
        assert sum(1 for item in snapshot["candidates"] if item["selected_for_cards"]) == 15


@requires_database
def test_the_same_input_produces_the_same_order_every_time() -> None:
    """동점이 섞여 있어도 매 실행 같은 순서가 나온다."""
    with db_session() as session:
        fixture = Fixture(session)
        for index in range(6):
            fixture.requirement(fixture.party(f"동점{index}"), budget=3_000_000_000)

        run_id = fixture.run(listing=True)
        anchor_id = fixture.anchor_card(
            run_id, listing=True, stated_amount=2_880_000_000, estimated_amount=2_800_000_000
        )
        anchor = repository.find_position_card_for_target(
            session,
            fixture.brokerage_id,
            position_analysis_id=anchor_id,
            negotiation_side="LISTING",
            listing_id=fixture.listing_id,
            requirement_id=None,
        )
        assert anchor is not None

        runs = [
            [
                item.candidate_id
                for item in select_candidates(
                    session,
                    fixture.brokerage_id,
                    anchor,
                    AnchorType.LISTING,
                    as_of=AS_OF.date(),
                ).ordered
            ]
            for _ in range(3)
        ]
        assert runs[0] == runs[1] == runs[2]
        assert runs[0] == sorted(runs[0])


@requires_database
def test_a_lost_lease_stores_nothing() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        run_id = fixture.run(listing=True)
        fixture.anchor_card(
            run_id, listing=True, stated_amount=2_880_000_000, estimated_amount=2_800_000_000
        )

        with pytest.raises(LeaseNotHeldError):
            store_candidate_selection(session, run_id, "another-worker", ATTEMPT, as_of=AS_OF)

        assert fixture.stored_run(run_id)["status"] == ANCHOR_READY_STATUS


@requires_database
def test_a_changed_anchor_version_stores_nothing() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        run_id = fixture.run(listing=True)
        fixture.anchor_card(
            run_id, listing=True, stated_amount=2_880_000_000, estimated_amount=2_800_000_000
        )
        session.execute(
            text("UPDATE property_listing SET row_version = row_version + 1 WHERE id = :i"),
            {"i": fixture.listing_id},
        )
        session.commit()

        with pytest.raises(InputVersionChangedError):
            store_candidate_selection(session, run_id, WORKER, ATTEMPT, as_of=AS_OF)

        assert fixture.stored_run(run_id)["status"] == ANCHOR_READY_STATUS


@requires_database
def test_an_invalidated_anchor_card_is_not_used() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        run_id = fixture.run(listing=True)
        card_id = fixture.anchor_card(
            run_id, listing=True, stated_amount=2_880_000_000, estimated_amount=2_800_000_000
        )
        session.execute(
            text("UPDATE negotiation_position_analysis SET invalidated_at = now() WHERE id = :i"),
            {"i": card_id},
        )
        session.commit()

        with pytest.raises(AnchorCardMissingError):
            store_candidate_selection(session, run_id, WORKER, ATTEMPT, as_of=AS_OF)

        assert fixture.stored_run(run_id)["status"] == ANCHOR_READY_STATUS
