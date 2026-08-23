"""후보 포지션 카드 확보 단계의 수직 슬라이스.

실제 PostgreSQL 에 붙고 AI 호출 경계만 fake generator 로 바꾼다. 확인하는 것은 넷이다.
반대편 측면으로 카드를 만드는가, 캐시를 실제로 재사용하는가, 반대편 상담 로그가 섞이지
않는가, 그리고 하나라도 실패하면 완료 상태로 넘어가지 않는가.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from brokerage_ai.core.types import ProviderDiagnostics, ProviderKind, TokenUsage
from brokerage_ai.f3 import (
    ContactabilityAssessment,
    ContactabilityStatus,
    Evidence,
    EvidenceKind,
    IntentAssessment,
    NegotiationIntent,
    NegotiationSide,
    PositionCardAnalysis,
    PositionCardGenerationRequest,
    PositionCardGenerationResult,
    PositionCardGeneratorVersions,
    PositionCardTarget,
    PositionCondition,
    PriceAssessment,
    PriceKind,
    TimingAssessment,
    Urgency,
    UrgencyAssessment,
    stated_price_for,
)
from sqlalchemy import text
from sqlalchemy.pool import NullPool
from sqlmodel import Session, create_engine

from domain.agent_execution.anchor_card import GenerationBinding, SourceChangedError
from domain.agent_execution.candidate_cards import (
    generate_and_store_candidate_cards,
    plan_candidate_cards,
)
from domain.agent_execution.candidates import store_candidate_selection
from domain.agent_execution.models import (
    ANCHOR_READY_STATUS,
    CANDIDATE_CARDS_READY_STATUS,
    CANDIDATES_READY_STATUS,
    AnchorType,
    LeaseNotHeldError,
)

requires_database = pytest.mark.skipif(
    not os.getenv("TEST_DB_URL"),
    reason="TEST_DB_URL is required for PostgreSQL integration tests",
)

WORKER = "worker-candidate-cards"
ATTEMPT = 1
AS_OF = datetime(2026, 8, 23, 1, 0, tzinfo=UTC)
OWNER_NAME = "김소유"
BUYER_NAME = "박손님"
OWNER_QUOTE = "급하게 팔 생각은 없습니다"
BUYER_QUOTE = "30억까지는 볼 수 있습니다"

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


def _evidence(request: PositionCardGenerationRequest) -> tuple[Evidence, ...]:
    if request.consultation_logs:
        first = request.consultation_logs[0]
        return (
            Evidence(
                kind=EvidenceKind.QUOTE,
                interaction_id=first.interaction_id,
                quote_text=first.masked_content[:6],
            ),
        )
    return (Evidence(kind=EvidenceKind.INFERENCE, note="전달된 상담 로그가 없다"),)


def default_analysis(request: PositionCardGenerationRequest) -> PositionCardAnalysis:
    evidence = _evidence(request)
    prices = []
    for kind in PriceKind:
        stated, monthly = stated_price_for(request.anchor, kind)
        if stated is None and monthly is None:
            continue
        prices.append(
            PriceAssessment(price_kind=kind, stated_amount=stated, stated_monthly_amount=monthly)
        )
    return PositionCardAnalysis(
        intent=IntentAssessment(value=NegotiationIntent.PRESENT, evidence=evidence),
        price=tuple(prices),
        urgency=UrgencyAssessment(value=Urgency.NORMAL, evidence=evidence),
        timing=TimingAssessment(),
        flexible=(
            PositionCondition(
                description="잔금일 조정",
                evidence=(Evidence(kind=EvidenceKind.INFERENCE, note="정황"),),
            ),
        ),
        contactability=ContactabilityAssessment(
            status=ContactabilityStatus.GOOD,
            evidence=(Evidence(kind=EvidenceKind.INFERENCE, note="정황"),),
        ),
    )


class FakeGenerator:
    """AI 호출 경계 대역. 무엇을 받았는지 기록한다."""

    def __init__(self, *, fail_on_anchor_id: int | None = None) -> None:
        self.requests: list[PositionCardGenerationRequest] = []
        self._fail_on_anchor_id = fail_on_anchor_id

    @property
    def versions(self) -> PositionCardGeneratorVersions:
        return PositionCardGeneratorVersions(
            prompt_version="position-card-prompt:v1",
            workflow_version="position-card-workflow:v1",
        )

    @property
    def calls(self) -> int:
        return len(self.requests)

    async def generate_position_card(
        self, request: PositionCardGenerationRequest
    ) -> PositionCardGenerationResult:
        self.requests.append(request)
        if self._fail_on_anchor_id == request.anchor_id:
            raise RuntimeError("provider is unavailable")
        return PositionCardGenerationResult(
            target=PositionCardTarget.from_request(request),
            analysis=default_analysis(request),
            prompt_version=self.versions.prompt_version,
            workflow_version=self.versions.workflow_version,
            diagnostics=ProviderDiagnostics(
                provider=ProviderKind.VLLM,
                model="fake-delegate",
                latency_ms=12.0,
                usage=TokenUsage(input_tokens=100, output_tokens=40, total_tokens=140),
            ),
        )


class Fixture:
    """매물 앵커 하나와 구입장 후보 여럿을 실제로 커밋해 만든다."""

    def __init__(self, session: Session, name: str = "후보 카드 검증") -> None:
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
        self.model_config_id = self._scalar(
            "INSERT INTO ai_model_config (brokerage_id, capability, config_key, config_version,"
            " provider, model_name)"
            " VALUES (:b, 'POSITION_CARD', 'delegate', 1, 'vllm', 'fake-delegate') RETURNING id",
            b=self.brokerage_id,
        )
        self.complex_id = self._scalar(
            "INSERT INTO property_complex (brokerage_id, name) VALUES (:b, '검증단지')"
            " RETURNING id",
            b=self.brokerage_id,
        )
        self.unit_id = self._scalar(
            "INSERT INTO property_unit (brokerage_id, complex_id, unit_number, pyeong)"
            " VALUES (:b, :c, '1801', 33) RETURNING id",
            b=self.brokerage_id,
            c=self.complex_id,
        )
        self.owner_party_id = self.party(OWNER_NAME)
        self._scalar(
            "INSERT INTO property_unit_party_relation (brokerage_id, unit_id, party_id, role,"
            " is_primary) VALUES (:b, :u, :p, 'OWNER', true) RETURNING id",
            b=self.brokerage_id,
            u=self.unit_id,
            p=self.owner_party_id,
        )
        self.listing_id = self._scalar(
            "INSERT INTO property_listing (brokerage_id, unit_id, client_party_id,"
            " is_sale_available, sale_price, received_at)"
            " VALUES (:b, :u, :p, true, 2880000000, :r) RETURNING id",
            b=self.brokerage_id,
            u=self.unit_id,
            p=self.owner_party_id,
            r=date(2026, 8, 1),
        )
        session.commit()

    def _scalar(self, sql: str, **params: object) -> int:
        return self.session.execute(text(sql), params).scalar_one()

    def party(self, name: str) -> int:
        stored = self._scalar(
            "INSERT INTO party (brokerage_id, party_type, name) VALUES (:b, 'PERSON', :n)"
            " RETURNING id",
            b=self.brokerage_id,
            n=name,
        )
        self.session.commit()
        return stored

    def requirement(self, *, budget: int, party_name: str = BUYER_NAME) -> int:
        stored = self._scalar(
            "INSERT INTO property_requirement (brokerage_id, party_id, demand_type,"
            " max_budget_amount, desired_pyeongs, received_at)"
            " VALUES (:b, :p, '매수', :m, ARRAY[33]::numeric[], :r) RETURNING id",
            b=self.brokerage_id,
            p=self.party(party_name),
            m=budget,
            r=date(2026, 8, 1),
        )
        self.session.commit()
        return stored

    def interaction(
        self, *, content: str, at: datetime, requirement_id: int | None, party_id: int
    ) -> int:
        stored = self._scalar(
            "INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_content,"
            " unit_id, requirement_id, counterparty_role, party_id)"
            " VALUES (:b, :at, :c, :u, :r, 'OWNER', :p) RETURNING id",
            b=self.brokerage_id,
            at=at,
            c=content,
            u=self.unit_id if requirement_id is None else None,
            r=requirement_id,
            p=party_id,
        )
        self.session.commit()
        return stored

    def run(self) -> int:
        stored = self._scalar(
            "INSERT INTO agent_run (brokerage_id, run_group_id, run_type, agent_type, status,"
            " trigger_type, requested_by, target_listing_id, target_unit_id,"
            " input_data_version, attempt_count, lease_owner, lease_expires_at)"
            " VALUES (:b, :g, 'CROSS_JUDGMENT', 'BROKERAGE_WORKFLOW', :st, 'USER_REQUEST',"
            " :u, :l, :unit, 1, :a, :owner, :exp) RETURNING id",
            b=self.brokerage_id,
            g=str(uuid4()),
            st=ANCHOR_READY_STATUS,
            u=self.user_id,
            l=self.listing_id,
            unit=self.unit_id,
            a=ATTEMPT,
            owner=WORKER,
            exp=datetime.now(UTC) + timedelta(minutes=5),
        )
        self.session.commit()
        return stored

    def anchor_card(self, run_id: int, *, estimated: int = 2_800_000_000) -> int:
        card_id = self._scalar(
            "INSERT INTO negotiation_position_analysis (brokerage_id, agent_run_id,"
            " negotiation_side, unit_id, listing_id, cache_key, data_version)"
            " VALUES (:b, :r, 'LISTING', :u, :l, :k, 1) RETURNING id",
            b=self.brokerage_id,
            r=run_id,
            u=self.unit_id,
            l=self.listing_id,
            k=f"test:{uuid4().hex}",
        )
        self._scalar(
            "INSERT INTO negotiation_position_price (brokerage_id, position_analysis_id,"
            " price_kind, stated_amount, estimated_amount, display_order)"
            " VALUES (:b, :p, 'SALE', 2880000000, :e, 0) RETURNING id",
            b=self.brokerage_id,
            p=card_id,
            e=estimated,
        )
        self.session.execute(
            text(
                "UPDATE agent_run SET redacted_output_snapshot ="
                " jsonb_build_object('position_analysis_id', :c),"
                " model_config_id = :m, model_snapshot = CAST(:s AS jsonb),"
                " prompt_version = 'position-card-prompt:v1',"
                " workflow_version = 'position-card-workflow:v1' WHERE id = :r"
            ),
            {
                "c": card_id,
                "r": run_id,
                "m": self.model_config_id,
                "s": (
                    '{"provider": "vllm", "model_name": "fake-delegate", "model_version": null,'
                    ' "config_key": "delegate", "config_version": 1}'
                ),
            },
        )
        self.session.commit()
        return card_id

    def prepared_run(self) -> int:
        """`CANDIDATES_READY` 까지 실제 코드로 진행시킨다."""
        run_id = self.run()
        self.anchor_card(run_id)
        store_candidate_selection(self.session, run_id, WORKER, ATTEMPT, as_of=AS_OF)
        return run_id

    def stored_run(self, run_id: int) -> dict:
        return dict(
            self.session.execute(text("SELECT * FROM agent_run WHERE id = :i"), {"i": run_id})
            .mappings()
            .one()
        )

    def snapshot(self) -> dict:
        return dict(
            self.session.execute(
                text(
                    "SELECT candidate_selection_snapshot AS s FROM match_evaluation"
                    " WHERE brokerage_id = :b"
                ),
                {"b": self.brokerage_id},
            )
            .mappings()
            .one()
        )["s"]

    def cards(self, side: str) -> list[dict]:
        return [
            dict(row)
            for row in self.session.execute(
                text(
                    "SELECT * FROM negotiation_position_analysis WHERE brokerage_id = :b"
                    " AND negotiation_side = :s ORDER BY id"
                ),
                {"b": self.brokerage_id, "s": side},
            ).mappings()
        ]


def binding_for(fixture: Fixture, generator: FakeGenerator) -> GenerationBinding:
    return GenerationBinding(generator=generator, model_config_id=fixture.model_config_id)


@requires_database
def test_candidate_cards_use_the_opposite_negotiation_side() -> None:
    """매물 앵커의 후보 카드는 구입장 측면으로 만들어진다."""
    with db_session() as session:
        fixture = Fixture(session)
        requirement_id = fixture.requirement(budget=3_000_000_000)
        run_id = fixture.prepared_run()
        generator = FakeGenerator()

        result = asyncio.run(
            generate_and_store_candidate_cards(
                session,
                run_id=run_id,
                worker_id=WORKER,
                attempt_count=ATTEMPT,
                binding=binding_for(fixture, generator),
                as_of=AS_OF,
            )
        )

        assert {card.candidate_id for card in result.cards} == {requirement_id}
        assert result.generated_count == 1
        assert fixture.stored_run(run_id)["status"] == CANDIDATE_CARDS_READY_STATUS

        cards = fixture.cards("REQUIREMENT")
        assert len(cards) == 1
        assert cards[0]["requirement_id"] == requirement_id
        assert cards[0]["listing_id"] is None
        # 후보 카드는 루트 실행에 직접 귀속한다. child run 을 만들지 않는다.
        assert cards[0]["agent_run_id"] == run_id
        assert all(
            request.negotiation_side is NegotiationSide.REQUIREMENT
            for request in generator.requests
        )


@requires_database
def test_the_candidate_side_never_sees_the_anchor_side_logs() -> None:
    """반대편 격리. 소유자의 말은 손님 대리 입력에 들어가지 않는다 (F3-CA-02)."""
    with db_session() as session:
        fixture = Fixture(session)
        requirement_id = fixture.requirement(budget=3_000_000_000)
        buyer_party = fixture.session.execute(
            text("SELECT party_id FROM property_requirement WHERE id = :i"), {"i": requirement_id}
        ).scalar_one()
        fixture.interaction(
            content=OWNER_QUOTE,
            at=datetime(2026, 8, 10, tzinfo=UTC),
            requirement_id=None,
            party_id=fixture.owner_party_id,
        )
        fixture.interaction(
            content=BUYER_QUOTE,
            at=datetime(2026, 8, 11, tzinfo=UTC),
            requirement_id=requirement_id,
            party_id=buyer_party,
        )

        run_id = fixture.prepared_run()
        generator = FakeGenerator()
        asyncio.run(
            generate_and_store_candidate_cards(
                session,
                run_id=run_id,
                worker_id=WORKER,
                attempt_count=ATTEMPT,
                binding=binding_for(fixture, generator),
                as_of=AS_OF,
            )
        )

        assert generator.calls == 1
        bodies = [log.masked_content for log in generator.requests[0].consultation_logs]
        assert BUYER_QUOTE in bodies
        assert OWNER_QUOTE not in bodies


@requires_database
def test_a_cached_candidate_card_is_reused_without_calling_the_model() -> None:
    """데이터 변경이 없으면 카드를 다시 만들지 않는다 (F3-PC-12)."""
    with db_session() as session:
        fixture = Fixture(session)
        fixture.requirement(budget=3_000_000_000)
        run_id = fixture.prepared_run()
        generator = FakeGenerator()
        binding = binding_for(fixture, generator)

        asyncio.run(
            generate_and_store_candidate_cards(
                session,
                run_id=run_id,
                worker_id=WORKER,
                attempt_count=ATTEMPT,
                binding=binding,
                as_of=AS_OF,
            )
        )
        assert generator.calls == 1

        # 같은 입력으로 두 번째 실행을 만든다. 후보 카드는 캐시에서 나와야 한다.
        second_run = fixture.prepared_run()
        second = asyncio.run(
            generate_and_store_candidate_cards(
                session,
                run_id=second_run,
                worker_id=WORKER,
                attempt_count=ATTEMPT,
                binding=binding,
                as_of=AS_OF,
            )
        )

        assert generator.calls == 1, "cache hit 이면 모델을 부르지 않는다"
        assert second.cache_hit_count == 1
        assert second.generated_count == 0
        assert len(fixture.cards("REQUIREMENT")) == 1


@requires_database
def test_no_candidate_skips_the_model_and_still_advances() -> None:
    """후보 0건이면 모델 호출 없이 다음 단계로 넘어간다."""
    with db_session() as session:
        fixture = Fixture(session)
        run_id = fixture.prepared_run()
        generator = FakeGenerator()

        result = asyncio.run(
            generate_and_store_candidate_cards(
                session,
                run_id=run_id,
                worker_id=WORKER,
                attempt_count=ATTEMPT,
                binding=binding_for(fixture, generator),
                as_of=AS_OF,
            )
        )

        assert generator.calls == 0
        assert result.cards == ()
        assert fixture.stored_run(run_id)["status"] == CANDIDATE_CARDS_READY_STATUS
        assert fixture.snapshot()["candidate_cards"] == []


@requires_database
def test_one_failed_candidate_does_not_advance_the_run() -> None:
    """일부 후보만 성공한 상태를 완료로 처리하지 않는다."""
    with db_session() as session:
        fixture = Fixture(session)
        first = fixture.requirement(budget=3_000_000_000, party_name="손님A")
        second = fixture.requirement(budget=3_100_000_000, party_name="손님B")
        run_id = fixture.prepared_run()
        # 점수가 높은 쪽이 먼저 처리되므로 두 후보 중 하나는 반드시 뒤에 온다.
        generator = FakeGenerator(fail_on_anchor_id=max(first, second))

        with pytest.raises(RuntimeError, match="provider is unavailable"):
            asyncio.run(
                generate_and_store_candidate_cards(
                    session,
                    run_id=run_id,
                    worker_id=WORKER,
                    attempt_count=ATTEMPT,
                    binding=binding_for(fixture, generator),
                    as_of=AS_OF,
                )
            )

        assert fixture.stored_run(run_id)["status"] == CANDIDATES_READY_STATUS
        assert "candidate_cards" not in fixture.snapshot()


@requires_database
def test_a_candidate_changed_during_generation_is_not_stored() -> None:
    """후보 장부가 바뀌면 그 입력으로 만든 카드를 저장하지 않는다."""
    with db_session() as session:
        fixture = Fixture(session)
        requirement_id = fixture.requirement(budget=3_000_000_000)
        run_id = fixture.prepared_run()

        class ChangingGenerator(FakeGenerator):
            async def generate_position_card(
                self, request: PositionCardGenerationRequest
            ) -> PositionCardGenerationResult:
                produced = await super().generate_position_card(request)
                # 모델을 기다리는 사이 후보의 상담 로그가 늘어난다.
                with db_session() as other:
                    other.execute(
                        text(
                            "INSERT INTO client_interaction (brokerage_id, interaction_at,"
                            " interaction_content, requirement_id, party_id)"
                            " SELECT :b, now(), '조건이 바뀌었습니다', :r, party_id"
                            " FROM property_requirement WHERE id = :r"
                        ),
                        {"b": fixture.brokerage_id, "r": requirement_id},
                    )
                    other.commit()
                return produced

        with pytest.raises(SourceChangedError):
            asyncio.run(
                generate_and_store_candidate_cards(
                    session,
                    run_id=run_id,
                    worker_id=WORKER,
                    attempt_count=ATTEMPT,
                    binding=binding_for(fixture, ChangingGenerator()),
                    as_of=AS_OF,
                )
            )

        assert fixture.cards("REQUIREMENT") == []
        assert fixture.stored_run(run_id)["status"] == CANDIDATES_READY_STATUS


@requires_database
def test_a_lost_lease_stores_no_candidate_card() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.requirement(budget=3_000_000_000)
        run_id = fixture.prepared_run()

        with pytest.raises(LeaseNotHeldError):
            asyncio.run(
                generate_and_store_candidate_cards(
                    session,
                    run_id=run_id,
                    worker_id="another-worker",
                    attempt_count=ATTEMPT,
                    binding=binding_for(fixture, FakeGenerator()),
                    as_of=AS_OF,
                )
            )

        assert fixture.cards("REQUIREMENT") == []
        assert fixture.stored_run(run_id)["status"] == CANDIDATES_READY_STATUS


@requires_database
def test_the_plan_only_covers_the_carded_top_candidates() -> None:
    """상위 15건만 카드화 대상이고 나머지는 snapshot 에 남는다."""
    with db_session() as session:
        fixture = Fixture(session)
        for index in range(18):
            fixture.requirement(budget=3_000_000_000 + index, party_name=f"손님{index}")
        run_id = fixture.prepared_run()

        plan = plan_candidate_cards(session, run_id, WORKER, ATTEMPT)

        assert plan.candidate_side is AnchorType.REQUIREMENT
        assert len(plan.candidate_ids) == 15
        assert fixture.snapshot()["total_count"] == 18
