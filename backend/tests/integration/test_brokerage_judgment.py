"""중개 판정 저장과 완료 전이의 수직 슬라이스.

실제 PostgreSQL 에 붙고 AI 호출 경계만 fake generator 로 바꾼다. 확인하는 것은 다섯이다.
판정 후보를 전부 저장하는가, 기각과 사유가 남는가, 후보 집합이 어긋난 결과를 거절하는가,
실패했을 때 부분 결과가 남지 않는가, 그리고 후보 0건이 AI 없이 완료되는가.
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
    BrokerageJudgmentContractError,
    BrokerageJudgmentGeneratorVersions,
    BrokerageJudgmentRequest,
    BrokerageJudgmentResult,
    BrokerageJudgmentTarget,
    CandidateJudgment,
    ContactabilityAssessment,
    ContactabilityStatus,
    ContactChannel,
    Evidence,
    EvidenceKind,
    IntentAssessment,
    JudgmentEvidence,
    MatchGrade,
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
    RecommendedAction,
    TimingAssessment,
    Urgency,
    UrgencyAssessment,
    stated_price_for,
)
from sqlalchemy import text
from sqlmodel import Session, create_engine

from domain.agent_execution.anchor_card import GenerationBinding, GenerationBindingError
from domain.agent_execution.candidate_cards import generate_and_store_candidate_cards
from domain.agent_execution.candidates import store_candidate_selection
from domain.agent_execution.judgment import JudgmentBinding, judge_and_store
from domain.agent_execution.models import (
    ANCHOR_READY_STATUS,
    CANDIDATE_CARDS_READY_STATUS,
    COMPLETED_STATUS,
    AnchorType,
    InputVersionChangedError,
    LeaseNotHeldError,
)
from domain.agent_execution.pii_guard import ModelOutputPrivacyError

requires_database = pytest.mark.skipif(
    not os.getenv("TEST_DB_URL"),
    reason="TEST_DB_URL is required for PostgreSQL integration tests",
)

WORKER = "worker-judgment"
ATTEMPT = 1
AS_OF = datetime(2026, 8, 23, 1, 0, tzinfo=UTC)
OWNER_QUOTE = "급하게 팔 생각은 없습니다"

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
    engine = create_engine(os.environ["TEST_DB_URL"])
    with Session(engine) as session:
        for statement in _CLEANUP_ORDER:
            session.execute(text(statement), {"ids": list(CREATED_BROKERAGES)})
        session.commit()
    engine.dispose()
    CREATED_BROKERAGES.clear()


@contextmanager
def db_session() -> Iterator[Session]:
    engine = create_engine(os.environ["TEST_DB_URL"])
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


# ── 카드 생성 대역 ─────────────────────────────────────────────────────────────


def card_analysis(request: PositionCardGenerationRequest) -> PositionCardAnalysis:
    if request.consultation_logs:
        first = request.consultation_logs[0]
        evidence = (
            Evidence(
                kind=EvidenceKind.QUOTE,
                interaction_id=first.interaction_id,
                quote_text=first.masked_content[:8],
            ),
        )
    else:
        evidence = (Evidence(kind=EvidenceKind.INFERENCE, note="전달된 상담 로그가 없다"),)
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


class FakeCardGenerator:
    @property
    def versions(self) -> PositionCardGeneratorVersions:
        return PositionCardGeneratorVersions(
            prompt_version="position-card-prompt:v1",
            workflow_version="position-card-workflow:v1",
        )

    async def generate_position_card(
        self, request: PositionCardGenerationRequest
    ) -> PositionCardGenerationResult:
        return PositionCardGenerationResult(
            target=PositionCardTarget.from_request(request),
            analysis=card_analysis(request),
            prompt_version=self.versions.prompt_version,
            workflow_version=self.versions.workflow_version,
            diagnostics=ProviderDiagnostics(
                provider=ProviderKind.VLLM,
                model="fake-delegate",
                latency_ms=10.0,
                usage=TokenUsage(input_tokens=50, output_tokens=20, total_tokens=70),
            ),
        )


# ── 판정 대역 ──────────────────────────────────────────────────────────────────


def default_judgments(request: BrokerageJudgmentRequest) -> tuple[CandidateJudgment, ...]:
    """요청 후보를 전부 판정한다. 첫 후보는 강함, 나머지는 기각으로 둔다."""
    judgments = []
    for index, card in enumerate(request.candidates):
        rejected = index > 0
        judgments.append(
            CandidateJudgment(
                card_id=card.card_id,
                grade=MatchGrade.REJECTED if rejected else MatchGrade.STRONG,
                rank=index + 1,
                comparison_basis="예산 상한이 앵커 추정가에 가장 가깝다",
                primary_obstacle="가격 차",
                possible_concession="매도 측이 2천만원 조정",
                recommended_action=RecommendedAction(
                    contact_side=NegotiationSide.REQUIREMENT,
                    channel=ContactChannel.MESSAGE,
                    message="가격 조정 여지를 먼저 확인한다",
                ),
                rejection_reason="이사일이 어긋난다" if rejected else None,
                evidence=(
                    JudgmentEvidence(
                        evidence_side=request.anchor.negotiation_side,
                        field_name="price",
                        source=next(
                            Evidence(
                                kind=EvidenceKind.QUOTE,
                                interaction_id=interaction_id,
                                quote_text=quote_text,
                            )
                            for interaction_id, quote_text in sorted(request.anchor.quoted())
                        )
                        if request.anchor.quoted()
                        else Evidence(kind=EvidenceKind.INFERENCE, note="카드 값을 비교했다"),
                    ),
                ),
            )
        )
    return tuple(judgments)


class FakeJudgmentGenerator:
    """AI 판정 경계 대역. 호출 수와 받은 요청을 기록한다."""

    def __init__(self, judgments=None, *, fail: Exception | None = None) -> None:
        self.requests: list[BrokerageJudgmentRequest] = []
        self._judgments = judgments or default_judgments
        self._fail = fail

    @property
    def versions(self) -> BrokerageJudgmentGeneratorVersions:
        return BrokerageJudgmentGeneratorVersions(
            prompt_version="brokerage-judgment-prompt:v1",
            workflow_version="brokerage-judgment-workflow:v1",
        )

    @property
    def calls(self) -> int:
        return len(self.requests)

    async def judge_candidates(self, request: BrokerageJudgmentRequest) -> BrokerageJudgmentResult:
        self.requests.append(request)
        if self._fail is not None:
            raise self._fail
        return BrokerageJudgmentResult(
            target=BrokerageJudgmentTarget.from_request(request),
            candidates=self._judgments(request),
            prompt_version=self.versions.prompt_version,
            workflow_version=self.versions.workflow_version,
            diagnostics=ProviderDiagnostics(
                provider=ProviderKind.VLLM,
                model="fake-broker",
                latency_ms=55.0,
                usage=TokenUsage(input_tokens=800, output_tokens=150, total_tokens=950),
            ),
        )


class Fixture:
    """매물 앵커 하나와 구입장 후보 여럿을 `CANDIDATE_CARDS_READY` 까지 실제로 진행시킨다."""

    def __init__(self, session: Session, name: str = "판정 검증") -> None:
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
        self.card_config_id = self._model_config("POSITION_CARD", "delegate", "fake-delegate")
        self.judgment_config_id = self._model_config("BROKERAGE_JUDGMENT", "broker", "fake-broker")
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
        self.owner_party_id = self.party("김소유")
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
        # 앵커 카드에 인용 근거가 실리도록 소유자 로그를 하나 둔다.
        self._scalar(
            "INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_content,"
            " unit_id, listing_id, counterparty_role, party_id)"
            " VALUES (:b, :at, :c, :u, :l, 'OWNER', :p) RETURNING id",
            b=self.brokerage_id,
            at=datetime(2026, 8, 10, tzinfo=UTC),
            c=OWNER_QUOTE,
            u=self.unit_id,
            l=self.listing_id,
            p=self.owner_party_id,
        )
        session.commit()

    def _scalar(self, sql: str, **params: object) -> int:
        return self.session.execute(text(sql), params).scalar_one()

    def _model_config(self, capability: str, key: str, model: str) -> int:
        stored = self._scalar(
            "INSERT INTO ai_model_config (brokerage_id, capability, config_key, config_version,"
            " provider, model_name) VALUES (:b, :c, :k, 1, 'vllm', :m) RETURNING id",
            b=self.brokerage_id,
            c=capability,
            k=key,
            m=model,
        )
        self.session.commit()
        return stored

    def party(self, name: str) -> int:
        stored = self._scalar(
            "INSERT INTO party (brokerage_id, party_type, name) VALUES (:b, 'PERSON', :n)"
            " RETURNING id",
            b=self.brokerage_id,
            n=name,
        )
        self.session.commit()
        return stored

    def requirement(self, *, budget: int, party_name: str) -> int:
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

    def run_to_candidate_cards(self) -> int:
        """`CANDIDATE_CARDS_READY` 까지 실제 코드로 진행시킨다."""
        run_id = self._scalar(
            "INSERT INTO agent_run (brokerage_id, run_group_id, run_type, agent_type, status,"
            " trigger_type, requested_by, target_listing_id, target_unit_id,"
            " input_data_version, attempt_count, lease_owner, lease_expires_at)"
            " VALUES (:b, :g, 'CROSS_JUDGMENT', 'BROKERAGE_WORKFLOW', 'RUNNING', 'USER_REQUEST',"
            " :u, :l, :unit, 1, :a, :owner, :exp) RETURNING id",
            b=self.brokerage_id,
            g=str(uuid4()),
            u=self.user_id,
            l=self.listing_id,
            unit=self.unit_id,
            a=ATTEMPT,
            owner=WORKER,
            exp=datetime.now(UTC) + timedelta(minutes=5),
        )
        self.session.commit()

        from domain.agent_execution.anchor_card import generate_and_store_anchor_position_card

        binding = GenerationBinding(
            generator=FakeCardGenerator(), model_config_id=self.card_config_id
        )
        asyncio.run(
            generate_and_store_anchor_position_card(
                self.session,
                run_id=run_id,
                worker_id=WORKER,
                attempt_count=ATTEMPT,
                binding=binding,
                as_of=AS_OF,
            )
        )
        store_candidate_selection(self.session, run_id, WORKER, ATTEMPT, as_of=AS_OF)
        asyncio.run(
            generate_and_store_candidate_cards(
                self.session,
                run_id=run_id,
                worker_id=WORKER,
                attempt_count=ATTEMPT,
                binding=binding,
                as_of=AS_OF,
            )
        )
        assert self.stored_run(run_id)["status"] == CANDIDATE_CARDS_READY_STATUS
        return run_id

    def judgment_binding(self, generator: FakeJudgmentGenerator) -> JudgmentBinding:
        return JudgmentBinding(generator=generator, model_config_id=self.judgment_config_id)

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

    def candidates(self) -> list[dict]:
        return [
            dict(row)
            for row in self.session.execute(
                text(
                    "SELECT * FROM match_candidate_evaluation WHERE brokerage_id = :b"
                    " ORDER BY match_rank"
                ),
                {"b": self.brokerage_id},
            ).mappings()
        ]

    def evidence(self) -> list[dict]:
        return [
            dict(row)
            for row in self.session.execute(
                text("SELECT * FROM match_candidate_evidence WHERE brokerage_id = :b ORDER BY id"),
                {"b": self.brokerage_id},
            ).mappings()
        ]


@requires_database
def test_every_judged_candidate_is_stored_with_its_grade_and_rank() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.requirement(budget=3_000_000_000, party_name="손님A")
        fixture.requirement(budget=3_100_000_000, party_name="손님B")
        run_id = fixture.run_to_candidate_cards()
        generator = FakeJudgmentGenerator()

        stored = asyncio.run(
            judge_and_store(
                session,
                run_id=run_id,
                worker_id=WORKER,
                attempt_count=ATTEMPT,
                binding=fixture.judgment_binding(generator),
            )
        )

        assert generator.calls == 1, "교차 판정 1회당 중개 판정 LLM 호출은 1회다 (F3-NF-04)"
        assert stored.candidate_count == 2
        assert fixture.stored_run(run_id)["status"] == COMPLETED_STATUS
        assert fixture.stored_run(run_id)["completed_at"] is not None

        rows = fixture.candidates()
        assert len(rows) == 2
        assert [row["match_rank"] for row in rows] == [1, 2]
        assert rows[0]["match_grade"] == "STRONG"
        assert rows[0]["evaluation_basis"]
        assert rows[0]["primary_obstacle"] == "가격 차"
        assert rows[0]["recommended_action"]["channel"] == "MESSAGE"
        assert fixture.header()["candidate_count"] == 2


@requires_database
def test_the_anchor_card_goes_out_once_with_all_candidates() -> None:
    """앵커 1장 + 후보 N장을 한 번에 보낸다 (F3-BR-01, F3-BR-02)."""
    with db_session() as session:
        fixture = Fixture(session)
        fixture.requirement(budget=3_000_000_000, party_name="손님A")
        fixture.requirement(budget=3_100_000_000, party_name="손님B")
        run_id = fixture.run_to_candidate_cards()
        generator = FakeJudgmentGenerator()

        asyncio.run(
            judge_and_store(
                session,
                run_id=run_id,
                worker_id=WORKER,
                attempt_count=ATTEMPT,
                binding=fixture.judgment_binding(generator),
            )
        )

        request = generator.requests[0]
        assert request.anchor.negotiation_side is NegotiationSide.LISTING
        assert len(request.candidates) == 2
        assert all(
            card.negotiation_side is NegotiationSide.REQUIREMENT for card in request.candidates
        )


@requires_database
def test_a_rejected_candidate_keeps_its_reason() -> None:
    """기각도 사유와 함께 남는다. 조용히 사라지는 후보를 만들지 않는다 (F3-BR-10)."""
    with db_session() as session:
        fixture = Fixture(session)
        fixture.requirement(budget=3_000_000_000, party_name="손님A")
        fixture.requirement(budget=3_100_000_000, party_name="손님B")
        run_id = fixture.run_to_candidate_cards()

        asyncio.run(
            judge_and_store(
                session,
                run_id=run_id,
                worker_id=WORKER,
                attempt_count=ATTEMPT,
                binding=fixture.judgment_binding(FakeJudgmentGenerator()),
            )
        )

        rejected = [row for row in fixture.candidates() if row["match_grade"] == "REJECTED"]
        assert len(rejected) == 1
        assert rejected[0]["exclusion_reason"] == "이사일이 어긋난다"


@requires_database
def test_the_quote_offsets_come_from_the_stored_card_evidence() -> None:
    """판정 단계에는 상담 원문이 없다. offset 은 카드가 저장해 둔 값을 그대로 옮긴다."""
    with db_session() as session:
        fixture = Fixture(session)
        fixture.requirement(budget=3_000_000_000, party_name="손님A")
        run_id = fixture.run_to_candidate_cards()

        asyncio.run(
            judge_and_store(
                session,
                run_id=run_id,
                worker_id=WORKER,
                attempt_count=ATTEMPT,
                binding=fixture.judgment_binding(FakeJudgmentGenerator()),
            )
        )

        rows = [row for row in fixture.evidence() if row["evidence_type"] == "QUOTE"]
        assert rows, "앵커 카드의 인용을 근거로 쓴 판정이 있어야 한다"
        for row in rows:
            card_row = session.execute(
                text(
                    "SELECT quote_start_offset, quote_end_offset FROM"
                    " negotiation_position_evidence WHERE brokerage_id = :b"
                    " AND interaction_id = :i AND quote_text = :q LIMIT 1"
                ),
                {"b": fixture.brokerage_id, "i": row["interaction_id"], "q": row["quote_text"]},
            ).one()
            assert (row["quote_start_offset"], row["quote_end_offset"]) == tuple(card_row)


@requires_database
def test_no_candidate_completes_without_calling_the_model() -> None:
    """후보 0건은 AI 호출 없이 빈 최종 결과를 원자 저장하고 완료한다."""
    with db_session() as session:
        fixture = Fixture(session)
        run_id = fixture.run_to_candidate_cards()
        generator = FakeJudgmentGenerator()

        stored = asyncio.run(
            judge_and_store(
                session,
                run_id=run_id,
                worker_id=WORKER,
                attempt_count=ATTEMPT,
                binding=fixture.judgment_binding(generator),
            )
        )

        assert generator.calls == 0
        assert stored.candidate_count == 0
        assert fixture.candidates() == []
        assert fixture.header()["candidate_count"] == 0
        assert fixture.stored_run(run_id)["status"] == COMPLETED_STATUS


@requires_database
def test_a_missing_candidate_in_the_result_stores_nothing() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.requirement(budget=3_000_000_000, party_name="손님A")
        fixture.requirement(budget=3_100_000_000, party_name="손님B")
        run_id = fixture.run_to_candidate_cards()

        def drop_one(request: BrokerageJudgmentRequest) -> tuple[CandidateJudgment, ...]:
            return default_judgments(request)[:1]

        with pytest.raises(BrokerageJudgmentContractError, match="missing"):
            asyncio.run(
                judge_and_store(
                    session,
                    run_id=run_id,
                    worker_id=WORKER,
                    attempt_count=ATTEMPT,
                    binding=fixture.judgment_binding(FakeJudgmentGenerator(drop_one)),
                )
            )

        assert fixture.candidates() == []
        assert fixture.evidence() == []
        assert fixture.stored_run(run_id)["status"] != COMPLETED_STATUS


@requires_database
def test_duplicate_ranks_store_nothing() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.requirement(budget=3_000_000_000, party_name="손님A")
        fixture.requirement(budget=3_100_000_000, party_name="손님B")
        run_id = fixture.run_to_candidate_cards()

        def same_rank(request: BrokerageJudgmentRequest) -> tuple[CandidateJudgment, ...]:
            return tuple(
                candidate.model_copy(update={"rank": 1}) for candidate in default_judgments(request)
            )

        with pytest.raises(BrokerageJudgmentContractError, match="1..N"):
            asyncio.run(
                judge_and_store(
                    session,
                    run_id=run_id,
                    worker_id=WORKER,
                    attempt_count=ATTEMPT,
                    binding=fixture.judgment_binding(FakeJudgmentGenerator(same_rank)),
                )
            )

        assert fixture.candidates() == []


@requires_database
def test_personal_data_in_the_judgment_stores_nothing() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.requirement(budget=3_000_000_000, party_name="손님A")
        run_id = fixture.run_to_candidate_cards()

        def leaks(request: BrokerageJudgmentRequest) -> tuple[CandidateJudgment, ...]:
            return tuple(
                candidate.model_copy(update={"primary_obstacle": "010-1234-5678 로 연락"})
                for candidate in default_judgments(request)
            )

        with pytest.raises(ModelOutputPrivacyError):
            asyncio.run(
                judge_and_store(
                    session,
                    run_id=run_id,
                    worker_id=WORKER,
                    attempt_count=ATTEMPT,
                    binding=fixture.judgment_binding(FakeJudgmentGenerator(leaks)),
                )
            )

        assert fixture.candidates() == []
        assert fixture.stored_run(run_id)["status"] != COMPLETED_STATUS


@requires_database
def test_a_lost_lease_stores_nothing() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.requirement(budget=3_000_000_000, party_name="손님A")
        run_id = fixture.run_to_candidate_cards()

        with pytest.raises(LeaseNotHeldError):
            asyncio.run(
                judge_and_store(
                    session,
                    run_id=run_id,
                    worker_id="another-worker",
                    attempt_count=ATTEMPT,
                    binding=fixture.judgment_binding(FakeJudgmentGenerator()),
                )
            )

        assert fixture.candidates() == []
        assert fixture.stored_run(run_id)["status"] == CANDIDATE_CARDS_READY_STATUS


@requires_database
def test_a_changed_anchor_version_stores_nothing() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.requirement(budget=3_000_000_000, party_name="손님A")
        run_id = fixture.run_to_candidate_cards()
        session.execute(
            text("UPDATE property_listing SET row_version = row_version + 1 WHERE id = :i"),
            {"i": fixture.listing_id},
        )
        session.commit()

        with pytest.raises(InputVersionChangedError):
            asyncio.run(
                judge_and_store(
                    session,
                    run_id=run_id,
                    worker_id=WORKER,
                    attempt_count=ATTEMPT,
                    binding=fixture.judgment_binding(FakeJudgmentGenerator()),
                )
            )

        assert fixture.candidates() == []
        assert fixture.stored_run(run_id)["status"] == CANDIDATE_CARDS_READY_STATUS


@requires_database
def test_a_position_card_config_cannot_be_used_for_the_judgment() -> None:
    """대리와 판정은 다른 capability 설정을 쓴다 (F3-NF-10)."""
    with db_session() as session:
        fixture = Fixture(session)
        fixture.requirement(budget=3_000_000_000, party_name="손님A")
        run_id = fixture.run_to_candidate_cards()
        wrong = JudgmentBinding(
            generator=FakeJudgmentGenerator(), model_config_id=fixture.card_config_id
        )

        with pytest.raises(GenerationBindingError):
            asyncio.run(
                judge_and_store(
                    session,
                    run_id=run_id,
                    worker_id=WORKER,
                    attempt_count=ATTEMPT,
                    binding=wrong,
                )
            )

        assert fixture.stored_run(run_id)["status"] == CANDIDATE_CARDS_READY_STATUS


@requires_database
def test_another_brokerage_judgment_config_is_refused() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        other = Fixture(session, name="다른 사무소")
        fixture.requirement(budget=3_000_000_000, party_name="손님A")
        run_id = fixture.run_to_candidate_cards()
        foreign = JudgmentBinding(
            generator=FakeJudgmentGenerator(), model_config_id=other.judgment_config_id
        )

        with pytest.raises(GenerationBindingError):
            asyncio.run(
                judge_and_store(
                    session,
                    run_id=run_id,
                    worker_id=WORKER,
                    attempt_count=ATTEMPT,
                    binding=foreign,
                )
            )

        assert fixture.candidates() == []


@requires_database
def test_a_provider_failure_leaves_no_partial_result() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.requirement(budget=3_000_000_000, party_name="손님A")
        run_id = fixture.run_to_candidate_cards()
        failing = FakeJudgmentGenerator(fail=RuntimeError("provider is unavailable"))

        with pytest.raises(RuntimeError, match="provider is unavailable"):
            asyncio.run(
                judge_and_store(
                    session,
                    run_id=run_id,
                    worker_id=WORKER,
                    attempt_count=ATTEMPT,
                    binding=fixture.judgment_binding(failing),
                )
            )

        assert fixture.candidates() == []
        assert fixture.evidence() == []
        # JUDGING 까지는 갔지만 COMPLETED 가 되지 않는다. 재선점이 이어서 처리한다.
        assert fixture.stored_run(run_id)["status"] != COMPLETED_STATUS


@requires_database
def test_the_run_snapshot_carries_no_prompt_or_model_response() -> None:
    """전체 프롬프트와 전체 모델 응답은 실행에 남기지 않는다."""
    with db_session() as session:
        fixture = Fixture(session)
        fixture.requirement(budget=3_000_000_000, party_name="손님A")
        run_id = fixture.run_to_candidate_cards()

        asyncio.run(
            judge_and_store(
                session,
                run_id=run_id,
                worker_id=WORKER,
                attempt_count=ATTEMPT,
                binding=fixture.judgment_binding(FakeJudgmentGenerator()),
            )
        )

        snapshot = fixture.stored_run(run_id)["redacted_output_snapshot"]
        judgment = snapshot["judgment_result"]
        assert set(judgment) == {
            "match_evaluation_id",
            "anchor_position_analysis_id",
            "candidate_count",
            "contract_version",
            "prompt_version",
            "workflow_version",
            "provider",
            "model",
            "grades",
        }
        # 판정 바인딩은 allowlist 필드만 남는다. API key 와 endpoint 는 들어가지 않는다.
        assert set(snapshot["judgment"]["model_snapshot"]) == {
            "provider",
            "model_name",
            "model_version",
            "config_key",
            "config_version",
        }
        assert OWNER_QUOTE not in str(snapshot)


@requires_database
def test_the_candidate_side_is_the_opposite_of_the_anchor() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.requirement(budget=3_000_000_000, party_name="손님A")
        run_id = fixture.run_to_candidate_cards()

        asyncio.run(
            judge_and_store(
                session,
                run_id=run_id,
                worker_id=WORKER,
                attempt_count=ATTEMPT,
                binding=fixture.judgment_binding(FakeJudgmentGenerator()),
            )
        )

        card_ids = [row["candidate_position_analysis_id"] for row in fixture.candidates()]
        sides = session.execute(
            text(
                "SELECT DISTINCT negotiation_side FROM negotiation_position_analysis"
                " WHERE brokerage_id = :b AND id = ANY(:ids)"
            ),
            {"b": fixture.brokerage_id, "ids": card_ids},
        ).scalars()
        assert set(sides) == {AnchorType.REQUIREMENT.value}


@requires_database
def test_an_anchor_ready_run_is_not_judged() -> None:
    """단계를 건너뛰지 않는다. 기대 상태가 아니면 lease 를 잡지 못한 것으로 다룬다."""
    with db_session() as session:
        fixture = Fixture(session)
        fixture.requirement(budget=3_000_000_000, party_name="손님A")
        run_id = fixture.run_to_candidate_cards()
        session.execute(
            text("UPDATE agent_run SET status = :s WHERE id = :i"),
            {"s": ANCHOR_READY_STATUS, "i": run_id},
        )
        session.commit()

        with pytest.raises(LeaseNotHeldError):
            asyncio.run(
                judge_and_store(
                    session,
                    run_id=run_id,
                    worker_id=WORKER,
                    attempt_count=ATTEMPT,
                    binding=fixture.judgment_binding(FakeJudgmentGenerator()),
                )
            )
