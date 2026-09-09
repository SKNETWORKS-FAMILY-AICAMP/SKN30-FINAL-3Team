"""중개 판정 저장과 완료 전이의 수직 슬라이스.

실제 PostgreSQL 에 붙고 AI 호출 경계만 fake generator 로 바꾼다. 확인하는 것은 다섯이다.
판정 후보를 전부 저장하는가, 기각과 사유가 남는가, 후보 집합이 어긋난 결과를 거절하는가,
실패했을 때 부분 결과가 남지 않는가, 그리고 후보 0건이 AI 없이 완료되는가.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

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
    InferenceEvidence,
    InputPrivacyMode,
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
    QuoteEvidence,
    RecommendedAction,
    TimingAssessment,
    Urgency,
    UrgencyAssessment,
    stated_price_for,
)
from f3_committed_db import CREATED_BROKERAGES
from sqlalchemy import text
from sqlmodel import Session

from domain.agent_execution.anchor_card import GenerationBinding
from domain.agent_execution.candidate_cards import generate_and_store_candidate_cards
from domain.agent_execution.candidates import store_candidate_selection
from domain.agent_execution.judgment import (
    JudgmentBinding,
)
from domain.agent_execution.models import (
    CANDIDATE_CARDS_READY_STATUS,
)

WORKER = "worker-judgment"
ATTEMPT = 1
AS_OF = datetime(2026, 8, 23, 1, 0, tzinfo=UTC)
OWNER_QUOTE = "급하게 팔 생각은 없습니다"

# ── 카드 생성 대역 ─────────────────────────────────────────────────────────────


def card_analysis(request: PositionCardGenerationRequest) -> PositionCardAnalysis:
    if request.consultation_logs:
        first = request.consultation_logs[0]
        evidence = (
            QuoteEvidence(
                interaction_id=first.interaction_id,
                quote_text=first.masked_content[:8],
            ),
        )
    else:
        evidence = (InferenceEvidence(note="전달된 상담 로그가 없다"),)
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
                evidence=(InferenceEvidence(note="정황"),),
            ),
        ),
        contactability=ContactabilityAssessment(
            status=ContactabilityStatus.GOOD,
            evidence=(InferenceEvidence(note="정황"),),
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
                            QuoteEvidence(
                                interaction_id=interaction_id,
                                quote_text=quote_text,
                            )
                            for interaction_id, quote_text in sorted(request.anchor.quoted())
                        )
                        if request.anchor.quoted()
                        else InferenceEvidence(note="카드 값을 비교했다"),
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
            generator=FakeCardGenerator(),
            model_config_id=self.card_config_id,
            input_privacy_mode=InputPrivacyMode.SYNTHETIC_PROTOTYPE,
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
        return JudgmentBinding(
            generator=generator,
            model_config_id=self.judgment_config_id,
            input_privacy_mode=InputPrivacyMode.SYNTHETIC_PROTOTYPE,
        )

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
