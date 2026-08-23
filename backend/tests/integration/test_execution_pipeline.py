"""저장된 상태에서 이어서 처리하는 단계 오케스트레이션.

실제 PostgreSQL 에 붙고 AI 호출 경계만 fake generator 로 바꾼다. 확인하는 것은 셋이다.
`QUEUED` 하나가 끝까지 가는가, 어느 단계에서 회수해도 그 단계부터 이어지는가, 그리고
실패가 올바른 종료 상태로 옮겨지는가.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from brokerage_ai.core.errors import ProviderRateLimitError, ProviderRefusalError
from brokerage_ai.core.types import ProviderDiagnostics, ProviderKind, TokenUsage
from brokerage_ai.f3 import (
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

from domain.agent_execution import pipeline, service
from domain.agent_execution.anchor_card import GenerationBinding
from domain.agent_execution.judgment import JudgmentBinding
from domain.agent_execution.models import (
    ANCHOR_READY_STATUS,
    CANDIDATE_CARDS_READY_STATUS,
    CANDIDATES_READY_STATUS,
    COMPLETED_STATUS,
    FAILED_TERMINAL_STATUS,
    JUDGING_STATUS,
    QUEUED_STATUS,
    RUNNING_STATUS,
    SUPERSEDED_STATUS,
)
from domain.agent_execution.pipeline import StepOutcome

requires_database = pytest.mark.skipif(
    not os.getenv("TEST_DB_URL"),
    reason="TEST_DB_URL is required for PostgreSQL integration tests",
)

WORKER = "worker-pipeline"
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
    def __init__(self, *, fail: Exception | None = None) -> None:
        self.calls = 0
        self._fail = fail

    @property
    def versions(self) -> PositionCardGeneratorVersions:
        return PositionCardGeneratorVersions(
            prompt_version="position-card-prompt:v1",
            workflow_version="position-card-workflow:v1",
        )

    async def generate_position_card(
        self, request: PositionCardGenerationRequest
    ) -> PositionCardGenerationResult:
        self.calls += 1
        if self._fail is not None:
            raise self._fail
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


class FakeJudgmentGenerator:
    def __init__(self, *, fail: Exception | None = None) -> None:
        self.calls = 0
        self._fail = fail

    @property
    def versions(self) -> BrokerageJudgmentGeneratorVersions:
        return BrokerageJudgmentGeneratorVersions(
            prompt_version="brokerage-judgment-prompt:v1",
            workflow_version="brokerage-judgment-workflow:v1",
        )

    async def judge_candidates(self, request: BrokerageJudgmentRequest) -> BrokerageJudgmentResult:
        self.calls += 1
        if self._fail is not None:
            raise self._fail
        return BrokerageJudgmentResult(
            target=BrokerageJudgmentTarget.from_request(request),
            candidates=tuple(
                CandidateJudgment(
                    card_id=card.card_id,
                    grade=MatchGrade.STRONG,
                    rank=index + 1,
                    comparison_basis="예산 상한이 가장 가깝다",
                    recommended_action=RecommendedAction(
                        contact_side=card.negotiation_side,
                        channel=ContactChannel.MESSAGE,
                        message="가격 조정 여지를 확인한다",
                    ),
                    evidence=(
                        JudgmentEvidence(
                            evidence_side=card.negotiation_side,
                            source=Evidence(kind=EvidenceKind.INFERENCE, note="카드 값을 비교했다"),
                        ),
                    ),
                )
                for index, card in enumerate(request.candidates)
            ),
            prompt_version=self.versions.prompt_version,
            workflow_version=self.versions.workflow_version,
            diagnostics=ProviderDiagnostics(
                provider=ProviderKind.VLLM,
                model="fake-broker",
                latency_ms=30.0,
                usage=TokenUsage(input_tokens=400, output_tokens=90, total_tokens=490),
            ),
        )


class Fixture:
    def __init__(self, session: Session, name: str = "파이프라인 검증") -> None:
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
        complex_id = self._scalar(
            "INSERT INTO property_complex (brokerage_id, name) VALUES (:b, '검증단지')"
            " RETURNING id",
            b=self.brokerage_id,
        )
        self.unit_id = self._scalar(
            "INSERT INTO property_unit (brokerage_id, complex_id, unit_number, pyeong)"
            " VALUES (:b, :c, '1801', 33) RETURNING id",
            b=self.brokerage_id,
            c=complex_id,
        )
        owner = self._scalar(
            "INSERT INTO party (brokerage_id, party_type, name) VALUES (:b, 'PERSON', '김소유')"
            " RETURNING id",
            b=self.brokerage_id,
        )
        self._scalar(
            "INSERT INTO property_unit_party_relation (brokerage_id, unit_id, party_id, role,"
            " is_primary) VALUES (:b, :u, :p, 'OWNER', true) RETURNING id",
            b=self.brokerage_id,
            u=self.unit_id,
            p=owner,
        )
        self.listing_id = self._scalar(
            "INSERT INTO property_listing (brokerage_id, unit_id, client_party_id,"
            " is_sale_available, sale_price, received_at)"
            " VALUES (:b, :u, :p, true, 2880000000, :r) RETURNING id",
            b=self.brokerage_id,
            u=self.unit_id,
            p=owner,
            r=date(2026, 8, 1),
        )
        self._scalar(
            "INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_content,"
            " unit_id, listing_id, counterparty_role, party_id)"
            " VALUES (:b, :at, :c, :u, :l, 'OWNER', :p) RETURNING id",
            b=self.brokerage_id,
            at=datetime(2026, 8, 10, tzinfo=UTC),
            c=OWNER_QUOTE,
            u=self.unit_id,
            l=self.listing_id,
            p=owner,
        )
        buyer = self._scalar(
            "INSERT INTO party (brokerage_id, party_type, name) VALUES (:b, 'PERSON', '박손님')"
            " RETURNING id",
            b=self.brokerage_id,
        )
        self.requirement_id = self._scalar(
            "INSERT INTO property_requirement (brokerage_id, party_id, demand_type,"
            " max_budget_amount, desired_pyeongs, received_at)"
            " VALUES (:b, :p, '매수', 3000000000, ARRAY[33]::numeric[], :r) RETURNING id",
            b=self.brokerage_id,
            p=buyer,
            r=date(2026, 8, 1),
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

    def queue_run(self) -> int:
        stored = self._scalar(
            "INSERT INTO agent_run (brokerage_id, run_group_id, run_type, agent_type, status,"
            " trigger_type, requested_by, target_listing_id, target_unit_id, input_data_version)"
            " VALUES (:b, :g, 'CROSS_JUDGMENT', 'BROKERAGE_WORKFLOW', :s, 'USER_REQUEST',"
            " :u, :l, :unit, 1) RETURNING id",
            b=self.brokerage_id,
            g=str(uuid4()),
            s=QUEUED_STATUS,
            u=self.user_id,
            l=self.listing_id,
            unit=self.unit_id,
        )
        self.session.commit()
        return stored

    def bindings(
        self, card: FakeCardGenerator | None = None, judge: FakeJudgmentGenerator | None = None
    ) -> pipeline.ExecutionBindings:
        return pipeline.ExecutionBindings(
            card=GenerationBinding(
                generator=card or FakeCardGenerator(), model_config_id=self.card_config_id
            ),
            judgment=JudgmentBinding(
                generator=judge or FakeJudgmentGenerator(),
                model_config_id=self.judgment_config_id,
            ),
        )

    def status(self, run_id: int) -> str:
        return self.session.execute(
            text("SELECT status FROM agent_run WHERE id = :i"), {"i": run_id}
        ).scalar_one()

    def stored_run(self, run_id: int) -> dict:
        return dict(
            self.session.execute(text("SELECT * FROM agent_run WHERE id = :i"), {"i": run_id})
            .mappings()
            .one()
        )

    def expire_lease(self, run_id: int) -> None:
        self.session.execute(
            text(
                "UPDATE agent_run SET lease_expires_at = now() - interval '1 minute' WHERE id = :i"
            ),
            {"i": run_id},
        )
        self.session.commit()


def drive(session: Session, fixture: Fixture, run_id: int, bindings) -> StepOutcome:
    """claim 한 번으로 실행 하나를 끝까지 진행시킨다. Worker 가 하는 일과 같다."""
    loop = asyncio.new_event_loop()
    try:
        claimed = service.claim_next_run(session, WORKER)
        assert claimed is not None and claimed.id == run_id
        return pipeline.drive_run(session, claimed, WORKER, bindings, loop)
    finally:
        loop.close()


def advance_to(
    session: Session, fixture: Fixture, run_id: int, bindings, target_status: str
) -> None:
    """원하는 단계에서 멈춘 실행을 만든다. claim 은 한 번만 한다.

    `drive_run` 은 단계 하나를 마칠 때마다 정지 여부를 묻는다. 그 자리에 목표 상태 검사를
    넣으면 실제 Worker 가 정지 신호를 받은 것과 같은 경로로 멈춘다.
    """
    if fixture.status(run_id) == target_status:
        return
    loop = asyncio.new_event_loop()
    try:
        claimed = service.claim_next_run(session, WORKER)
        assert claimed is not None
        if target_status == RUNNING_STATUS:
            # claim 자체가 QUEUED 를 RUNNING 으로 옮긴다. 더 진행시키지 않는다.
            return
        pipeline.drive_run(
            session,
            claimed,
            WORKER,
            bindings,
            loop,
            should_stop=lambda: fixture.status(run_id) == target_status,
        )
    finally:
        loop.close()
    assert fixture.status(run_id) == target_status


@requires_database
def test_a_queued_run_walks_the_whole_pipeline_to_completed() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        run_id = fixture.queue_run()
        card = FakeCardGenerator()
        judge = FakeJudgmentGenerator()

        outcome = drive(session, fixture, run_id, fixture.bindings(card, judge))

        assert outcome is StepOutcome.COMPLETED
        assert fixture.status(run_id) == COMPLETED_STATUS
        # 한 번 claim 으로 끝까지 간다. 단계마다 다시 선점하지 않는다.
        assert fixture.stored_run(run_id)["attempt_count"] == 1
        # 앵커 1장 + 후보 1장 = 카드 2회, 중개 판정 1회 (F3-NF-04).
        assert card.calls == 2
        assert judge.calls == 1


@requires_database
@pytest.mark.parametrize(
    ("stalled_status", "expected_next"),
    [
        (RUNNING_STATUS, ANCHOR_READY_STATUS),
        (ANCHOR_READY_STATUS, CANDIDATES_READY_STATUS),
        (CANDIDATES_READY_STATUS, CANDIDATE_CARDS_READY_STATUS),
    ],
)
def test_a_reclaimed_run_resumes_from_its_stored_status(
    stalled_status: str, expected_next: str
) -> None:
    """회수해도 진행 상태를 잃지 않는다. 저장된 단계부터 이어서 처리한다."""
    with db_session() as session:
        fixture = Fixture(session)
        run_id = fixture.queue_run()
        bindings = fixture.bindings()
        # 원하는 단계까지 진행시킨 뒤 그 자리에서 Worker 가 죽은 상태를 만든다.
        advance_to(session, fixture, run_id, bindings, stalled_status)
        fixture.expire_lease(run_id)

        # 다른 Worker 가 회수한다. 상태는 그대로여야 한다.
        loop = asyncio.new_event_loop()
        try:
            reclaimed = service.claim_next_run(session, "worker-second")
            assert reclaimed is not None
            assert reclaimed.status == stalled_status
            outcome = pipeline.advance_run(session, reclaimed, "worker-second", bindings, loop)
        finally:
            loop.close()

        assert outcome in {StepOutcome.ADVANCED, StepOutcome.COMPLETED}
        assert fixture.status(run_id) == expected_next


@requires_database
def test_a_judging_run_without_results_is_rewound_and_retried() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        run_id = fixture.queue_run()
        bindings = fixture.bindings()
        advance_to(session, fixture, run_id, bindings, CANDIDATE_CARDS_READY_STATUS)

        # 판정 호출 도중 Worker 가 죽은 상태를 만든다.
        session.execute(
            text("UPDATE agent_run SET status = :s WHERE id = :i"),
            {"s": JUDGING_STATUS, "i": run_id},
        )
        session.commit()
        fixture.expire_lease(run_id)

        loop = asyncio.new_event_loop()
        try:
            claimed = service.claim_next_run(session, "worker-third")
            assert claimed is not None
            assert claimed.status == JUDGING_STATUS
            outcome = pipeline.advance_run(session, claimed, "worker-third", bindings, loop)
        finally:
            loop.close()

        assert outcome is StepOutcome.ADVANCED
        assert fixture.status(run_id) == CANDIDATE_CARDS_READY_STATUS


@requires_database
def test_a_changed_anchor_marks_the_run_superseded() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        run_id = fixture.queue_run()
        bindings = fixture.bindings()
        loop = asyncio.new_event_loop()
        try:
            claimed = service.claim_next_run(session, WORKER)
            assert claimed is not None
            session.execute(
                text("UPDATE property_listing SET row_version = row_version + 1 WHERE id = :i"),
                {"i": fixture.listing_id},
            )
            session.commit()
            outcome = pipeline.advance_run(session, claimed, WORKER, bindings, loop)
        finally:
            loop.close()

        assert outcome is StepOutcome.SUPERSEDED
        stored = fixture.stored_run(run_id)
        assert stored["status"] == SUPERSEDED_STATUS
        assert stored["failure_code"] == pipeline.SUPERSEDED_FAILURE_CODE
        # 공개 문구만 저장한다. raw exception 과 SQL 은 들어가지 않는다.
        assert stored["failure_message"] == pipeline.SUPERSEDED_FAILURE_MESSAGE
        assert stored["lease_owner"] is None


@requires_database
def test_a_retryable_provider_error_releases_the_lease_without_changing_status() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        run_id = fixture.queue_run()
        bindings = fixture.bindings(FakeCardGenerator(fail=ProviderRateLimitError()))
        loop = asyncio.new_event_loop()
        try:
            claimed = service.claim_next_run(session, WORKER)
            assert claimed is not None
            outcome = pipeline.advance_run(session, claimed, WORKER, bindings, loop)
        finally:
            loop.close()

        assert outcome is StepOutcome.RETRY
        stored = fixture.stored_run(run_id)
        assert stored["status"] == RUNNING_STATUS, "상태는 그대로 두고 다음 Worker 가 이어받는다"
        assert stored["failure_code"] is None
        # lease 를 즉시 놓았으므로 다음 선점이 5분을 기다리지 않는다.
        next_claim = service.claim_next_run(session, "worker-next")
        assert next_claim is not None
        assert next_claim.id == run_id


@requires_database
def test_a_terminal_provider_error_fails_the_run() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        run_id = fixture.queue_run()
        bindings = fixture.bindings(FakeCardGenerator(fail=ProviderRefusalError()))
        loop = asyncio.new_event_loop()
        try:
            claimed = service.claim_next_run(session, WORKER)
            assert claimed is not None
            outcome = pipeline.advance_run(session, claimed, WORKER, bindings, loop)
        finally:
            loop.close()

        assert outcome is StepOutcome.FAILED_TERMINAL
        stored = fixture.stored_run(run_id)
        assert stored["status"] == FAILED_TERMINAL_STATUS
        assert stored["failure_code"] == pipeline.TERMINAL_FAILURE_CODE
        assert stored["failure_message"] == pipeline.TERMINAL_FAILURE_MESSAGE


@requires_database
def test_a_lost_lease_writes_nothing() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        run_id = fixture.queue_run()
        loop = asyncio.new_event_loop()
        try:
            claimed = service.claim_next_run(session, WORKER)
            assert claimed is not None
            # 다른 Worker 가 회수해 간 뒤 이 Worker 가 저장하려 한다.
            fixture.expire_lease(run_id)
            stolen = service.claim_next_run(session, "worker-thief")
            assert stolen is not None
            outcome = pipeline.advance_run(session, claimed, WORKER, fixture.bindings(), loop)
        finally:
            loop.close()

        assert outcome is StepOutcome.LEASE_LOST
        stored = fixture.stored_run(run_id)
        assert stored["lease_owner"] == "worker-thief"
        assert stored["failure_code"] is None


@requires_database
def test_a_completed_run_is_not_claimed_again() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        run_id = fixture.queue_run()
        drive(session, fixture, run_id, fixture.bindings())
        assert fixture.status(run_id) == COMPLETED_STATUS

        fixture.expire_lease(run_id)
        claimed = service.claim_next_run(session, "worker-again")

        assert claimed is None or claimed.id != run_id


@requires_database
def test_a_run_without_an_active_model_config_fails_terminally() -> None:
    """설정 문제는 재시도해도 풀리지 않는다. 이 실행만 끝내고 loop 는 계속 돈다."""
    from worker import process_run

    class EmptyRuntime:
        providers = None

    with db_session() as session:
        fixture = Fixture(session)
        run_id = fixture.queue_run()
        session.execute(
            text("UPDATE ai_model_config SET is_active = false WHERE brokerage_id = :b"),
            {"b": fixture.brokerage_id},
        )
        session.commit()

        loop = asyncio.new_event_loop()
        try:
            claimed = service.claim_next_run(session, WORKER)
            assert claimed is not None
            outcome = process_run(session, claimed, WORKER, EmptyRuntime(), loop)  # type: ignore[arg-type]
        finally:
            loop.close()

        assert outcome is StepOutcome.FAILED_TERMINAL
        assert fixture.status(run_id) == FAILED_TERMINAL_STATUS


@requires_database
def test_a_stalled_run_over_the_attempt_limit_is_ended() -> None:
    """기존 5분 lease 와 3회 상한을 그대로 쓴다. 새 scheduler 를 만들지 않는다."""
    with db_session() as session:
        fixture = Fixture(session)
        run_id = fixture.queue_run()
        session.execute(
            text(
                "UPDATE agent_run SET status = :s, attempt_count = 3, lease_owner = 'dead',"
                " lease_expires_at = now() - interval '1 minute' WHERE id = :i"
            ),
            {"s": CANDIDATES_READY_STATUS, "i": run_id},
        )
        session.commit()

        service.claim_next_run(session, "worker-cleanup")

        stored = fixture.stored_run(run_id)
        assert stored["status"] == FAILED_TERMINAL_STATUS
        assert stored["failure_code"] == "LEASE_EXPIRED_MAX_ATTEMPTS"
        assert stored["lease_owner"] is None


@requires_database
def test_a_stalled_in_progress_run_is_reclaimed() -> None:
    """파이프라인 중간에 죽은 실행이 영영 방치되지 않는다."""
    with db_session() as session:
        fixture = Fixture(session)
        run_id = fixture.queue_run()
        session.execute(
            text(
                "UPDATE agent_run SET status = :s, attempt_count = 1, lease_owner = 'dead',"
                " lease_expires_at = now() - interval '1 minute' WHERE id = :i"
            ),
            {"s": ANCHOR_READY_STATUS, "i": run_id},
        )
        session.commit()

        claimed = service.claim_next_run(session, "worker-rescue")

        assert claimed is not None
        assert claimed.id == run_id
        assert claimed.status == ANCHOR_READY_STATUS, "회수해도 진행 상태를 되돌리지 않는다"
        assert claimed.attempt_count == 2
