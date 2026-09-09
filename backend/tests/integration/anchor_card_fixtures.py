"""앵커 포지션 카드 생성·저장 수직 슬라이스 검증.

Repository 를 mock 하지 않는다. 실제 PostgreSQL 에 붙고 AI 호출 경계만 fake generator 로
바꾼다. 확인하는 것은 네 가지다. 무엇을 AI 로 보내는가, 모델을 기다리는 동안 DB 를 쥐고
있지 않은가, 저장 직전에 무엇을 다시 확인하는가, 실패하면 무엇이 남는가.
"""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from brokerage_ai.core.types import ProviderDiagnostics, ProviderKind, TokenUsage
from brokerage_ai.f3 import (
    ContactabilityAssessment,
    ContactabilityStatus,
    Evidence,
    InferenceEvidence,
    InputPrivacyMode,
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
    QuoteEvidence,
    TimingAssessment,
    Urgency,
    UrgencyAssessment,
    stated_price_for,
)
from f3_committed_db import CREATED_BROKERAGES
from sqlalchemy import text
from sqlmodel import Session

from domain.agent_execution.anchor_card import (
    AnchorPositionCardResult,
    GenerationBinding,
    generate_and_store_anchor_position_card,
)

WORKER = "worker-card"
ATTEMPT = 1
OWNER_NAME = "김소유"
OWNER_PHONE = "010-1234-5678"
BUYER_NAME = "박손님"
OWNER_QUOTE = "급하게 팔 생각은 없습니다"
BUYER_QUOTE = "30억까지는 볼 수 있습니다"
AS_OF = datetime(2026, 8, 20, 1, 0, tzinfo=UTC)


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
            return QuoteEvidence(interaction_id=log.interaction_id, quote_text=text_value)
    raise AssertionError(f"quote {text_value!r} is not in the request")


def inference(note: str = "접촉 이력이 짧다") -> Evidence:
    return InferenceEvidence(note=note)


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
            QuoteEvidence(
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
    return GenerationBinding(
        generator=generator,
        model_config_id=model_config_id,
        input_privacy_mode=InputPrivacyMode.SYNTHETIC_PROTOTYPE,
    )


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
