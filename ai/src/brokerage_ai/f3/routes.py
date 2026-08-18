"""F3 역할별 모델 배정.

AI-OQ-002(역할별 ModelRoute 배정)의 **잠정** 답이다. 운영 Provider·모델 승인이 아니다.
값은 `06_프로토타입_F3플로우` 와 같게 두었다 — 다르면 프로토타입과의 등급 대조가 성립하지 않는다.
대리는 후보 수만큼 돌고 중개 판정은 1회뿐이라 등급을 다르게 잡는다.
"""

from __future__ import annotations

from brokerage_ai.core.types import ModelRoute, ProviderKind

DELEGATE_ROUTE = ModelRoute(provider=ProviderKind.OPENAI, model="gpt-4o-mini")
BROKER_ROUTE = ModelRoute(provider=ProviderKind.OPENAI, model="gpt-4o")

# 판정 재현성(F3-NF-08)을 위해 샘플링을 끈다.
TEMPERATURE = 0.0
