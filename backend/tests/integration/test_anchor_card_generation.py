"""앵커 포지션 카드 생성·저장 수직 슬라이스 검증.

Repository 를 mock 하지 않는다. 실제 PostgreSQL 에 붙고 AI 호출 경계만 fake generator 로
바꾼다. 확인하는 것은 네 가지다. 무엇을 AI 로 보내는가, 모델을 기다리는 동안 DB 를 쥐고
있지 않은가, 저장 직전에 무엇을 다시 확인하는가, 실패하면 무엇이 남는가.
"""

from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from brokerage_ai.core.types import ProviderDiagnostics, ProviderKind, TokenUsage
from brokerage_ai.f3 import (
    ContactabilityAssessment,
    ContactabilityStatus,
    Evidence,
    EvidenceKind,
    IntentAssessment,
    ListingAnchorContext,
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
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import NullPool
from sqlmodel import Session, create_engine

from domain.agent_execution import repository
from domain.agent_execution.anchor_card import (
    AnchorPositionCardResult,
    CachedCardUnavailableError,
    GenerationBinding,
    GenerationBindingError,
    SourceChangedError,
    generate_and_store_anchor_position_card,
    prepare_generation,
    store_generated_card,
)
from domain.agent_execution.fingerprint import input_fingerprint
from domain.agent_execution.models import AnchorType, InputVersionChangedError, LeaseNotHeldError
from domain.agent_execution.pii_guard import ModelOutputPrivacyError
from domain.agent_execution.snapshot import build_anchor_snapshot

requires_database = pytest.mark.skipif(
    not os.getenv("TEST_DB_URL"),
    reason="TEST_DB_URL is required for PostgreSQL integration tests",
)

WORKER = "worker-card"
ATTEMPT = 1
OWNER_NAME = "김소유"
OWNER_PHONE = "010-1234-5678"
BUYER_NAME = "박손님"
OWNER_QUOTE = "급하게 팔 생각은 없습니다"
BUYER_QUOTE = "30억까지는 볼 수 있습니다"
AS_OF = datetime(2026, 8, 20, 1, 0, tzinfo=UTC)


# 이 파일은 실제로 커밋한다. 남긴 행은 다른 테스트의 claim 대상이 되므로 반드시 지운다.
CREATED_BROKERAGES: list[int] = []

_CLEANUP_ORDER = (
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
    """테스트가 만든 사무소의 행을 전부 지운다.

    남겨 두면 lease 가 만료된 `RUNNING` 실행이 다른 테스트의 `claim_next_run` 에 걸린다.
    실제로 그렇게 깨진 적이 있다.
    """
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
    """실제 커밋을 하는 세션. 이 슬라이스는 transaction 경계 자체가 검증 대상이다."""
    engine = create_engine(os.environ["TEST_DB_URL"], poolclass=NullPool)
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


class FakeGenerator:
    """AI 호출 경계 대역. 무엇을 받았는지 기록하고 정해진 결과를 돌려준다."""

    def __init__(
        self,
        *,
        analysis: PositionCardAnalysis | None = None,
        before_return: threading.Event | None = None,
        released: threading.Event | None = None,
    ) -> None:
        self.requests: list[PositionCardGenerationRequest] = []
        self.override_versions: PositionCardGeneratorVersions | None = None
        self._analysis = analysis
        self._before_return = before_return
        self._released = released

    @property
    def versions(self) -> PositionCardGeneratorVersions:
        return self.override_versions or PositionCardGeneratorVersions(
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
        if self._released is not None:
            # 모델을 기다리는 동안 다른 커넥션이 장부를 바꿀 수 있어야 한다.
            self._released.set()
        if self._before_return is not None:
            assert self._before_return.wait(timeout=10)
        return PositionCardGenerationResult(
            target=PositionCardTarget.from_request(request),
            analysis=self._analysis or default_analysis(request),
            prompt_version=self.versions.prompt_version,
            workflow_version=self.versions.workflow_version,
            diagnostics=ProviderDiagnostics(
                provider=ProviderKind.VLLM,
                model="fake-delegate",
                latency_ms=31.0,
                usage=TokenUsage(input_tokens=200, output_tokens=80, total_tokens=280),
            ),
        )


def quote(request: PositionCardGenerationRequest, text_value: str) -> Evidence:
    """요청에 실제로 들어 있는 로그에서 인용을 만든다."""
    for log in request.consultation_logs:
        if text_value in log.masked_content:
            return Evidence(
                kind=EvidenceKind.QUOTE, interaction_id=log.interaction_id, quote_text=text_value
            )
    raise AssertionError(f"quote {text_value!r} is not in the request")


def inference(note: str = "접촉 이력이 짧다") -> Evidence:
    return Evidence(kind=EvidenceKind.INFERENCE, note=note)


def default_analysis(request: PositionCardGenerationRequest) -> PositionCardAnalysis:
    """요청에 실제로 들어 있는 로그에서 근거를 만든다.

    로그가 없거나 표준 인용문이 없으면 추정 근거로 대체한다. 모든 테스트가 같은 본문을
    쓰지는 않는다.
    """
    body = OWNER_QUOTE if request.negotiation_side is NegotiationSide.LISTING else BUYER_QUOTE
    available = [log for log in request.consultation_logs if body in log.masked_content]
    evidence: tuple[Evidence, ...]
    if available:
        evidence = (quote(request, body),)
    elif request.consultation_logs:
        first = request.consultation_logs[0]
        evidence = (
            Evidence(
                kind=EvidenceKind.QUOTE,
                interaction_id=first.interaction_id,
                quote_text=first.masked_content[:6],
            ),
        )
    else:
        evidence = (inference("전달된 상담 로그가 없다"),)
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
        urgency=UrgencyAssessment(value=Urgency.RELAXED, evidence=evidence),
        timing=TimingAssessment(),
        flexible=(PositionCondition(description="잔금일 조정", evidence=(inference(),)),),
        contactability=ContactabilityAssessment(
            status=ContactabilityStatus.GOOD, evidence=(inference(),)
        ),
    )


class Fixture:
    """한 사무소의 매물·구입장 앵커와 선점된 실행을 실제로 커밋해 만든다."""

    def __init__(self, session: Session, name: str = "카드 생성 검증") -> None:
        self.session = session
        self.brokerage_id = self._scalar(
            "INSERT INTO brokerage (name) VALUES (:n) RETURNING id", n=f"{name} {uuid4().hex[:6]}"
        )
        CREATED_BROKERAGES.append(self.brokerage_id)
        self.login_id = f"agent-{uuid4().hex[:8]}"
        self.display_name = f"담당자{uuid4().hex[:4]}"
        self.user_id = self._scalar(
            "INSERT INTO app_user (brokerage_id, login_id, password_hash, display_name, role)"
            " VALUES (:b, :l, 'unused', :d, 'OWNER') RETURNING id",
            b=self.brokerage_id,
            l=self.login_id,
            d=self.display_name,
        )
        self.model_config_id = self._scalar(
            "INSERT INTO ai_model_config (brokerage_id, capability, config_key, config_version,"
            " provider, model_name)"
            " VALUES (:b, 'POSITION_CARD', 'delegate', 1, 'vllm', 'fake-delegate') RETURNING id",
            b=self.brokerage_id,
        )
        complex_id = self._scalar(
            "INSERT INTO property_complex (brokerage_id, name)"
            " VALUES (:b, '검증단지') RETURNING id",
            b=self.brokerage_id,
        )
        self.unit_id = self._scalar(
            "INSERT INTO property_unit (brokerage_id, complex_id, unit_number, tenancy_expiry_date)"
            " VALUES (:b, :c, '1801', :e) RETURNING id",
            b=self.brokerage_id,
            c=complex_id,
            e=date(2026, 11, 30),
        )
        self.owner_party_id = self._scalar(
            "INSERT INTO party (brokerage_id, party_type, name) VALUES (:b, 'PERSON', :n)"
            " RETURNING id",
            b=self.brokerage_id,
            n=OWNER_NAME,
        )
        self._scalar(
            "INSERT INTO party_contact (brokerage_id, party_id, contact_value,"
            " normalized_contact_value) VALUES (:b, :p, :v, :v) RETURNING id",
            b=self.brokerage_id,
            p=self.owner_party_id,
            v=OWNER_PHONE,
        )
        self._scalar(
            "INSERT INTO property_unit_party_relation (brokerage_id, unit_id, party_id, role,"
            " is_primary, is_co_owner) VALUES (:b, :u, :p, 'OWNER', true, true) RETURNING id",
            b=self.brokerage_id,
            u=self.unit_id,
            p=self.owner_party_id,
        )
        self.listing_id = self._scalar(
            "INSERT INTO property_listing (brokerage_id, unit_id, client_party_id,"
            " is_sale_available, sale_price) VALUES (:b, :u, :p, true, 2880000000) RETURNING id",
            b=self.brokerage_id,
            u=self.unit_id,
            p=self.owner_party_id,
        )
        self.buyer_party_id = self._scalar(
            "INSERT INTO party (brokerage_id, party_type, name) VALUES (:b, 'PERSON', :n)"
            " RETURNING id",
            b=self.brokerage_id,
            n=BUYER_NAME,
        )
        self.requirement_id = self._scalar(
            "INSERT INTO property_requirement (brokerage_id, party_id, demand_type,"
            " max_budget_amount) VALUES (:b, :p, '매수', 2850000000) RETURNING id",
            b=self.brokerage_id,
            p=self.buyer_party_id,
        )
        session.commit()

    def _scalar(self, sql: str, **params: object) -> int:
        return self.session.execute(text(sql), params).scalar_one()

    def another_model_config(self) -> int:
        stored = self._scalar(
            "INSERT INTO ai_model_config (brokerage_id, capability, config_key, config_version,"
            " provider, model_name)"
            " VALUES (:b, 'POSITION_CARD', 'delegate', 2, 'openai', 'other-model') RETURNING id",
            b=self.brokerage_id,
        )
        self.session.commit()
        return stored

    def interaction(
        self,
        *,
        content: str,
        at: datetime,
        listing: bool = True,
        voided: bool = False,
        party_id: int | None = None,
        attach_party: bool = True,
    ) -> int:
        """기본값은 그 측면의 당사자를 붙인다.

        세대에만 달리고 당사자도 없는 로그는 매물 대리 범위에서 제외되므로, 대부분의
        테스트가 원하는 "소유자가 한 말"을 만들려면 party 를 붙여야 한다.
        """
        if party_id is None and attach_party:
            party_id = self.owner_party_id if listing else self.buyer_party_id
        stored = self._scalar(
            "INSERT INTO client_interaction (brokerage_id, interaction_at, interaction_content,"
            " unit_id, requirement_id, is_voided, counterparty_role, party_id)"
            " VALUES (:b, :at, :c, :u, :r, :v, 'OWNER', :p) RETURNING id",
            b=self.brokerage_id,
            at=at,
            c=content,
            u=self.unit_id if listing else None,
            r=None if listing else self.requirement_id,
            v=voided,
            p=party_id,
        )
        self.session.commit()
        return stored

    def run(self, *, listing: bool = True, model_config_id: int | None = None) -> int:
        stored = self._scalar(
            "INSERT INTO agent_run (brokerage_id, run_group_id, run_type, agent_type, status,"
            " trigger_type, requested_by, target_listing_id, target_unit_id,"
            " target_requirement_id, input_data_version, attempt_count, lease_owner,"
            " lease_expires_at, model_config_id)"
            " VALUES (:b, :g, 'CROSS_JUDGMENT', 'BROKERAGE_WORKFLOW', 'RUNNING', 'USER_REQUEST',"
            " :u, :l, :unit, :r, 1, :a, :owner, :exp, :m) RETURNING id",
            b=self.brokerage_id,
            g=str(uuid4()),
            u=self.user_id,
            l=self.listing_id if listing else None,
            unit=self.unit_id if listing else None,
            r=None if listing else self.requirement_id,
            a=ATTEMPT,
            owner=WORKER,
            exp=datetime.now(UTC) + timedelta(minutes=5),
            m=model_config_id,
        )
        self.session.commit()
        return stored

    def stored_run(self, run_id: int) -> dict:
        return dict(
            self.session.execute(text("SELECT * FROM agent_run WHERE id = :i"), {"i": run_id})
            .mappings()
            .one()
        )

    def cards(self) -> list[dict]:
        return [
            dict(row)
            for row in self.session.execute(
                text(
                    "SELECT * FROM negotiation_position_analysis WHERE brokerage_id = :b"
                    " ORDER BY id"
                ),
                {"b": self.brokerage_id},
            ).mappings()
        ]

    def prices(self, analysis_id: int) -> list[dict]:
        return [
            dict(row)
            for row in self.session.execute(
                text(
                    "SELECT * FROM negotiation_position_price WHERE position_analysis_id = :i"
                    " ORDER BY display_order"
                ),
                {"i": analysis_id},
            ).mappings()
        ]

    def evidence(self, analysis_id: int) -> list[dict]:
        return [
            dict(row)
            for row in self.session.execute(
                text(
                    "SELECT * FROM negotiation_position_evidence WHERE position_analysis_id = :i"
                    " ORDER BY field_name, display_order"
                ),
                {"i": analysis_id},
            ).mappings()
        ]


def binding(generator: FakeGenerator, model_config_id: int) -> GenerationBinding:
    return GenerationBinding(generator=generator, model_config_id=model_config_id)


def run_use_case(
    session: Session, run_id: int, generator: FakeGenerator, model_config_id: int
) -> AnchorPositionCardResult:
    """유스케이스를 동기 테스트에서 돌린다. 이것 때문에 async 플러그인을 들이지 않는다."""
    return asyncio.run(
        generate_and_store_anchor_position_card(
            session,
            run_id=run_id,
            worker_id=WORKER,
            attempt_count=ATTEMPT,
            binding=binding(generator, model_config_id),
            as_of=AS_OF,
        )
    )


# --- 정상 흐름 -----------------------------------------------------------------


@requires_database
def test_listing_cache_miss_generates_stores_and_advances_to_anchor_ready() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.interaction(content=f"{OWNER_NAME} 통화. {OWNER_QUOTE}.", at=AS_OF)
        run_id = fixture.run()
        generator = FakeGenerator()

        result = run_use_case(session, run_id, generator, fixture.model_config_id)

        assert generator.calls == 1
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
def test_personal_data_is_masked_before_the_model_sees_it() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.interaction(content=f"{OWNER_NAME}({OWNER_PHONE}) 통화. {OWNER_QUOTE}.", at=AS_OF)
        generator = FakeGenerator()

        run_use_case(session, fixture.run(), generator, fixture.model_config_id)

        (request,) = generator.requests
        rendered = request.model_dump_json()
        for secret in (OWNER_NAME, OWNER_PHONE):
            assert secret not in rendered
        assert OWNER_QUOTE in rendered


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
            engine = create_engine(os.environ["TEST_DB_URL"], poolclass=NullPool)
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
        engine = create_engine(os.environ["TEST_DB_URL"], poolclass=NullPool)
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


def _analysis_with(request: PositionCardGenerationRequest, **overrides) -> PositionCardAnalysis:
    base = default_analysis(request)
    return base.model_copy(update=overrides)


@requires_database
@pytest.mark.parametrize(
    "broken",
    ["unknown_interaction", "invented_quote", "invented_deadline", "closed_price_kind"],
)
def test_a_result_that_breaks_the_contract_is_not_stored(broken: str) -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.interaction(content=f"소유자. {OWNER_QUOTE}.", at=AS_OF)
        run_id = fixture.run()

        stray = Evidence(kind=EvidenceKind.QUOTE, interaction_id=987_654, quote_text=OWNER_QUOTE)
        cases = {
            "unknown_interaction": {
                "intent": IntentAssessment(value=NegotiationIntent.PRESENT, evidence=(stray,))
            },
            "invented_quote": {
                "intent": IntentAssessment(
                    value=NegotiationIntent.PRESENT,
                    evidence=(
                        Evidence(
                            kind=EvidenceKind.QUOTE,
                            interaction_id=1,
                            quote_text="한 번도 한 적 없는 말",
                        ),
                    ),
                )
            },
            "invented_deadline": {
                "timing": TimingAssessment(
                    constraints=(PositionCondition(description="명도", evidence=(inference(),)),),
                    hard_deadline=date(2027, 1, 1),
                )
            },
            "closed_price_kind": {
                "price": (PriceAssessment(price_kind=PriceKind.JEONSE, stated_amount=None),)
            },
        }

        class BrokenGenerator(FakeGenerator):
            async def generate_position_card(self, request):  # type: ignore[override]
                override = cases[broken]
                if broken == "invented_quote":
                    override = {
                        "intent": IntentAssessment(
                            value=NegotiationIntent.PRESENT,
                            evidence=(
                                Evidence(
                                    kind=EvidenceKind.QUOTE,
                                    interaction_id=request.consultation_logs[0].interaction_id,
                                    quote_text="한 번도 한 적 없는 말",
                                ),
                            ),
                        )
                    }
                self._analysis = _analysis_with(request, **override)
                return await super().generate_position_card(request)

        with pytest.raises(Exception) as rejected:
            run_use_case(session, run_id, BrokenGenerator(), fixture.model_config_id)

        assert rejected.type.__name__ == "PositionCardContractError"
        assert fixture.cards() == []
        assert fixture.stored_run(run_id)["status"] == "RUNNING"


# --- 저장 내용 -----------------------------------------------------------------


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
            # 길이 보존 마스킹이라 마스킹 본문의 offset 이 원문의 같은 자리를 가리킨다.
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
            engine = create_engine(os.environ["TEST_DB_URL"], poolclass=NullPool)
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


# --- 대리 측면별 상담 로그 격리 -----------------------------------------------


@requires_database
def test_the_opposite_party_logs_on_the_same_unit_stay_out_of_the_listing_request() -> None:
    """같은 세대에 달렸어도 매수 희망자의 말은 매물 대리가 읽지 않는다 (F3-LA-02)."""
    with db_session() as session:
        fixture = Fixture(session)
        owner_log = fixture.interaction(
            content=f"소유자 통화. {OWNER_QUOTE}.", at=AS_OF, party_id=fixture.owner_party_id
        )
        buyer_log = fixture.interaction(
            content=f"매수 희망자 임장. {BUYER_QUOTE}.",
            at=AS_OF,
            party_id=fixture.buyer_party_id,
        )
        generator = FakeGenerator()

        result = run_use_case(session, fixture.run(), generator, fixture.model_config_id)

        (request,) = generator.requests
        identifiers = [log.interaction_id for log in request.consultation_logs]
        assert identifiers == [owner_log]
        assert buyer_log not in identifiers
        rendered = request.model_dump_json()
        assert OWNER_QUOTE in rendered
        assert BUYER_QUOTE not in rendered
        # source identity 도 걸러진 집합으로 계산돼야 한다.
        assert request.source.interaction_count == 1
        assert request.source.max_interaction_id == owner_log
        # 저장된 근거에도 반대편 로그 ID 가 없다.
        stored_evidence = fixture.evidence(result.position_analysis_id)
        assert buyer_log not in {row["interaction_id"] for row in stored_evidence}


@requires_database
def test_the_opposite_party_logs_stay_out_of_the_requirement_request() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.interaction(
            content=f"소유자 통화. {OWNER_QUOTE}.", at=AS_OF, party_id=fixture.owner_party_id
        )
        buyer_log = fixture.interaction(
            content=f"손님 상담. {BUYER_QUOTE}.",
            at=AS_OF,
            listing=False,
            party_id=fixture.buyer_party_id,
        )
        generator = FakeGenerator()

        run_use_case(session, fixture.run(listing=False), generator, fixture.model_config_id)

        (request,) = generator.requests
        assert [log.interaction_id for log in request.consultation_logs] == [buyer_log]
        rendered = request.model_dump_json()
        assert BUYER_QUOTE in rendered
        assert OWNER_QUOTE not in rendered


@requires_database
def test_a_log_carrying_a_requirement_never_enters_the_listing_scope() -> None:
    """구입장이 달린 로그는 세대에도 연결돼 있어도 수요 측이다."""
    with db_session() as session:
        fixture = Fixture(session)
        owner_log = fixture.interaction(
            content=f"소유자. {OWNER_QUOTE}.", at=AS_OF, party_id=fixture.owner_party_id
        )
        crossed = session.execute(
            text(
                "INSERT INTO client_interaction (brokerage_id, interaction_at,"
                " interaction_content, unit_id, requirement_id, party_id)"
                " VALUES (:b, :at, :c, :u, :r, :p) RETURNING id"
            ),
            {
                "b": fixture.brokerage_id,
                "at": AS_OF,
                "c": f"세대 임장 후 손님 의견. {BUYER_QUOTE}.",
                "u": fixture.unit_id,
                "r": fixture.requirement_id,
                "p": fixture.buyer_party_id,
            },
        ).scalar_one()
        session.commit()
        generator = FakeGenerator()

        run_use_case(session, fixture.run(), generator, fixture.model_config_id)

        (request,) = generator.requests
        assert [log.interaction_id for log in request.consultation_logs] == [owner_log]
        assert crossed not in {log.interaction_id for log in request.consultation_logs}


# --- 입력 개인정보 마스킹 ------------------------------------------------------


@requires_database
def test_the_requesting_user_identifiers_are_masked() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.interaction(
            content=f"{fixture.login_id}({fixture.display_name})가 남긴 메모. {OWNER_QUOTE}.",
            at=AS_OF,
            party_id=fixture.owner_party_id,
        )
        generator = FakeGenerator()

        run_use_case(session, fixture.run(), generator, fixture.model_config_id)

        rendered = generator.requests[0].model_dump_json()
        assert fixture.login_id not in rendered
        assert fixture.display_name not in rendered
        assert OWNER_QUOTE in rendered


@requires_database
def test_a_party_without_a_current_relation_is_still_masked() -> None:
    """관계가 끝난 과거 소유자의 이름도 로그에 남아 있으면 가려야 한다."""
    with db_session() as session:
        fixture = Fixture(session)
        former_name = "이전소유"
        former_party = session.execute(
            text(
                "INSERT INTO party (brokerage_id, party_type, name) VALUES (:b, 'PERSON', :n)"
                " RETURNING id"
            ),
            {"b": fixture.brokerage_id, "n": former_name},
        ).scalar_one()
        session.execute(
            text(
                "INSERT INTO property_unit_party_relation (brokerage_id, unit_id, party_id, role,"
                " role_index, valid_to) VALUES (:b, :u, :p, 'OWNER', 2, :ended)"
            ),
            {
                "b": fixture.brokerage_id,
                "u": fixture.unit_id,
                "p": former_party,
                "ended": date(2026, 1, 1),
            },
        )
        session.commit()
        fixture.interaction(
            content=f"{former_name} 명의 시절 이야기. {OWNER_QUOTE}.",
            at=AS_OF,
            party_id=former_party,
        )
        generator = FakeGenerator()

        run_use_case(session, fixture.run(), generator, fixture.model_config_id)

        rendered = generator.requests[0].model_dump_json()
        assert former_name not in rendered
        assert OWNER_QUOTE in rendered


@requires_database
def test_handover_condition_is_masked_like_the_logs() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        session.execute(
            text("UPDATE property_listing SET handover_condition = :h WHERE id = :i"),
            {
                "h": f"{OWNER_NAME} {OWNER_PHONE} owner@example.com 와 협의 후 명도",
                "i": fixture.listing_id,
            },
        )
        session.commit()
        fixture.interaction(
            content=f"소유자. {OWNER_QUOTE}.", at=AS_OF, party_id=fixture.owner_party_id
        )
        generator = FakeGenerator()

        run_use_case(session, fixture.run(), generator, fixture.model_config_id)

        anchor = generator.requests[0].anchor
        assert isinstance(anchor, ListingAnchorContext)
        handover = anchor.handover_condition
        assert handover is not None
        for secret in (OWNER_NAME, OWNER_PHONE, "owner@example.com"):
            assert secret not in handover
        assert "협의 후 명도" in handover


@requires_database
def test_masking_preserves_length_so_quote_offsets_still_land() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        original = f"{OWNER_NAME}({OWNER_PHONE}) 통화. {OWNER_QUOTE}."
        interaction_id = fixture.interaction(
            content=original, at=AS_OF, party_id=fixture.owner_party_id
        )

        result = run_use_case(session, fixture.run(), FakeGenerator(), fixture.model_config_id)

        quotes = [
            row
            for row in fixture.evidence(result.position_analysis_id)
            if row["evidence_type"] == "QUOTE"
        ]
        assert quotes
        for row in quotes:
            assert row["interaction_id"] == interaction_id
            assert original[row["quote_start_offset"] : row["quote_end_offset"]] == OWNER_QUOTE


# --- 모델 출력 개인정보 방어 ----------------------------------------------------


class _AnalysisOverridingGenerator(FakeGenerator):
    """모델이 특정 자유 문자열을 만들어 냈다고 가정한다."""

    def __init__(self, build) -> None:
        super().__init__()
        self._build = build

    async def generate_position_card(self, request):  # type: ignore[override]
        self._analysis = self._build(request, default_analysis(request))
        return await super().generate_position_card(request)


def _leaking_generators(fixture: Fixture) -> dict[str, _AnalysisOverridingGenerator]:
    def note_with_phone(request, base):
        return base.model_copy(
            update={
                "intent": IntentAssessment(
                    value=NegotiationIntent.PRESENT,
                    evidence=(Evidence(kind=EvidenceKind.INFERENCE, note=f"연락처 {OWNER_PHONE}"),),
                )
            }
        )

    def description_with_email(request, base):
        return base.model_copy(
            update={
                "flexible": (
                    PositionCondition(
                        description="메일 owner@example.com 로 협의 가능",
                        evidence=(inference(),),
                    ),
                )
            }
        )

    def note_with_display_name(request, base):
        return base.model_copy(
            update={
                "contactability": ContactabilityAssessment(
                    status=ContactabilityStatus.GOOD,
                    note=f"{fixture.display_name} 담당자가 직접 통화",
                    evidence=(inference(),),
                )
            }
        )

    return {
        "inference_note_phone": _AnalysisOverridingGenerator(note_with_phone),
        "condition_description_email": _AnalysisOverridingGenerator(description_with_email),
        "contactability_note_display_name": _AnalysisOverridingGenerator(note_with_display_name),
    }


@requires_database
@pytest.mark.parametrize(
    "case",
    ["inference_note_phone", "condition_description_email", "contactability_note_display_name"],
)
def test_personal_data_in_the_model_output_blocks_the_whole_save(case: str) -> None:
    """프롬프트 지시만으로는 부족하다. 저장 직전에 실제 문자열을 검사한다."""
    with db_session() as session:
        fixture = Fixture(session)
        fixture.interaction(
            content=f"소유자. {OWNER_QUOTE}.", at=AS_OF, party_id=fixture.owner_party_id
        )
        run_id = fixture.run()
        generator = _leaking_generators(fixture)[case]

        with pytest.raises(ModelOutputPrivacyError) as rejected:
            run_use_case(session, run_id, generator, fixture.model_config_id)

        # 오류 메시지가 곧 유출 경로가 되면 막은 의미가 없다.
        message = str(rejected.value)
        for secret in (OWNER_PHONE, "owner@example.com", fixture.display_name):
            assert secret not in message

        assert fixture.cards() == []
        assert (
            session.execute(
                text(
                    "SELECT count(*) FROM negotiation_position_price p"
                    " JOIN negotiation_position_analysis a ON a.id = p.position_analysis_id"
                    " WHERE a.brokerage_id = :b"
                ),
                {"b": fixture.brokerage_id},
            ).scalar_one()
            == 0
        )
        stored = fixture.stored_run(run_id)
        assert stored["status"] == "RUNNING"
        assert stored["redacted_output_snapshot"] == {}


@requires_database
def test_a_normal_structured_date_is_not_mistaken_for_personal_data() -> None:
    """구조화 날짜 필드를 개인정보 검사로 훼손하지 않는다."""
    with db_session() as session:
        fixture = Fixture(session)
        fixture.interaction(
            content=f"소유자. {OWNER_QUOTE}.", at=AS_OF, party_id=fixture.owner_party_id
        )

        def with_deadline(request, base):
            return base.model_copy(
                update={
                    "timing": TimingAssessment(
                        constraints=(
                            PositionCondition(
                                description="임대차 만기 전 명도", evidence=(inference(),)
                            ),
                        ),
                        hard_deadline=date(2026, 11, 30),
                    )
                }
            )

        result = run_use_case(
            session,
            fixture.run(),
            _AnalysisOverridingGenerator(with_deadline),
            fixture.model_config_id,
        )

        card = fixture.cards()[0]
        assert card["id"] == result.position_analysis_id
        assert card["preferred_timing"]["hard_deadline"] == "2026-11-30"


# --- cache hit source fencing ---------------------------------------------------


def _prepare(fixture: Fixture, run_id: int, generator: FakeGenerator):
    return prepare_generation(
        fixture.session,
        run_id,
        WORKER,
        ATTEMPT,
        binding(generator, fixture.model_config_id),
        as_of=AS_OF,
    )


@requires_database
@pytest.mark.parametrize("change", ["new_log", "backdated_log", "voided_log"])
def test_cache_hit_still_rejects_a_changed_consultation_set(change: str) -> None:
    """재사용 경로에도 fencing 이 있어야 낡은 카드가 확정되지 않는다."""
    with db_session() as session:
        fixture = Fixture(session)
        first_log = fixture.interaction(
            content=f"소유자. {OWNER_QUOTE}.", at=AS_OF, party_id=fixture.owner_party_id
        )
        run_use_case(session, fixture.run(), FakeGenerator(), fixture.model_config_id)
        before = fixture.cards()
        assert len(before) == 1

        second_run = fixture.run()
        generator = FakeGenerator()
        prepared = _prepare(fixture, second_run, generator)
        assert prepared.cached_analysis_id == before[0]["id"]
        assert prepared.request is None

        engine = create_engine(os.environ["TEST_DB_URL"], poolclass=NullPool)
        with Session(engine) as other:
            if change == "voided_log":
                other.execute(
                    text("UPDATE client_interaction SET is_voided = true WHERE id = :i"),
                    {"i": first_log},
                )
            else:
                moment = AS_OF if change == "new_log" else datetime(2026, 1, 1, tzinfo=UTC)
                other.execute(
                    text(
                        "INSERT INTO client_interaction (brokerage_id, interaction_at,"
                        " interaction_content, unit_id, party_id)"
                        " VALUES (:b, :at, '경합 중 추가된 상담', :u, :p)"
                    ),
                    {
                        "b": fixture.brokerage_id,
                        "at": moment,
                        "u": fixture.unit_id,
                        "p": fixture.owner_party_id,
                    },
                )
            other.commit()
        engine.dispose()

        with pytest.raises(SourceChangedError):
            store_generated_card(
                session,
                second_run,
                WORKER,
                ATTEMPT,
                binding(generator, fixture.model_config_id),
                prepared,
                None,
            )

        assert generator.calls == 0
        assert [card["id"] for card in fixture.cards()] == [before[0]["id"]]
        assert fixture.stored_run(second_run)["status"] == "RUNNING"


def _add_tenant_relation(fixture: Fixture, party_id: int, *, with_log: bool) -> None:
    """다른 커넥션에서 새 당사자 관계를 추가한다. AI 를 기다리는 사이에 일어나는 일이다."""
    engine = create_engine(os.environ["TEST_DB_URL"], poolclass=NullPool)
    with Session(engine) as other:
        other.execute(
            text(
                "INSERT INTO property_unit_party_relation (brokerage_id, unit_id, party_id,"
                " role, role_index) VALUES (:b, :u, :p, 'TENANT', 3)"
            ),
            {"b": fixture.brokerage_id, "u": fixture.unit_id, "p": party_id},
        )
        if with_log:
            other.execute(
                text(
                    "INSERT INTO client_interaction (brokerage_id, interaction_at,"
                    " interaction_content, unit_id, party_id)"
                    " VALUES (:b, :at, '새 임차인 상담', :u, :p)"
                ),
                {"b": fixture.brokerage_id, "at": AS_OF, "u": fixture.unit_id, "p": party_id},
            )
        other.commit()
    engine.dispose()


def _stray_party(fixture: Fixture) -> int:
    stored = fixture.session.execute(
        text(
            "INSERT INTO party (brokerage_id, party_type, name) VALUES (:b, 'PERSON', '외부인')"
            " RETURNING id"
        ),
        {"b": fixture.brokerage_id},
    ).scalar_one()
    fixture.session.commit()
    return stored


@requires_database
@pytest.mark.parametrize("with_log", [True, False], ids=["로그_추가", "관계만_추가"])
def test_a_new_party_relation_during_generation_is_rejected(with_log: bool) -> None:
    """준비 이후 당사자가 늘면 로그 수가 그대로여도 범위가 달라진 것이다.

    cache miss 경로이므로 **유효한 결과를 실제로 전달한다.** `result=None` 을 넘기면 구현이
    범위 변화를 놓쳐도 마지막의 `analysis_id` 부재에서 같은 예외가 나 통과해 버린다.
    """
    with db_session() as session:
        fixture = Fixture(session)
        fixture.interaction(content=f"소유자. {OWNER_QUOTE}.", at=AS_OF)
        run_id = fixture.run()
        stray = _stray_party(fixture)
        generator = FakeGenerator()
        prepared = _prepare(fixture, run_id, generator)
        assert prepared.request is not None
        assert prepared.source.interaction_count == 1

        # 실제로 모델을 돌려 유효한 결과를 만든다.
        result = asyncio.run(generator.generate_position_card(prepared.request))

        _add_tenant_relation(fixture, stray, with_log=with_log)

        with pytest.raises(SourceChangedError) as rejected:
            store_generated_card(
                session,
                run_id,
                WORKER,
                ATTEMPT,
                binding(generator, fixture.model_config_id),
                prepared,
                result,
            )

        # 예외가 "카드가 없다"가 아니라 범위·집합 재검증에서 나왔음을 확인한다.
        message = str(rejected.value)
        assert "scope" in message or "consultation log set" in message
        assert "no position card" not in message
        # 당사자 ID 집합 같은 민감한 값은 오류에 담기지 않는다.
        assert str(stray) not in message
        assert fixture.cards() == []
        assert fixture.stored_run(run_id)["status"] == "RUNNING"


@requires_database
def test_a_removed_party_relation_during_generation_is_rejected() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        tenant = _stray_party(fixture)
        _add_tenant_relation(fixture, tenant, with_log=False)
        fixture.interaction(content=f"소유자. {OWNER_QUOTE}.", at=AS_OF)
        run_id = fixture.run()
        generator = FakeGenerator()
        prepared = _prepare(fixture, run_id, generator)
        assert prepared.request is not None
        result = asyncio.run(generator.generate_position_card(prepared.request))

        engine = create_engine(os.environ["TEST_DB_URL"], poolclass=NullPool)
        with Session(engine) as other:
            other.execute(
                text(
                    "DELETE FROM property_unit_party_relation"
                    " WHERE brokerage_id = :b AND party_id = :p"
                ),
                {"b": fixture.brokerage_id, "p": tenant},
            )
            other.commit()
        engine.dispose()

        with pytest.raises(SourceChangedError):
            store_generated_card(
                session,
                run_id,
                WORKER,
                ATTEMPT,
                binding(generator, fixture.model_config_id),
                prepared,
                result,
            )
        assert fixture.cards() == []
        assert fixture.stored_run(run_id)["status"] == "RUNNING"


@requires_database
def test_a_cache_hit_also_detects_a_party_relation_change() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.interaction(content=f"소유자. {OWNER_QUOTE}.", at=AS_OF)
        run_use_case(session, fixture.run(), FakeGenerator(), fixture.model_config_id)
        before = fixture.cards()
        assert len(before) == 1

        second_run = fixture.run()
        generator = FakeGenerator()
        prepared = _prepare(fixture, second_run, generator)
        assert prepared.cached_analysis_id == before[0]["id"]

        _add_tenant_relation(fixture, _stray_party(fixture), with_log=False)

        with pytest.raises(SourceChangedError):
            store_generated_card(
                session,
                second_run,
                WORKER,
                ATTEMPT,
                binding(generator, fixture.model_config_id),
                prepared,
                None,
            )

        assert generator.calls == 0
        assert [card["id"] for card in fixture.cards()] == [before[0]["id"]]
        assert fixture.stored_run(second_run)["status"] == "RUNNING"


@requires_database
def test_a_normal_cache_hit_reuses_the_card_and_records_the_versions() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.interaction(
            content=f"소유자. {OWNER_QUOTE}.", at=AS_OF, party_id=fixture.owner_party_id
        )
        first = run_use_case(session, fixture.run(), FakeGenerator(), fixture.model_config_id)

        second_run = fixture.run()
        generator = FakeGenerator()
        second = run_use_case(session, second_run, generator, fixture.model_config_id)

        assert generator.calls == 0
        assert second.position_analysis_id == first.position_analysis_id
        assert len(fixture.cards()) == 1
        stored = fixture.stored_run(second_run)
        snapshot_row = stored["redacted_output_snapshot"]
        assert snapshot_row["cache_hit"] is True
        # cache hit 이어도 버전과 모델 정보가 null 로 남지 않는다.
        assert snapshot_row["contract_version"] == "position-card:v1"
        assert snapshot_row["prompt_version"] == "position-card-prompt:v1"
        assert snapshot_row["workflow_version"] == "position-card-workflow:v1"
        assert snapshot_row["provider"] == "vllm"
        assert snapshot_row["model"] == "fake-delegate"


# --- 실행 모델 바인딩 ----------------------------------------------------------


@requires_database
def test_the_first_run_records_the_whole_execution_binding() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.interaction(
            content=f"소유자. {OWNER_QUOTE}.", at=AS_OF, party_id=fixture.owner_party_id
        )
        run_id = fixture.run()
        assert fixture.stored_run(run_id)["model_config_id"] is None

        run_use_case(session, run_id, FakeGenerator(), fixture.model_config_id)

        stored = fixture.stored_run(run_id)
        assert stored["model_config_id"] == fixture.model_config_id
        assert stored["prompt_version"] == "position-card-prompt:v1"
        assert stored["workflow_version"] == "position-card-workflow:v1"
        assert stored["model_snapshot"] == {
            "provider": "vllm",
            "model_name": "fake-delegate",
            "model_version": None,
            "config_key": "delegate",
            "config_version": 1,
        }
        # allowlist 밖의 비밀 계열 값은 어떤 이름으로도 들어오지 않는다.
        assert not {"api_key", "token", "endpoint", "endpoint_alias", "secret"} & set(
            stored["model_snapshot"]
        )


@requires_database
def test_the_same_binding_may_retry_but_a_different_one_is_refused() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.interaction(
            content=f"소유자. {OWNER_QUOTE}.", at=AS_OF, party_id=fixture.owner_party_id
        )
        run_id = fixture.run()
        run_use_case(session, run_id, FakeGenerator(), fixture.model_config_id)
        session.execute(
            text("UPDATE agent_run SET status = 'RUNNING' WHERE id = :i"), {"i": run_id}
        )
        session.commit()

        # 같은 binding 은 다시 통과한다.
        run_use_case(session, run_id, FakeGenerator(), fixture.model_config_id)
        assert fixture.stored_run(run_id)["status"] == "ANCHOR_READY"


@requires_database
@pytest.mark.parametrize("difference", ["model_config", "prompt_version", "workflow_version"])
def test_a_changed_binding_on_retry_is_refused(difference: str) -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.interaction(
            content=f"소유자. {OWNER_QUOTE}.", at=AS_OF, party_id=fixture.owner_party_id
        )
        run_id = fixture.run()
        run_use_case(session, run_id, FakeGenerator(), fixture.model_config_id)
        session.execute(
            text("UPDATE agent_run SET status = 'RUNNING' WHERE id = :i"), {"i": run_id}
        )
        session.commit()
        cards_before = len(fixture.cards())

        generator = FakeGenerator()
        model_config_id = fixture.model_config_id
        if difference == "model_config":
            model_config_id = fixture.another_model_config()
        else:
            other = "other:v9"
            generator.override_versions = (
                PositionCardGeneratorVersions(
                    prompt_version=other, workflow_version="position-card-workflow:v1"
                )
                if difference == "prompt_version"
                else PositionCardGeneratorVersions(
                    prompt_version="position-card-prompt:v1", workflow_version=other
                )
            )

        with pytest.raises(GenerationBindingError):
            run_use_case(session, run_id, generator, model_config_id)

        assert generator.calls == 0
        assert len(fixture.cards()) == cards_before
        assert fixture.stored_run(run_id)["status"] == "RUNNING"


@requires_database
def test_a_model_config_from_another_brokerage_is_refused() -> None:
    """존재 여부를 구분해서 알리지 않는다. 없는 설정과 남의 설정이 같은 오류다."""
    with db_session() as session:
        fixture = Fixture(session)
        theirs = Fixture(session, name="남의 사무소")
        fixture.interaction(
            content=f"소유자. {OWNER_QUOTE}.", at=AS_OF, party_id=fixture.owner_party_id
        )
        run_id = fixture.run()
        generator = FakeGenerator()

        with pytest.raises(GenerationBindingError) as foreign:
            run_use_case(session, run_id, generator, theirs.model_config_id)
        with pytest.raises(GenerationBindingError) as missing:
            run_use_case(session, run_id, generator, 987_654_321)

        assert str(foreign.value) == str(missing.value)
        assert generator.calls == 0
        assert fixture.cards() == []
        assert fixture.stored_run(run_id)["model_config_id"] is None


@requires_database
def test_a_run_with_a_half_written_binding_is_refused() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.interaction(
            content=f"소유자. {OWNER_QUOTE}.", at=AS_OF, party_id=fixture.owner_party_id
        )
        run_id = fixture.run()
        session.execute(
            text("UPDATE agent_run SET prompt_version = 'stray:v1' WHERE id = :i"), {"i": run_id}
        )
        session.commit()
        generator = FakeGenerator()

        with pytest.raises(GenerationBindingError):
            run_use_case(session, run_id, generator, fixture.model_config_id)

        assert generator.calls == 0
        assert fixture.cards() == []
        assert fixture.stored_run(run_id)["model_config_id"] is None


# --- target label --------------------------------------------------------------


@requires_database
def test_the_listing_label_uses_structured_ledger_values() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.interaction(
            content=f"소유자. {OWNER_QUOTE}.", at=AS_OF, party_id=fixture.owner_party_id
        )

        result = run_use_case(session, fixture.run(), FakeGenerator(), fixture.model_config_id)

        assert result.target_label == "검증단지 1801호"
        assert fixture.cards()[0]["target_label"] == "검증단지 1801호"


@requires_database
def test_the_requirement_label_carries_no_party_name() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.interaction(
            content=f"손님. {BUYER_QUOTE}.",
            at=AS_OF,
            listing=False,
            party_id=fixture.buyer_party_id,
        )

        result = run_use_case(
            session, fixture.run(listing=False), FakeGenerator(), fixture.model_config_id
        )

        label = fixture.cards()[0]["target_label"]
        assert label == f"구입장 #{fixture.requirement_id}"
        assert result.target_label == label
        assert BUYER_NAME not in label


def test_the_model_cannot_produce_a_target_label() -> None:
    from brokerage_ai.f3.model_output import PositionCardModelOutput

    assert "target_label" not in set(PositionCardModelOutput.model_fields)
    assert "target" not in set(PositionCardModelOutput.model_fields)


@requires_database
def test_a_tampered_target_label_is_refused() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.interaction(
            content=f"소유자. {OWNER_QUOTE}.", at=AS_OF, party_id=fixture.owner_party_id
        )

        class TamperingGenerator(FakeGenerator):
            async def generate_position_card(self, request):  # type: ignore[override]
                produced = await super().generate_position_card(request)
                return produced.model_copy(
                    update={
                        "target": produced.target.model_copy(update={"target_label": "다른 라벨"})
                    }
                )

        with pytest.raises(Exception) as rejected:
            run_use_case(session, fixture.run(), TamperingGenerator(), fixture.model_config_id)

        assert rejected.type.__name__ == "PositionCardContractError"
        assert "target label" in str(rejected.value)
        assert fixture.cards() == []


# --- 준비 단계 transaction 종료 --------------------------------------------------


@requires_database
@pytest.mark.parametrize("failure", ["lease", "binding", "anchor_version"])
def test_a_domain_error_in_preparation_closes_the_transaction(failure: str) -> None:
    """도메인 오류에서도 transaction 을 남기면 이 커넥션이 잠긴 채 AI 를 기다리게 된다."""
    with db_session() as session:
        fixture = Fixture(session)
        fixture.interaction(
            content=f"소유자. {OWNER_QUOTE}.", at=AS_OF, party_id=fixture.owner_party_id
        )
        run_id = fixture.run()
        worker = WORKER
        model_config_id = fixture.model_config_id
        expected: type[Exception] = LeaseNotHeldError

        if failure == "lease":
            worker = "someone-else"
        elif failure == "binding":
            model_config_id = 987_654_321
            expected = GenerationBindingError
        else:
            session.execute(
                text("UPDATE property_listing SET row_version = 99 WHERE id = :i"),
                {"i": fixture.listing_id},
            )
            session.commit()
            expected = InputVersionChangedError

        with pytest.raises(expected):
            prepare_generation(
                session,
                run_id,
                worker,
                ATTEMPT,
                binding(FakeGenerator(), model_config_id),
                as_of=AS_OF,
            )

        assert session.in_transaction() is False


@requires_database
def test_a_successful_preparation_leaves_no_open_transaction() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.interaction(
            content=f"소유자. {OWNER_QUOTE}.", at=AS_OF, party_id=fixture.owner_party_id
        )

        prepared = _prepare(fixture, fixture.run(), FakeGenerator())

        assert prepared.request is not None
        assert session.in_transaction() is False


# --- 전체 입력 변경 감지 ---------------------------------------------------------


def _mutate_in_another_session(sql: str, **params: object) -> None:
    engine = create_engine(os.environ["TEST_DB_URL"], poolclass=NullPool)
    with Session(engine) as other:
        other.execute(text(sql), params)
        other.commit()
    engine.dispose()


@requires_database
@pytest.mark.parametrize(
    "change",
    ["unit_field", "complex_name", "party_role", "party_is_co_owner"],
)
def test_a_model_input_change_outside_the_listing_row_is_rejected(change: str) -> None:
    """`listing.row_version` 은 그대로여도 모델 입력이 달라지면 저장하지 않는다."""
    with db_session() as session:
        fixture = Fixture(session)
        fixture.interaction(content=f"소유자. {OWNER_QUOTE}.", at=AS_OF)
        run_id = fixture.run()
        generator = FakeGenerator()
        prepared = _prepare(fixture, run_id, generator)
        assert prepared.request is not None
        result = asyncio.run(generator.generate_position_card(prepared.request))
        version_before = session.execute(
            text("SELECT row_version FROM property_listing WHERE id = :i"),
            {"i": fixture.listing_id},
        ).scalar_one()

        mutations = {
            "unit_field": (
                "UPDATE property_unit SET tenancy_status = '임대차 있음' WHERE id = :i",
                {"i": fixture.unit_id},
            ),
            "complex_name": (
                "UPDATE property_complex SET name = '이름이 바뀐 단지'"
                " WHERE id = (SELECT complex_id FROM property_unit WHERE id = :i)",
                {"i": fixture.unit_id},
            ),
            "party_role": (
                "UPDATE property_unit_party_relation SET role = 'TENANT'"
                " WHERE brokerage_id = :b AND party_id = :p",
                {"b": fixture.brokerage_id, "p": fixture.owner_party_id},
            ),
            "party_is_co_owner": (
                "UPDATE property_unit_party_relation SET is_co_owner = NOT is_co_owner"
                " WHERE brokerage_id = :b AND party_id = :p",
                {"b": fixture.brokerage_id, "p": fixture.owner_party_id},
            ),
        }
        sql, params = mutations[change]
        _mutate_in_another_session(sql, **params)

        with pytest.raises(SourceChangedError) as rejected:
            store_generated_card(
                session,
                run_id,
                WORKER,
                ATTEMPT,
                binding(generator, fixture.model_config_id),
                prepared,
                result,
            )

        assert "no position card" not in str(rejected.value)
        # 앵커 row_version 은 그대로다. 이것만 봤다면 통과했을 변경이다.
        assert (
            session.execute(
                text("SELECT row_version FROM property_listing WHERE id = :i"),
                {"i": fixture.listing_id},
            ).scalar_one()
            == version_before
        )
        assert fixture.cards() == []
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
def test_a_cache_hit_also_detects_a_unit_field_change() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.interaction(content=f"소유자. {OWNER_QUOTE}.", at=AS_OF)
        run_use_case(session, fixture.run(), FakeGenerator(), fixture.model_config_id)
        before = fixture.cards()

        second_run = fixture.run()
        generator = FakeGenerator()
        prepared = _prepare(fixture, second_run, generator)
        assert prepared.cached_analysis_id == before[0]["id"]

        _mutate_in_another_session(
            "UPDATE property_unit SET orientation = '남향' WHERE id = :i", i=fixture.unit_id
        )

        with pytest.raises(SourceChangedError):
            store_generated_card(
                session,
                second_run,
                WORKER,
                ATTEMPT,
                binding(generator, fixture.model_config_id),
                prepared,
                None,
            )
        assert generator.calls == 0
        assert [card["id"] for card in fixture.cards()] == [before[0]["id"]]
        assert fixture.stored_run(second_run)["status"] == "RUNNING"


@requires_database
def test_a_later_date_bucket_does_not_reuse_yesterdays_card() -> None:
    """날짜가 넘어가면 `days_since`·`days_until` 이 달라져 재사용하지 않는다."""
    with db_session() as session:
        fixture = Fixture(session)
        fixture.interaction(content=f"소유자. {OWNER_QUOTE}.", at=AS_OF)
        first = run_use_case(session, fixture.run(), FakeGenerator(), fixture.model_config_id)

        tomorrow = AS_OF + timedelta(days=1)
        generator = FakeGenerator()
        prepared = prepare_generation(
            session,
            fixture.run(),
            WORKER,
            ATTEMPT,
            binding(generator, fixture.model_config_id),
            as_of=tomorrow,
        )

        assert prepared.cached_analysis_id is None
        assert prepared.request is not None
        assert prepared.as_of_bucket == tomorrow.date().isoformat()
        assert prepared.cache_key != fixture.cards()[0]["cache_key"]
        assert first.position_analysis_id == fixture.cards()[0]["id"]


@requires_database
def test_the_same_day_reuses_the_card_even_at_a_different_instant() -> None:
    """같은 날 안의 다른 시각까지 cache miss 로 만들면 캐시가 무의미해진다."""
    with db_session() as session:
        fixture = Fixture(session)
        fixture.interaction(content=f"소유자. {OWNER_QUOTE}.", at=AS_OF)
        first = run_use_case(session, fixture.run(), FakeGenerator(), fixture.model_config_id)

        generator = FakeGenerator()
        prepared = prepare_generation(
            session,
            fixture.run(),
            WORKER,
            ATTEMPT,
            binding(generator, fixture.model_config_id),
            as_of=AS_OF + timedelta(hours=6),
        )

        assert prepared.cached_analysis_id == first.position_analysis_id
        assert prepared.request is None


@requires_database
def test_equivalent_instants_in_different_timezones_build_the_same_snapshot() -> None:
    """UTC bucket이 같으면 파생 날짜 신호와 실제 AI 요청도 같아야 한다."""
    with db_session() as session:
        fixture = Fixture(session)
        fixture.interaction(content=f"소유자. {OWNER_QUOTE}.", at=AS_OF)
        instant = datetime(2026, 8, 20, 16, 0, tzinfo=UTC)
        same_in_korea = instant.astimezone(timezone(timedelta(hours=9)))

        utc_snapshot = build_anchor_snapshot(
            session,
            fixture.brokerage_id,
            AnchorType.LISTING,
            fixture.listing_id,
            as_of=instant,
            requested_by=fixture.user_id,
        )
        korea_snapshot = build_anchor_snapshot(
            session,
            fixture.brokerage_id,
            AnchorType.LISTING,
            fixture.listing_id,
            as_of=same_in_korea,
            requested_by=fixture.user_id,
        )

        assert utc_snapshot.request == korea_snapshot.request
        assert utc_snapshot.request.date_signals.as_of == instant
        assert input_fingerprint(utc_snapshot.request) == input_fingerprint(korea_snapshot.request)


# --- cache hit 카드 활성 상태 재검증 ----------------------------------------------


@requires_database
def test_an_invalidated_card_is_not_reused_after_preparation() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.interaction(content=f"소유자. {OWNER_QUOTE}.", at=AS_OF)
        first = run_use_case(session, fixture.run(), FakeGenerator(), fixture.model_config_id)

        second_run = fixture.run()
        generator = FakeGenerator()
        prepared = _prepare(fixture, second_run, generator)
        assert prepared.cached_analysis_id == first.position_analysis_id

        _mutate_in_another_session(
            "UPDATE negotiation_position_analysis SET invalidated_at = now(),"
            " invalidation_reason = '검증' WHERE id = :i",
            i=first.position_analysis_id,
        )

        with pytest.raises(CachedCardUnavailableError):
            store_generated_card(
                session,
                second_run,
                WORKER,
                ATTEMPT,
                binding(generator, fixture.model_config_id),
                prepared,
                None,
            )

        assert generator.calls == 0
        stored = fixture.stored_run(second_run)
        assert stored["status"] == "RUNNING"
        # 무효화된 카드 ID 가 실행 snapshot 에 남으면 안 된다.
        assert stored["redacted_output_snapshot"] == {}


@requires_database
def test_a_store_lock_serializes_concurrent_cache_invalidation() -> None:
    """활성 확인 뒤 무효화가 끼어들어 무효 카드로 상태를 확정하면 안 된다."""
    with db_session() as session:
        fixture = Fixture(session)
        fixture.interaction(content=f"소유자. {OWNER_QUOTE}.", at=AS_OF)
        first = run_use_case(session, fixture.run(), FakeGenerator(), fixture.model_config_id)
        prepared = _prepare(fixture, fixture.run(), FakeGenerator())
        assert prepared.cached_analysis_id == first.position_analysis_id

        locked = repository.lock_active_position_card_for_store(
            session,
            fixture.brokerage_id,
            cache_key=prepared.cache_key,
            negotiation_side=prepared.negotiation_side.value,
            listing_id=prepared.anchor_id,
            requirement_id=None,
            data_version=prepared.data_version,
            interactions=repository.InteractionSummary(
                prepared.source.interaction_count,
                prepared.source.last_interaction_at,
                prepared.source.max_interaction_id,
            ),
        )
        assert locked is not None and locked.id == first.position_analysis_id

        engine = create_engine(os.environ["TEST_DB_URL"], poolclass=NullPool)
        with Session(engine) as invalidator:
            invalidator.execute(text("SET LOCAL lock_timeout = '250ms'"))
            with pytest.raises(DBAPIError) as blocked:
                invalidator.execute(
                    text(
                        "UPDATE negotiation_position_analysis SET invalidated_at = now()"
                        " WHERE brokerage_id = :b AND id = :i"
                    ),
                    {"b": fixture.brokerage_id, "i": first.position_analysis_id},
                )
            assert getattr(blocked.value.orig, "sqlstate", None) == "55P03"
            invalidator.rollback()
        engine.dispose()

        session.rollback()
        assert fixture.cards()[0]["invalidated_at"] is None


@requires_database
def test_another_brokerage_card_with_the_same_cache_key_is_never_reused() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        theirs = Fixture(session, name="남의 사무소")
        fixture.interaction(content=f"소유자. {OWNER_QUOTE}.", at=AS_OF)
        run_id = fixture.run()
        generator = FakeGenerator()
        prepared = _prepare(fixture, run_id, generator)
        assert prepared.cached_analysis_id is None

        # 남의 사무소에 같은 cache key 를 가진 카드를 심는다.
        _mutate_in_another_session(
            "INSERT INTO negotiation_position_analysis (brokerage_id, agent_run_id,"
            " negotiation_side, listing_id, unit_id, cache_key, data_version)"
            " VALUES (:b, :r, 'LISTING', :l, :u, :k, 1)",
            b=theirs.brokerage_id,
            r=theirs.run(),
            l=theirs.listing_id,
            u=theirs.unit_id,
            k=prepared.cache_key,
        )

        reprepared = _prepare(fixture, run_id, FakeGenerator())

        assert reprepared.cached_analysis_id is None
        assert reprepared.request is not None


# --- 모델 바인딩 전체 fencing -----------------------------------------------------


@requires_database
def test_the_model_snapshot_is_part_of_the_binding_fence() -> None:
    """AI 를 기다리는 사이 model_snapshot 이 바뀌면 결과를 저장하지 않는다."""
    with db_session() as session:
        fixture = Fixture(session)
        fixture.interaction(content=f"소유자. {OWNER_QUOTE}.", at=AS_OF)
        run_id = fixture.run()
        generator = FakeGenerator()
        prepared = _prepare(fixture, run_id, generator)
        assert prepared.request is not None
        result = asyncio.run(generator.generate_position_card(prepared.request))

        _mutate_in_another_session(
            'UPDATE agent_run SET model_snapshot = \'{"provider": "tampered"}\'::jsonb'
            " WHERE id = :i",
            i=run_id,
        )

        with pytest.raises(GenerationBindingError):
            store_generated_card(
                session,
                run_id,
                WORKER,
                ATTEMPT,
                binding(generator, fixture.model_config_id),
                prepared,
                result,
            )

        assert fixture.cards() == []
        assert (
            session.execute(
                text("SELECT count(*) FROM negotiation_position_evidence WHERE brokerage_id = :b"),
                {"b": fixture.brokerage_id},
            ).scalar_one()
            == 0
        )
        assert fixture.stored_run(run_id)["status"] == "RUNNING"


@requires_database
@pytest.mark.parametrize(
    "corruption",
    [
        "snapshot_only",
        "prompt_only",
        "config_and_prompt",
    ],
)
def test_a_partially_bound_run_is_never_overwritten(corruption: str) -> None:
    """미바인딩은 세 버전이 NULL 이고 snapshot 이 빈 객체인 상태뿐이다."""
    with db_session() as session:
        fixture = Fixture(session)
        fixture.interaction(content=f"소유자. {OWNER_QUOTE}.", at=AS_OF)
        run_id = fixture.run()
        corruptions = {
            "snapshot_only": (
                'UPDATE agent_run SET model_snapshot = \'{"provider": "stray"}\'::jsonb'
                " WHERE id = :i",
                {"i": run_id},
            ),
            "prompt_only": (
                "UPDATE agent_run SET prompt_version = 'stray:v1' WHERE id = :i",
                {"i": run_id},
            ),
            "config_and_prompt": (
                "UPDATE agent_run SET model_config_id = :m, prompt_version = 'stray:v1'"
                " WHERE id = :i",
                {"i": run_id, "m": fixture.model_config_id},
            ),
        }
        sql, params = corruptions[corruption]
        session.execute(text(sql), params)
        session.commit()
        before = fixture.stored_run(run_id)
        generator = FakeGenerator()

        with pytest.raises(GenerationBindingError):
            run_use_case(session, run_id, generator, fixture.model_config_id)

        assert generator.calls == 0
        after = fixture.stored_run(run_id)
        # 손상된 행을 새 바인딩으로 덮지 않는다.
        assert after["model_config_id"] == before["model_config_id"]
        assert after["prompt_version"] == before["prompt_version"]
        assert after["workflow_version"] == before["workflow_version"]
        assert after["model_snapshot"] == before["model_snapshot"]
        assert fixture.cards() == []
        assert after["status"] == "RUNNING"


@requires_database
def test_an_unbound_run_has_an_empty_snapshot_not_a_null_one() -> None:
    """DB 기본값이 `{}` 라 "네 값이 NULL" 이라는 판정은 성립하지 않는다."""
    with db_session() as session:
        fixture = Fixture(session)
        run_id = fixture.run()

        stored = fixture.stored_run(run_id)

        assert stored["model_config_id"] is None
        assert stored["prompt_version"] is None
        assert stored["workflow_version"] is None
        assert stored["model_snapshot"] == {}


# --- party_id NULL 로그의 측면 격리 -----------------------------------------------


def _insert_log(fixture: Fixture, **columns: object) -> int:
    fields = {"brokerage_id": fixture.brokerage_id, "interaction_at": AS_OF, **columns}
    names = ", ".join(fields)
    binds = ", ".join(f":{name}" for name in fields)
    stored = fixture.session.execute(
        text(f"INSERT INTO client_interaction ({names}) VALUES ({binds}) RETURNING id"), fields
    ).scalar_one()
    fixture.session.commit()
    return stored


@requires_database
def test_the_listing_scope_takes_explicit_listing_logs_even_without_a_party() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        explicit = _insert_log(
            fixture,
            interaction_content="매물 건에 직접 남긴 메모",
            unit_id=fixture.unit_id,
            listing_id=fixture.listing_id,
        )
        generator = FakeGenerator()

        run_use_case(session, fixture.run(), generator, fixture.model_config_id)

        assert [log.interaction_id for log in generator.requests[0].consultation_logs] == [explicit]


@requires_database
def test_the_listing_scope_drops_an_ambiguous_unit_only_log() -> None:
    """세대에만 달리고 당사자도 없는 로그는 수요 측 상담일 수 있어 받지 않는다."""
    with db_session() as session:
        fixture = Fixture(session)
        ambiguous = _insert_log(
            fixture, interaction_content="누가 한 말인지 알 수 없는 메모", unit_id=fixture.unit_id
        )
        allowed = _insert_log(
            fixture,
            interaction_content="소유자가 한 말",
            unit_id=fixture.unit_id,
            party_id=fixture.owner_party_id,
        )
        generator = FakeGenerator()

        run_use_case(session, fixture.run(), generator, fixture.model_config_id)

        identifiers = [log.interaction_id for log in generator.requests[0].consultation_logs]
        assert identifiers == [allowed]
        assert ambiguous not in identifiers


@requires_database
def test_the_listing_scope_drops_a_unit_log_from_an_outside_party() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        allowed = _insert_log(
            fixture,
            interaction_content="소유자가 한 말",
            unit_id=fixture.unit_id,
            party_id=fixture.owner_party_id,
        )
        outsider = _insert_log(
            fixture,
            interaction_content="매수 희망자가 한 말",
            unit_id=fixture.unit_id,
            party_id=fixture.buyer_party_id,
        )
        with_requirement = _insert_log(
            fixture,
            interaction_content="구입장이 달린 말",
            unit_id=fixture.unit_id,
            requirement_id=fixture.requirement_id,
        )
        generator = FakeGenerator()

        run_use_case(session, fixture.run(), generator, fixture.model_config_id)

        identifiers = [log.interaction_id for log in generator.requests[0].consultation_logs]
        assert identifiers == [allowed]
        assert outsider not in identifiers
        assert with_requirement not in identifiers


@requires_database
def test_the_requirement_scope_takes_its_own_logs_only() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        mine_without_party = _insert_log(
            fixture,
            interaction_content="구입장에 남긴 메모",
            requirement_id=fixture.requirement_id,
        )
        mine_with_party = _insert_log(
            fixture,
            interaction_content="손님이 한 말",
            requirement_id=fixture.requirement_id,
            party_id=fixture.buyer_party_id,
        )
        other_requirement = session.execute(
            text(
                "INSERT INTO property_requirement (brokerage_id, party_id, demand_type)"
                " VALUES (:b, :p, '전세') RETURNING id"
            ),
            {"b": fixture.brokerage_id, "p": fixture.buyer_party_id},
        ).scalar_one()
        session.commit()
        stray = _insert_log(
            fixture,
            interaction_content="다른 구입장 상담",
            requirement_id=other_requirement,
            party_id=fixture.buyer_party_id,
        )
        generator = FakeGenerator()

        run_use_case(session, fixture.run(listing=False), generator, fixture.model_config_id)

        identifiers = [log.interaction_id for log in generator.requests[0].consultation_logs]
        assert sorted(identifiers) == sorted([mine_without_party, mine_with_party])
        assert stray not in identifiers
