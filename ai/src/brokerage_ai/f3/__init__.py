"""F3 의 Backend–AI 공개 계약.

두 계약이 있다. 포지션 카드(`position-card:v1`)는 한 측면의 협상 입장을 세우고, 중개
판정(`brokerage-judgment:v1`)은 앵커 카드 1장과 후보 카드 N장을 한 번에 비교해 등급·순위·
근거·행동을 낸다.

카드 저장, 상태 전이와 tenant 격리는 Backend 가 소유한다. LangGraph production graph 와
checkpoint 는 아직 없다. 두 생성 모두 구조화 출력 1회다.
"""

from brokerage_ai.f3.contracts import (
    ALLOWED_PRICE_KINDS,
    POSITION_CARD_CONTRACT_VERSION,
    AnchorContext,
    AnchorContextValue,
    ConsultationLogInput,
    ContactabilityAssessment,
    ContactabilityStatus,
    ContractVersion,
    DateSignals,
    Evidence,
    EvidenceKind,
    IntentAssessment,
    ListingAnchorContext,
    NegotiationIntent,
    NegotiationSide,
    PartyRoleContext,
    PositionCardAnalysis,
    PositionCardGenerationRequest,
    PositionCardGenerationResult,
    PositionCardTarget,
    PositionCondition,
    PriceAssessment,
    PriceKind,
    RequirementAnchorContext,
    SourceIdentity,
    TimingAssessment,
    Urgency,
    UrgencyAssessment,
    enabled_price_kinds,
    stated_price_for,
)
from brokerage_ai.f3.generator import (
    POSITION_CARD_WORKFLOW_VERSION,
    LlmPositionCardGenerator,
)
from brokerage_ai.f3.judgment_contracts import (
    BROKERAGE_JUDGMENT_CONTRACT_VERSION,
    BrokerageJudgmentRequest,
    BrokerageJudgmentResult,
    BrokerageJudgmentTarget,
    CandidateJudgment,
    ContactChannel,
    JudgmentCard,
    JudgmentContractVersion,
    JudgmentEvidence,
    MatchGrade,
    RecommendedAction,
)
from brokerage_ai.f3.judgment_generator import (
    BROKERAGE_JUDGMENT_WORKFLOW_VERSION,
    LlmBrokerageJudgmentGenerator,
)
from brokerage_ai.f3.judgment_ports import (
    BrokerageJudgmentGenerator,
    BrokerageJudgmentGeneratorVersions,
)
from brokerage_ai.f3.judgment_prompts import BROKERAGE_JUDGMENT_PROMPT_VERSION
from brokerage_ai.f3.judgment_validation import (
    BrokerageJudgmentContractError,
    validate_judgment_result,
)
from brokerage_ai.f3.ports import PositionCardGenerator, PositionCardGeneratorVersions
from brokerage_ai.f3.prompts import POSITION_CARD_PROMPT_VERSION
from brokerage_ai.f3.validation import (
    PositionCardContractError,
    validate_generation_result,
)

__all__ = [
    "ALLOWED_PRICE_KINDS",
    "BROKERAGE_JUDGMENT_CONTRACT_VERSION",
    "BROKERAGE_JUDGMENT_PROMPT_VERSION",
    "BROKERAGE_JUDGMENT_WORKFLOW_VERSION",
    "BrokerageJudgmentContractError",
    "BrokerageJudgmentGenerator",
    "BrokerageJudgmentGeneratorVersions",
    "BrokerageJudgmentRequest",
    "BrokerageJudgmentResult",
    "BrokerageJudgmentTarget",
    "CandidateJudgment",
    "ContactChannel",
    "JudgmentCard",
    "JudgmentContractVersion",
    "JudgmentEvidence",
    "LlmBrokerageJudgmentGenerator",
    "MatchGrade",
    "RecommendedAction",
    "validate_judgment_result",
    "POSITION_CARD_CONTRACT_VERSION",
    "AnchorContext",
    "ConsultationLogInput",
    "ContactabilityAssessment",
    "ContactabilityStatus",
    "ContractVersion",
    "DateSignals",
    "Evidence",
    "EvidenceKind",
    "IntentAssessment",
    "ListingAnchorContext",
    "NegotiationIntent",
    "NegotiationSide",
    "PositionCardAnalysis",
    "PositionCardContractError",
    "PositionCardGenerationRequest",
    "PositionCardGenerationResult",
    "PositionCardGenerator",
    "PositionCardTarget",
    "PositionCondition",
    "PriceAssessment",
    "PriceKind",
    "RequirementAnchorContext",
    "SourceIdentity",
    "TimingAssessment",
    "Urgency",
    "UrgencyAssessment",
    "AnchorContextValue",
    "LlmPositionCardGenerator",
    "POSITION_CARD_PROMPT_VERSION",
    "POSITION_CARD_WORKFLOW_VERSION",
    "PartyRoleContext",
    "PositionCardGeneratorVersions",
    "enabled_price_kinds",
    "stated_price_for",
    "validate_generation_result",
]
