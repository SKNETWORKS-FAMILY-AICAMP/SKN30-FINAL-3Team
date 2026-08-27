"""중개 판정 계약과 생성 구현 검증.

실제 Provider 도 네트워크도 쓰지 않는다. fake `LlmProvider` 로 무엇을 넘겼고 무엇을
조립했는지, 그리고 어떤 결과를 거절하는지만 본다.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from brokerage_ai.core.types import (
    ModelRoute,
    ProviderDiagnostics,
    ProviderKind,
    StructuredGenerationRequest,
    StructuredGenerationResult,
    TokenUsage,
)
from brokerage_ai.f3 import (
    BROKERAGE_JUDGMENT_PROMPT_VERSION,
    BROKERAGE_JUDGMENT_WORKFLOW_VERSION,
    BrokerageJudgmentContractError,
    BrokerageJudgmentRequest,
    BrokerageJudgmentResult,
    BrokerageJudgmentTarget,
    CandidateJudgment,
    ContactabilityAssessment,
    ContactabilityStatus,
    ContactChannel,
    Evidence,
    EvidenceKind,
    InputPrivacyMode,
    IntentAssessment,
    JudgmentCard,
    JudgmentEvidence,
    LlmBrokerageJudgmentGenerator,
    MatchGrade,
    NegotiationIntent,
    NegotiationSide,
    PositionCardAnalysis,
    PositionCondition,
    RecommendedAction,
    TimingAssessment,
    Urgency,
    UrgencyAssessment,
    validate_judgment_result,
)
from brokerage_ai.f3.judgment_model_output import (
    BrokerageJudgmentModelOutput,
    ModelCandidateJudgment,
)

ROUTE = ModelRoute(provider=ProviderKind.VLLM, model="test-broker")
ANCHOR_QUOTE = "28억 아래로는 안 판다"
CANDIDATE_QUOTE = "30억까지는 볼 수 있습니다"
ANCHOR_INTERACTION = 11
CANDIDATE_INTERACTION = 22


def quote(interaction_id: int, text: str) -> Evidence:
    return Evidence(kind=EvidenceKind.QUOTE, interaction_id=interaction_id, quote_text=text)


def inference(note: str = "카드 값을 비교했다") -> Evidence:
    return Evidence(kind=EvidenceKind.INFERENCE, note=note)


def analysis(evidence: Evidence) -> PositionCardAnalysis:
    return PositionCardAnalysis(
        intent=IntentAssessment(value=NegotiationIntent.PRESENT, evidence=(evidence,)),
        urgency=UrgencyAssessment(value=Urgency.NORMAL, evidence=(inference(),)),
        timing=TimingAssessment(),
        flexible=(PositionCondition(description="잔금일 조정", evidence=(inference(),)),),
        contactability=ContactabilityAssessment(
            status=ContactabilityStatus.GOOD, evidence=(inference(),)
        ),
    )


def anchor_card(card_id: int = 1) -> JudgmentCard:
    return JudgmentCard(
        card_id=card_id,
        negotiation_side=NegotiationSide.LISTING,
        target_label="검증단지 101동 1801호",
        analysis=analysis(quote(ANCHOR_INTERACTION, ANCHOR_QUOTE)),
    )


def candidate_card(card_id: int, interaction_id: int = CANDIDATE_INTERACTION) -> JudgmentCard:
    return JudgmentCard(
        card_id=card_id,
        negotiation_side=NegotiationSide.REQUIREMENT,
        target_label=f"구입장 #{card_id}",
        analysis=analysis(quote(interaction_id, CANDIDATE_QUOTE)),
    )


def request(
    candidate_ids: tuple[int, ...] = (2, 3),
    *,
    input_privacy_mode: InputPrivacyMode = InputPrivacyMode.SYNTHETIC_PROTOTYPE,
) -> BrokerageJudgmentRequest:
    return BrokerageJudgmentRequest(
        input_privacy_mode=input_privacy_mode,
        anchor=anchor_card(),
        candidates=tuple(candidate_card(card_id) for card_id in candidate_ids),
    )


def judgment(
    card_id: int,
    rank: int,
    *,
    grade: MatchGrade = MatchGrade.STRONG,
    rejection_reason: str | None = None,
    evidence: tuple[JudgmentEvidence, ...] | None = None,
) -> CandidateJudgment:
    return CandidateJudgment(
        card_id=card_id,
        grade=grade,
        rank=rank,
        comparison_basis="예산 상한이 앵커 추정가에 가장 가깝다",
        primary_obstacle="가격 차",
        possible_concession="매도 측이 2천만원 조정",
        recommended_action=RecommendedAction(
            contact_side=NegotiationSide.REQUIREMENT,
            channel=ContactChannel.MESSAGE,
            message="가격 조정 여지를 먼저 확인한다",
        ),
        rejection_reason=rejection_reason,
        # `or` 로 기본값을 주면 빈 tuple 이 기본값으로 바뀌어 "근거 없음" 을 시험할 수 없다.
        evidence=(
            evidence
            if evidence is not None
            else (
                JudgmentEvidence(
                    evidence_side=NegotiationSide.LISTING,
                    field_name="price",
                    source=quote(ANCHOR_INTERACTION, ANCHOR_QUOTE),
                ),
            )
        ),
    )


def result(
    source: BrokerageJudgmentRequest, candidates: tuple[CandidateJudgment, ...]
) -> BrokerageJudgmentResult:
    return BrokerageJudgmentResult(
        target=BrokerageJudgmentTarget.from_request(source),
        candidates=candidates,
        prompt_version=BROKERAGE_JUDGMENT_PROMPT_VERSION,
        workflow_version=BROKERAGE_JUDGMENT_WORKFLOW_VERSION,
    )


class FakeProvider:
    """구조화 출력을 그대로 돌려주는 대역. 호출 인자를 전부 보관한다."""

    def __init__(
        self,
        output: BrokerageJudgmentModelOutput,
        *,
        kind: ProviderKind = ProviderKind.VLLM,
    ) -> None:
        self.calls: list[StructuredGenerationRequest] = []
        self.schemas: list[type[BaseModel]] = []
        self.output = output
        self._kind = kind

    @property
    def kind(self) -> ProviderKind:
        return self._kind

    async def generate_structured(
        self, request: StructuredGenerationRequest, output_schema: type[Any]
    ) -> StructuredGenerationResult[Any]:
        # 인자 이름까지 Protocol 과 같아야 한다. 키워드 호출에서 갈라지면 대역이 아니다.
        self.calls.append(request)
        self.schemas.append(output_schema)
        return StructuredGenerationResult(
            output=self.output,
            diagnostics=ProviderDiagnostics(
                provider=self.kind,
                model="test-broker",
                request_id="req-9",
                latency_ms=88.0,
                usage=TokenUsage(input_tokens=900, output_tokens=210, total_tokens=1110),
            ),
        )


def generator_for(
    provider: FakeProvider, *, allow_synthetic_prototype: bool = True
) -> LlmBrokerageJudgmentGenerator:
    return LlmBrokerageJudgmentGenerator(
        provider=provider,
        route=ROUTE,
        allow_synthetic_prototype=allow_synthetic_prototype,
    )


def model_output(*candidates: ModelCandidateJudgment) -> BrokerageJudgmentModelOutput:
    return BrokerageJudgmentModelOutput(candidates=candidates)


def model_candidate(
    card_id: int, rank: int, *, grade: MatchGrade = MatchGrade.STRONG
) -> ModelCandidateJudgment:
    return ModelCandidateJudgment(
        card_id=card_id,
        grade=grade,
        rank=rank,
        comparison_basis="예산 상한이 앵커 추정가에 가장 가깝다",
        primary_obstacle="가격 차",
        rejection_reason="시점이 맞지 않는다" if grade is MatchGrade.REJECTED else None,
        evidence=(
            JudgmentEvidence(
                evidence_side=NegotiationSide.LISTING,
                source=quote(ANCHOR_INTERACTION, ANCHOR_QUOTE),
            ),
        ),
    )


# ── 어휘와 구조 ────────────────────────────────────────────────────────────────


def test_the_grade_vocabulary_is_exactly_three_values() -> None:
    assert [grade.value for grade in MatchGrade] == ["STRONG", "WEAK", "REJECTED"]


def test_a_rejected_candidate_requires_a_reason() -> None:
    with pytest.raises(ValidationError, match="rejection_reason"):
        judgment(2, 1, grade=MatchGrade.REJECTED)


def test_only_a_rejected_candidate_may_carry_a_reason() -> None:
    with pytest.raises(ValidationError, match="rejection_reason"):
        judgment(2, 1, grade=MatchGrade.STRONG, rejection_reason="사유")


def test_a_candidate_without_evidence_is_rejected() -> None:
    with pytest.raises(ValidationError):
        judgment(2, 1, evidence=())


def test_a_rank_below_one_is_rejected() -> None:
    with pytest.raises(ValidationError):
        judgment(2, 0)


def test_candidates_must_be_on_the_opposite_side_of_the_anchor() -> None:
    with pytest.raises(ValidationError, match="opposite negotiation side"):
        BrokerageJudgmentRequest(
            input_privacy_mode=InputPrivacyMode.SYNTHETIC_PROTOTYPE,
            anchor=anchor_card(1),
            candidates=(anchor_card(2),),
        )


def test_the_anchor_must_not_also_be_a_candidate() -> None:
    with pytest.raises(ValidationError, match="must not also be a candidate"):
        BrokerageJudgmentRequest(
            input_privacy_mode=InputPrivacyMode.SYNTHETIC_PROTOTYPE,
            anchor=anchor_card(1),
            candidates=(candidate_card(1),),
        )


def test_a_request_with_no_candidate_cannot_be_built() -> None:
    """후보 0건은 모델 호출 없이 처리하므로 generator 입력으로 만들 수 없다."""
    with pytest.raises(ValidationError):
        BrokerageJudgmentRequest(
            input_privacy_mode=InputPrivacyMode.SYNTHETIC_PROTOTYPE,
            anchor=anchor_card(),
            candidates=(),
        )


def test_a_request_rejects_more_than_fifteen_candidates() -> None:
    with pytest.raises(ValidationError):
        request(tuple(range(2, 18)))


# ── 요청·결과 교차 검증 ────────────────────────────────────────────────────────


def test_a_matching_result_passes() -> None:
    source = request()
    validate_judgment_result(source, result(source, (judgment(2, 1), judgment(3, 2))))


def test_a_missing_candidate_is_rejected() -> None:
    source = request()
    produced = BrokerageJudgmentResult(
        target=BrokerageJudgmentTarget.from_request(source), candidates=(judgment(2, 1),)
    )
    with pytest.raises(BrokerageJudgmentContractError, match="missing"):
        validate_judgment_result(source, produced)


def test_an_extra_candidate_is_rejected() -> None:
    source = request()
    produced = BrokerageJudgmentResult(
        target=BrokerageJudgmentTarget.from_request(source),
        candidates=(judgment(2, 1), judgment(3, 2), judgment(99, 3)),
    )
    with pytest.raises(BrokerageJudgmentContractError, match="not requested"):
        validate_judgment_result(source, produced)


def test_a_repeated_candidate_is_rejected() -> None:
    source = request()
    produced = BrokerageJudgmentResult(
        target=BrokerageJudgmentTarget.from_request(source),
        candidates=(judgment(2, 1), judgment(2, 2), judgment(3, 3)),
    )
    with pytest.raises(BrokerageJudgmentContractError, match="repeats"):
        validate_judgment_result(source, produced)


def test_duplicate_ranks_are_rejected() -> None:
    source = request()
    with pytest.raises(BrokerageJudgmentContractError, match="1..N"):
        validate_judgment_result(source, result(source, (judgment(2, 1), judgment(3, 1))))


def test_a_gap_in_the_ranks_is_rejected() -> None:
    source = request()
    with pytest.raises(BrokerageJudgmentContractError, match="1..N"):
        validate_judgment_result(source, result(source, (judgment(2, 1), judgment(3, 3))))


def test_a_different_anchor_card_is_rejected() -> None:
    source = request()
    produced = BrokerageJudgmentResult(
        target=BrokerageJudgmentTarget(
            anchor_card_id=999,
            anchor_side=NegotiationSide.LISTING,
            candidate_card_ids=(2, 3),
        ),
        candidates=(judgment(2, 1), judgment(3, 2)),
    )
    with pytest.raises(BrokerageJudgmentContractError, match="different anchor card"):
        validate_judgment_result(source, produced)


def test_a_different_candidate_set_in_the_target_is_rejected() -> None:
    source = request()
    produced = BrokerageJudgmentResult(
        target=BrokerageJudgmentTarget(
            anchor_card_id=1, anchor_side=NegotiationSide.LISTING, candidate_card_ids=(2, 4)
        ),
        candidates=(judgment(2, 1), judgment(3, 2)),
    )
    with pytest.raises(BrokerageJudgmentContractError, match="different candidate set"):
        validate_judgment_result(source, produced)


def test_a_quote_the_cards_do_not_contain_is_rejected() -> None:
    """판정 단계에는 상담 원문이 없다. 카드에 없는 인용은 모델이 만들어 낸 것이다."""
    source = request()
    invented = judgment(
        2,
        1,
        evidence=(
            JudgmentEvidence(
                evidence_side=NegotiationSide.LISTING,
                source=quote(ANCHOR_INTERACTION, "이런 말은 한 적이 없다"),
            ),
        ),
    )
    with pytest.raises(BrokerageJudgmentContractError, match="does not contain"):
        validate_judgment_result(source, result(source, (invented, judgment(3, 2))))


def test_a_quote_attributed_to_the_wrong_side_is_rejected() -> None:
    source = request()
    misattributed = judgment(
        2,
        1,
        evidence=(
            JudgmentEvidence(
                evidence_side=NegotiationSide.REQUIREMENT,
                source=quote(ANCHOR_INTERACTION, ANCHOR_QUOTE),
            ),
        ),
    )
    with pytest.raises(BrokerageJudgmentContractError, match="does not contain"):
        validate_judgment_result(source, result(source, (misattributed, judgment(3, 2))))


def test_an_inference_needs_no_quote() -> None:
    source = request()
    reasoned = judgment(
        2,
        1,
        evidence=(
            JudgmentEvidence(
                evidence_side=NegotiationSide.REQUIREMENT,
                source=inference("예산 상한과 표기가의 차이를 비교했다"),
            ),
        ),
    )
    validate_judgment_result(source, result(source, (reasoned, judgment(3, 2))))


def test_a_rejected_candidate_survives_into_the_result() -> None:
    """기각도 결과에 남는다. 조용히 사라지는 후보를 만들지 않는다 (F3-BR-10)."""
    source = request()
    rejected = judgment(3, 2, grade=MatchGrade.REJECTED, rejection_reason="이사일이 6개월 어긋난다")
    produced = result(source, (judgment(2, 1), rejected))
    validate_judgment_result(source, produced)
    assert produced.candidates[1].grade is MatchGrade.REJECTED
    assert produced.candidates[1].rejection_reason


# ── 생성 구현 ──────────────────────────────────────────────────────────────────


async def test_synthetic_input_requires_an_explicit_generator_opt_in() -> None:
    source = request()
    provider = FakeProvider(model_output(model_candidate(2, 1), model_candidate(3, 2)))
    generator = generator_for(provider, allow_synthetic_prototype=False)

    with pytest.raises(BrokerageJudgmentContractError, match="explicit generator opt-in"):
        await generator.judge_candidates(source)

    assert provider.calls == []


async def test_masked_input_does_not_need_the_synthetic_opt_in() -> None:
    source = request(input_privacy_mode=InputPrivacyMode.MASKED)
    provider = FakeProvider(model_output(model_candidate(2, 1), model_candidate(3, 2)))
    generator = generator_for(provider, allow_synthetic_prototype=False)

    produced = await generator.judge_candidates(source)

    assert len(produced.candidates) == 2
    assert len(provider.calls) == 1


def test_the_provider_kind_must_match_the_model_route() -> None:
    provider = FakeProvider(
        model_output(model_candidate(2, 1), model_candidate(3, 2)),
        kind=ProviderKind.OPENAI,
    )

    with pytest.raises(ValueError, match="provider kind"):
        generator_for(provider)


async def test_all_candidates_go_out_in_a_single_structured_request() -> None:
    """후보를 1장씩 개별 호출하지 않는다 (F3-BR-01, F3-NF-04)."""
    source = request((2, 3, 4))
    provider = FakeProvider(
        model_output(model_candidate(2, 1), model_candidate(3, 2), model_candidate(4, 3))
    )
    generator = generator_for(provider)

    produced = await generator.judge_candidates(source)

    assert len(provider.calls) == 1
    assert provider.schemas == [BrokerageJudgmentModelOutput]
    assert len(produced.candidates) == 3
    validate_judgment_result(source, produced)


async def test_the_anchor_card_is_sent_exactly_once() -> None:
    """앵커를 후보 수만큼 반복 전송하지 않는다 (F3-BR-02)."""
    source = request((2, 3, 4))
    provider = FakeProvider(
        model_output(model_candidate(2, 1), model_candidate(3, 2), model_candidate(4, 3))
    )
    generator = generator_for(provider)

    await generator.judge_candidates(source)

    body = "".join(message.content for message in provider.calls[0].messages)
    assert body.count(source.anchor.target_label) == 1


async def test_the_target_is_copied_from_the_request_not_the_model() -> None:
    source = request()
    provider = FakeProvider(model_output(model_candidate(2, 1), model_candidate(3, 2)))
    generator = generator_for(provider)

    produced = await generator.judge_candidates(source)

    assert produced.target.anchor_card_id == source.anchor.card_id
    assert produced.target.anchor_side is NegotiationSide.LISTING
    assert set(produced.target.candidate_card_ids) == {2, 3}


async def test_the_versions_and_safe_diagnostics_come_back() -> None:
    source = request()
    provider = FakeProvider(model_output(model_candidate(2, 1), model_candidate(3, 2)))
    generator = generator_for(provider)

    produced = await generator.judge_candidates(source)

    assert produced.prompt_version == BROKERAGE_JUDGMENT_PROMPT_VERSION
    assert produced.workflow_version == BROKERAGE_JUDGMENT_WORKFLOW_VERSION
    assert generator.versions.prompt_version == BROKERAGE_JUDGMENT_PROMPT_VERSION
    assert produced.diagnostics is not None
    assert produced.diagnostics.usage is not None
    assert produced.diagnostics.usage.total_tokens == 1110
    # Provider SDK 응답 자체는 공개 DTO 밖으로 나가지 않는다.
    assert set(produced.diagnostics.model_dump()) == {
        "provider",
        "model",
        "request_id",
        "latency_ms",
        "usage",
    }


async def test_a_model_that_drops_a_candidate_is_caught_by_validation() -> None:
    """조립 단계가 조용히 메우지 않는다. 검증이 문제를 드러내야 한다."""
    source = request((2, 3))
    provider = FakeProvider(model_output(model_candidate(2, 1)))
    generator = generator_for(provider)

    with pytest.raises(BrokerageJudgmentContractError, match="missing"):
        await generator.judge_candidates(source)


async def test_a_model_that_invents_a_candidate_is_caught_by_validation() -> None:
    source = request((2,))
    provider = FakeProvider(model_output(model_candidate(2, 1), model_candidate(77, 2)))
    generator = generator_for(provider)

    with pytest.raises(BrokerageJudgmentContractError, match="not requested"):
        await generator.judge_candidates(source)


async def test_the_prompt_carries_no_run_or_tenant_identifier() -> None:
    """실행 제어 값과 사무소 식별자는 AI 공개 계약에 들어가지 않는다."""
    source = request()
    provider = FakeProvider(model_output(model_candidate(2, 1), model_candidate(3, 2)))
    generator = generator_for(provider)

    await generator.judge_candidates(source)

    body = "".join(message.content for message in provider.calls[0].messages)
    for forbidden in ("brokerage_id", "run_id", "lease_owner", "requested_by", "attempt_count"):
        assert forbidden not in body


async def test_the_prompt_requires_unused_evidence_fields_to_be_null() -> None:
    source = request()
    provider = FakeProvider(model_output(model_candidate(2, 1), model_candidate(3, 2)))
    generator = generator_for(provider)

    await generator.judge_candidates(source)

    body = "".join(message.content for message in provider.calls[0].messages)
    for rule in ("kind=QUOTE", "kind=INFERENCE", "해당하지 않는 필드는 반드시 null"):
        assert rule in body


class SequenceProvider:
    """호출 순서대로 다른 출력을 내놓는 대역. 되먹임 뒤 모델이 답을 고치는 상황을 흉내 낸다."""

    def __init__(self, *outputs: BrokerageJudgmentModelOutput) -> None:
        self.outputs = list(outputs)
        self.calls: list[StructuredGenerationRequest] = []

    @property
    def kind(self) -> ProviderKind:
        return ProviderKind.VLLM

    async def generate_structured(
        self, request: StructuredGenerationRequest, output_schema: type[Any]
    ) -> StructuredGenerationResult[Any]:
        self.calls.append(request)
        return StructuredGenerationResult(
            output=self.outputs.pop(0),
            diagnostics=ProviderDiagnostics(
                provider=self.kind, model="test-broker", latency_ms=1.0
            ),
        )


async def test_a_rank_gap_is_fed_back_and_the_next_attempt_is_accepted() -> None:
    """순위가 어긋난 판정은 `validate_judgment_result()` 에서만 걸린다.

    모델이 원인이고 지적하면 고칠 수 있는 실패인데, 지금까지는 첫 시도에 종료됐다.
    """
    source = request()
    provider = SequenceProvider(
        model_output(model_candidate(2, 1), model_candidate(3, 3)),
        model_output(model_candidate(2, 1), model_candidate(3, 2)),
    )

    result = await LlmBrokerageJudgmentGenerator(
        provider=provider, route=ROUTE, allow_synthetic_prototype=True
    ).judge_candidates(source)

    assert [candidate.rank for candidate in result.candidates] == [1, 2]
    assert len(provider.calls) == 2
    appended = provider.calls[1].messages[len(provider.calls[0].messages) :]
    assert len(appended) == 1
    assert "1..N without gaps" in appended[0].content
