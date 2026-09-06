"""F3 포지션 카드를 Provider 하나에 실제로 한 번 물려 본다.

**왜 있나.** 이게 없으면 "붙었는지"를 확인하는 유일한 길이 DB seed 적재 + Worker 기동 +
케이스 실행이다. 한 번에 30분이고 실패해도 원인이 endpoint 인지 스키마인지 프롬프트인지
구분되지 않는다. 여기서는 모델 호출 한 겹만 떼어 낸다.

로컬 vLLM 을 새로 띄웠을 때 **가장 먼저** 이걸 돌린다. `chat.completions.parse` 가 넘기는
strict JSON schema 를 vLLM 의 구조화 출력 백엔드가 소화하지 못하면 여기서 바로 드러나며,
그건 프롬프트로 고칠 수 있는 실패가 아니다.

    uv run --project ai python ai/eval/f3/smoke.py Qwen/Qwen3-32B-AWQ
    uv run --project ai python ai/eval/f3/smoke.py gpt-4o-mini --provider openai

입력은 이 파일 안의 합성 사례 하나뿐이다. 실제 상담 데이터를 읽지 않는다.

ponytail: 포지션 카드만 본다. 중개 판정 스키마는 케이스 A~I 실행에서 확인한다.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, date, datetime

from brokerage_ai.core.config import load_ai_config
from brokerage_ai.core.types import ModelRoute, ProviderKind
from brokerage_ai.f3 import (
    ConsultationLogInput,
    DateSignals,
    InputPrivacyMode,
    ListingAnchorContext,
    LlmPositionCardGenerator,
    NegotiationSide,
    PartyRoleContext,
    PositionCardGenerationRequest,
    SourceIdentity,
)
from brokerage_ai.runtime import create_ai_runtime

AS_OF = datetime(2026, 8, 20, 1, 0, tzinfo=UTC)

# 합성 사례 하나. 지어낸 값이며 실존 인물·매물과 무관하다. 세 로그가 각각 인용(가격 하한),
# 인용(여유), 접촉 실패를 물어 카드의 주요 항목이 한 번씩 걸리게 골랐다.
LOGS = (
    ConsultationLogInput(
        interaction_id=101,
        interaction_at=datetime(2026, 6, 2, 5, 0, tzinfo=UTC),
        channel="VISIT",
        counterparty_role="OWNER",
        masked_content="방문 상담. 소유자 ***. 28억 아래로는 안 판다고 못박음.",
    ),
    ConsultationLogInput(
        interaction_id=118,
        interaction_at=datetime(2026, 7, 21, 2, 30, tzinfo=UTC),
        channel="CALL",
        counterparty_role="OWNER",
        interaction_result="SUCCESS",
        masked_content="소유자 통화. 급하지 않습니다. 세입자 만기까지는 기다릴 수 있다고 함.",
    ),
    ConsultationLogInput(
        interaction_id=131,
        interaction_at=datetime(2026, 8, 14, 7, 15, tzinfo=UTC),
        channel="CALL",
        counterparty_role="OWNER",
        interaction_result="NO_ANSWER",
        masked_content="부재중. 연결되지 않음.",
    ),
)

REQUEST = PositionCardGenerationRequest(
    input_privacy_mode=InputPrivacyMode.SYNTHETIC_PROTOTYPE,
    negotiation_side=NegotiationSide.LISTING,
    anchor_id=9001,
    target_label="합성단지 101동 1801호",
    source=SourceIdentity(
        data_version=1,
        interaction_count=len(LOGS),
        last_interaction_at=LOGS[-1].interaction_at,
        max_interaction_id=131,
    ),
    anchor=ListingAnchorContext(
        listing_id=9001,
        unit_id=7001,
        listing_status="RECEIVED",
        is_sale_available=True,
        sale_price=2_880_000_000,
        unit_number="1801",
        party_roles=(PartyRoleContext(role="OWNER", is_primary=True),),
        client_party_role="OWNER",
    ),
    date_signals=DateSignals(
        as_of=AS_OF,
        days_until_tenancy_expiry=102,
        hard_deadline_candidate=date(2026, 11, 30),
    ),
    consultation_logs=LOGS,
)


async def run(model: str, provider_kind: ProviderKind) -> int:
    config = load_ai_config("local")
    async with create_ai_runtime(config) as runtime:
        generator = LlmPositionCardGenerator(
            provider=runtime.providers.get_llm(provider_kind),
            route=ModelRoute(provider=provider_kind, model=model),
            allow_synthetic_prototype=True,
        )
        result = await generator.generate_position_card(REQUEST)

    diagnostics = result.diagnostics
    if diagnostics is None:
        print("OK  (diagnostics 없음)")
    else:
        print(f"OK  model={diagnostics.model}  latency={diagnostics.latency_ms:.0f}ms")
        usage = diagnostics.usage
        if usage is not None:
            print(f"    tokens in={usage.input_tokens} out={usage.output_tokens}")
    print(result.analysis.model_dump_json(indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", help="Provider 가 아는 모델 ID. vLLM 이면 /v1/models 의 값 그대로")
    parser.add_argument(
        "--provider",
        default=ProviderKind.VLLM.value,
        choices=[kind.value for kind in ProviderKind],
        help="기본값 vllm. OpenAI 기준선을 뜰 때만 openai 로 바꾼다",
    )
    arguments = parser.parse_args()

    try:
        return asyncio.run(run(arguments.model, ProviderKind(arguments.provider)))
    except Exception as error:
        # 예외 **타입**이 원인 구분의 핵심이다. ProviderConfigurationError 는 .env 문제,
        # ProviderOutputInvalidError 는 모델이 스키마를 못 지킨 것, APIConnectionError 는
        # 터널이 끊긴 것이다. runbook 의 오류 표가 이 이름을 기준으로 쓰여 있다.
        print(f"FAIL {type(error).__name__}: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
