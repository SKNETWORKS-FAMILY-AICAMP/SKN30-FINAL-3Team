"""F3 엔드포인트 통합 테스트.

모델은 fake Provider 로 갈아끼운다 — 이 파일은 OpenAI 를 타지 않고, 대신 **대리에게 실제로
간 프롬프트**를 붙잡아 격리(수용 기준 3)와 호출 횟수(수용 기준 5)를 검증한다.
"""

from __future__ import annotations

import json
from typing import Any, cast

import pytest
from brokerage_ai.core.types import (
    ProviderDiagnostics,
    ProviderKind,
    StructuredGenerationRequest,
    StructuredGenerationResult,
    TokenUsage,
)
from brokerage_ai.f3.contracts import MatchVerdict, MatchVerdictList, PositionCard
from brokerage_ai.providers.registry import ProviderRegistry
from ledger_fixtures import create_complex, ledger_client, requires_database
from sqlalchemy import text
from sqlmodel import Session

from core.ai import get_provider_registry
from core.config import Config

pytestmark = requires_database


def card_payload(
    *,
    intent: str = "있음",
    price: float | None = 23.3,
    concession: float | None = 0.0,
    deal_type: str = "매매",
    contact: str = "양호",
    conflict: str | None = None,
    stated_by_tenant: bool | None = None,
) -> dict[str, Any]:
    return {
        "intent": {
            "value": intent,
            "evidence": "[26-06-11 19:42 주]①24.5억은 받아야 한다",
            "speaker": "주①",
            "note": None,
        },
        "price": {
            "estimated": price,
            "basis": "[26-06-11 19:42 주]①24.5억은 받아야 한다",
            "concession": concession,
            "speaker": "주①",
            "conflict": conflict,
            "stated_by_tenant": stated_by_tenant,
        },
        "urgency": {"value": "보통", "evidence": None},
        "flexible": ["잔금 시점"],
        "inflexible": ["24억 하한"],
        "contactability": {"status": contact, "note": None, "route": "주①"},
        "speakers": [
            {"key": "주①", "n": 3, "last": "2026-06-11", "contact": None, "last_stmt": None}
        ],
        "deal_type_now": {"value": deal_type, "ref": None},
    }


class RecordingProvider:
    """호출을 전부 기록하는 대역. 카드 값은 테스트가 지정한다."""

    def __init__(self) -> None:
        self.requests: list[StructuredGenerationRequest] = []
        self.card_overrides: dict[str, dict[str, Any]] = {}
        self.default_card = card_payload()

    @property
    def kind(self) -> ProviderKind:
        return ProviderKind.OPENAI

    @property
    def delegate_calls(self) -> list[StructuredGenerationRequest]:
        return [row for row in self.requests if "대리" in row.messages[0].content]

    @property
    def broker_calls(self) -> list[StructuredGenerationRequest]:
        return [row for row in self.requests if "중개 판정" in row.messages[0].content]

    def user_payload(self, request: StructuredGenerationRequest) -> dict[str, Any]:
        return json.loads(request.messages[1].content)

    async def generate_structured(self, request: Any, output_schema: Any) -> Any:
        self.requests.append(request)
        if output_schema is MatchVerdictList:
            candidates = self.user_payload(request)["candidates"]
            output: Any = MatchVerdictList(
                verdicts=[
                    MatchVerdict(
                        id=str(item["id"]),
                        blocker="없음",
                        concession="없음",
                        action="주①에게 전화",
                    )
                    for item in candidates
                ]
            )
        else:
            label = self.user_payload(request)["label"]
            output = PositionCard.model_validate(self.card_overrides.get(label, self.default_card))
        return StructuredGenerationResult(
            output=output,
            diagnostics=ProviderDiagnostics(
                provider=ProviderKind.OPENAI,
                model=request.route.model,
                request_id="resp_fake",
                latency_ms=5.0,
                usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15),
            ),
        )


def seed_unit(
    session: Session,
    brokerage_id: int,
    complex_id: int,
    *,
    building: str,
    number: str,
    price: int,
    pyeong: str = "33.00",
    tenancy: str = "SELF_OCCUPIED",
    custom_fields: str = "{}",
) -> int:
    unit_id = session.execute(
        text(
            "INSERT INTO property_unit"
            " (brokerage_id, complex_id, building_number, unit_number, pyeong,"
            "  tenancy_status, custom_fields)"
            " VALUES (:b, :c, :bn, :un, :py, :ten, CAST(:cf AS jsonb)) RETURNING id"
        ),
        {
            "b": brokerage_id,
            "c": complex_id,
            "bn": building,
            "un": number,
            "py": pyeong,
            "ten": tenancy,
            "cf": custom_fields,
        },
    ).scalar_one()
    session.execute(
        text(
            "INSERT INTO property_listing"
            " (brokerage_id, unit_id, status, is_sale_available, sale_price)"
            " VALUES (:b, :u, 'ADVERTISING', true, :p)"
        ),
        {"b": brokerage_id, "u": unit_id, "p": price},
    )
    return unit_id


def seed_default_unit(
    session: Session, brokerage_id: int, complex_id: int, price: int = 2_230_000_000, **kwargs: Any
) -> int:
    return seed_unit(
        session, brokerage_id, complex_id, building="203", number="1101", price=price, **kwargs
    )


def seed_requirement(
    session: Session,
    brokerage_id: int,
    *,
    budget: int,
    move_in: str | None = "2027-03-02",
    user_id: int = 1,
) -> int:
    # 동의 시각과 동의자는 함께 있어야 한다 (ck_party_privacy_consent_pair).
    party_id = session.execute(
        text(
            "INSERT INTO party"
            " (brokerage_id, party_type, name, privacy_consent_at, privacy_consent_by)"
            " VALUES (:b, 'INDIVIDUAL', '김O수', now(), :u) RETURNING id"
        ),
        {"b": brokerage_id, "u": user_id},
    ).scalar_one()
    return session.execute(
        text(
            "INSERT INTO property_requirement"
            " (brokerage_id, party_id, demand_type, desired_pyeongs, max_budget_amount,"
            "  desired_move_in_date)"
            " VALUES (:b, :p, 'BUY', ARRAY[33.00], :budget, CAST(:move AS date)) RETURNING id"
        ),
        {"b": brokerage_id, "p": party_id, "budget": budget, "move": move_in},
    ).scalar_one()


def add_log(
    session: Session,
    brokerage_id: int,
    *,
    content: str,
    role: str,
    index: int | None = 1,
    unit_id: int | None = None,
    requirement_id: int | None = None,
    at: str = "2026-06-11 10:42+00",
) -> None:
    session.execute(
        text(
            "INSERT INTO client_interaction"
            " (brokerage_id, interaction_at, interaction_channel, counterparty_role,"
            "  counterparty_index, interaction_content, unit_id, requirement_id)"
            " VALUES (:b, CAST(:at AS timestamptz), 'CALL', :role, :idx, :c, :u, :r)"
        ),
        {
            "b": brokerage_id,
            "at": at,
            "role": role,
            "idx": index,
            "c": content,
            "u": unit_id,
            "r": requirement_id,
        },
    )


@pytest.fixture
def f3_client(config: Config):
    provider = RecordingProvider()
    with ledger_client(config) as (client, session, brokerage_id, user_id):
        app = cast(Any, client.app)
        app.dependency_overrides[get_provider_registry] = lambda: ProviderRegistry(
            llm_providers=[provider]
        )
        yield client, session, brokerage_id, user_id, provider


def test_saving_a_unit_produces_one_card_with_one_model_call(f3_client) -> None:
    client, session, brokerage_id, user_id, provider = f3_client
    complex_id = create_complex(client, session, brokerage_id, "한들마을")
    unit_id = seed_default_unit(session, brokerage_id, complex_id)
    add_log(
        session, brokerage_id, content="24.5억은 받아야 한다", role="OWNER_SIDE", unit_id=unit_id
    )

    response = client.post("/api/v1/position-cards", json={"unit_id": unit_id})

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["label"] == "203동 1101호"
    assert body["intent"] == "있음"
    assert body["cache_hit"] is False
    assert len(provider.requests) == 1


def test_listing_delegate_never_receives_customer_logs(f3_client) -> None:
    """수용 기준 3 — 실행 로그로 확인한다."""
    client, session, brokerage_id, user_id, provider = f3_client
    complex_id = create_complex(client, session, brokerage_id, "한들마을")
    unit_id = seed_default_unit(session, brokerage_id, complex_id)
    requirement_id = seed_requirement(session, brokerage_id, user_id=user_id, budget=2_200_000_000)
    add_log(
        session, brokerage_id, content="24.5억은 받아야 한다", role="OWNER_SIDE", unit_id=unit_id
    )
    add_log(
        session,
        brokerage_id,
        content="23.5억까지는 올릴 수 있다",
        role="BUYER",
        requirement_id=requirement_id,
    )

    client.post("/api/v1/position-cards", json={"unit_id": unit_id})
    client.post("/api/v1/position-cards", json={"requirement_id": requirement_id})

    listing_prompt = json.dumps(provider.user_payload(provider.requests[0]), ensure_ascii=False)
    customer_prompt = json.dumps(provider.user_payload(provider.requests[1]), ensure_ascii=False)

    assert "24.5억" in listing_prompt
    assert "23.5억까지는" not in listing_prompt
    assert "23.5억까지는" in customer_prompt
    assert "24.5억은" not in customer_prompt


def test_position_card_requires_exactly_one_target(f3_client) -> None:
    client, _, _, _, _ = f3_client

    both = client.post("/api/v1/position-cards", json={"unit_id": 1, "requirement_id": 1})
    neither = client.post("/api/v1/position-cards", json={})

    assert both.status_code == 422
    assert neither.status_code == 422


def test_a_second_save_without_new_logs_hits_the_cache(f3_client) -> None:
    """수용 기준 13 — 로그가 그대로면 카드를 다시 만들지 않는다."""
    client, session, brokerage_id, user_id, provider = f3_client
    complex_id = create_complex(client, session, brokerage_id, "한들마을")
    unit_id = seed_default_unit(session, brokerage_id, complex_id)
    add_log(
        session, brokerage_id, content="24.5억은 받아야 한다", role="OWNER_SIDE", unit_id=unit_id
    )

    first = client.post("/api/v1/position-cards", json={"unit_id": unit_id})
    second = client.post("/api/v1/position-cards", json={"unit_id": unit_id})

    assert first.json()["cache_hit"] is False
    assert second.json()["cache_hit"] is True
    assert len(provider.requests) == 1


def test_a_new_log_invalidates_the_card(f3_client) -> None:
    client, session, brokerage_id, user_id, provider = f3_client
    complex_id = create_complex(client, session, brokerage_id, "한들마을")
    unit_id = seed_default_unit(session, brokerage_id, complex_id)
    add_log(
        session, brokerage_id, content="24.5억은 받아야 한다", role="OWNER_SIDE", unit_id=unit_id
    )

    client.post("/api/v1/position-cards", json={"unit_id": unit_id})
    add_log(
        session,
        brokerage_id,
        content="23.8억까지 뺀다",
        role="OWNER_SIDE",
        unit_id=unit_id,
        at="2026-07-01 10:00+00",
    )
    second = client.post("/api/v1/position-cards", json={"unit_id": unit_id})

    assert second.json()["cache_hit"] is False
    assert len(provider.requests) == 2


def test_find_makes_one_broker_call_for_the_anchor_and_all_candidates(f3_client) -> None:
    """수용 기준 5 — 앵커1 + 후보N 이 한 번의 판정 호출로 간다."""
    client, session, brokerage_id, user_id, provider = f3_client
    complex_id = create_complex(client, session, brokerage_id, "한들마을")
    requirement_id = seed_requirement(session, brokerage_id, user_id=user_id, budget=2_350_000_000)
    add_log(
        session,
        brokerage_id,
        content="23.5억까지 가능",
        role="BUYER",
        requirement_id=requirement_id,
    )
    for index, price in enumerate((2_230_000_000, 2_240_000_000, 2_260_000_000), start=1):
        unit_id = seed_unit(
            session,
            brokerage_id,
            complex_id,
            building=f"20{index}",
            number=f"110{index}",
            price=price,
            custom_fields='{"handover_pref_date": "2026-12-15"}',
        )
        add_log(
            session,
            brokerage_id,
            content=f"{index}억은 받아야",
            role="OWNER_SIDE",
            unit_id=unit_id,
        )

    response = client.post(
        "/api/v1/match-evaluations",
        json={"requirement_id": requirement_id, "as_of": "2026-08-17"},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert len(body["candidates"]) == 3
    assert len(provider.broker_calls) == 1
    assert len(provider.delegate_calls) == 4  # 앵커 1 + 후보 3
    assert body["llm_calls"] == 5


def test_candidates_outside_the_price_gate_never_reach_the_model(f3_client) -> None:
    """수용 기준 1 — 후보 추출은 코드가 한다. 게이트 밖은 LLM 을 태우지 않는다."""
    client, session, brokerage_id, user_id, provider = f3_client
    complex_id = create_complex(client, session, brokerage_id, "한들마을")
    requirement_id = seed_requirement(session, brokerage_id, user_id=user_id, budget=2_200_000_000)
    add_log(session, brokerage_id, content="22억 예산", role="BUYER", requirement_id=requirement_id)
    provider.card_overrides["김O수"] = card_payload(price=22.0)
    seed_default_unit(session, brokerage_id, complex_id)
    seed_unit(
        session,
        brokerage_id,
        complex_id,
        building="105",
        number="901",
        price=3_640_000_000,
    )

    response = client.post(
        "/api/v1/match-evaluations",
        json={"requirement_id": requirement_id, "as_of": "2026-08-17"},
    )

    body = response.json()
    assert body["selection"]["kept"] == 1
    assert body["selection"]["dropped"][0]["reason"] == "가격 게이트 밖"
    assert len(provider.delegate_calls) == 2  # 앵커 1 + 게이트 안 후보 1


def test_rejected_candidates_stay_in_the_response(f3_client) -> None:
    """수용 기준 9 — 판정 수 = 노출 수 + 기각 수. 컷이 없다."""
    client, session, brokerage_id, user_id, provider = f3_client
    complex_id = create_complex(client, session, brokerage_id, "한들마을")
    requirement_id = seed_requirement(session, brokerage_id, user_id=user_id, budget=2_350_000_000)
    add_log(
        session, brokerage_id, content="23.5억까지", role="BUYER", requirement_id=requirement_id
    )
    provider.card_overrides["김O수"] = card_payload(price=23.5)
    unit_id = seed_default_unit(session, brokerage_id, complex_id, price=2_300_000_000)
    add_log(session, brokerage_id, content="월세로 돌린다", role="OWNER_SIDE", unit_id=unit_id)
    provider.card_overrides["203동 1101호"] = card_payload(deal_type="임대")

    response = client.post(
        "/api/v1/match-evaluations",
        json={"requirement_id": requirement_id, "as_of": "2026-08-17"},
    )

    body = response.json()
    assert len(body["candidates"]) == 1
    rejected = body["candidates"][0]
    assert rejected["grade"] == "기각"
    assert rejected["hard_gates"][0].startswith("G1 거래 유형 불일치")


def test_the_run_is_recorded_for_the_traceability_chain(f3_client) -> None:
    client, session, brokerage_id, _, _ = f3_client
    complex_id = create_complex(client, session, brokerage_id, "한들마을")
    unit_id = seed_default_unit(session, brokerage_id, complex_id)
    add_log(session, brokerage_id, content="24.5억", role="OWNER_SIDE", unit_id=unit_id)

    client.post("/api/v1/position-cards", json={"unit_id": unit_id})

    run = session.execute(
        text(
            "SELECT run_type, agent_type, trigger_type, prompt_version, workflow_version,"
            " input_tokens, target_unit_id"
            " FROM agent_run WHERE brokerage_id = :b"
        ),
        {"b": brokerage_id},
    ).one()
    assert run.run_type == "POSITION_ANALYSIS"
    assert run.agent_type == "LISTING_DELEGATE"
    assert run.trigger_type == "USER_SAVE"
    assert run.prompt_version
    assert run.workflow_version == "f3-slice-1"
    assert run.target_unit_id == unit_id


def test_a_missing_target_is_reported_as_not_found(f3_client) -> None:
    client, _, _, _, _ = f3_client

    response = client.post("/api/v1/position-cards", json={"unit_id": 999_999})

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_f3_returns_503_when_the_ai_runtime_is_absent(config: Config) -> None:
    """수용 기준 15 — F3 가 죽어도 F1 은 살아야 한다."""
    with ledger_client(config) as (client, _, _, _):
        f1 = client.get("/api/v1/property-units")
        f3 = client.post("/api/v1/position-cards", json={"unit_id": 1})

    assert f1.status_code == 200
    assert f3.status_code == 503
    assert f3.json()["code"] == "AI_UNAVAILABLE"


def test_a_route_without_a_configured_provider_is_503_not_500(config: Config) -> None:
    """route 에 맞는 Provider 가 없으면 500 이 아니라 공개 계약의 503 으로 나간다."""
    with ledger_client(config) as (client, session, brokerage_id, _):
        complex_id = create_complex(client, session, brokerage_id, "한들마을")
        unit_id = seed_default_unit(session, brokerage_id, complex_id)
        app = cast(Any, client.app)
        # LLM Provider 가 하나도 없는 레지스트리 — 설정만 있고 Provider 가 없는 상태다.
        app.dependency_overrides[get_provider_registry] = lambda: ProviderRegistry()

        response = client.post("/api/v1/position-cards", json={"unit_id": unit_id})

    assert response.status_code == 503
    assert response.json()["code"] == "AI_UNAVAILABLE"


def test_position_card_reports_which_fields_are_inferred(f3_client) -> None:
    """수용 기준 2 — 근거 원문이 있거나 「추정」으로 표시된다."""
    client, session, brokerage_id, _, _ = f3_client
    complex_id = create_complex(client, session, brokerage_id, "한들마을")
    unit_id = seed_default_unit(session, brokerage_id, complex_id)
    add_log(session, brokerage_id, content="24.5억", role="OWNER_SIDE", unit_id=unit_id)

    body = client.post("/api/v1/position-cards", json={"unit_id": unit_id}).json()

    by_field = {item["field_name"]: item for item in body["evidence"]}
    assert by_field["intent"]["is_inferred"] is False
    assert by_field["urgency"]["is_inferred"] is True
