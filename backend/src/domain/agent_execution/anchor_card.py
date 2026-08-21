"""앵커 포지션 카드 생성과 저장의 application 유스케이스.

흐름을 세 단계로 나눈다.

1. 준비 transaction — lease·버전 확인, 모델 바인딩 기록, cache lookup, snapshot 조립.
   끝나면 transaction 을 닫는다.
2. transaction 밖 — AI 호출. 모델을 기다리는 동안 DB 잠금을 쥐고 있지 않는다.
3. 저장 transaction — lease·버전·source identity 재확인 후 카드·가격·근거·상태를 원자 저장.

Worker polling loop 와는 분리되어 있다. 이 함수는 이미 선점된 실행 하나를 처리할 뿐이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from brokerage_ai.f3 import (
    Evidence,
    EvidenceKind,
    NegotiationSide,
    PositionCardAnalysis,
    PositionCardGenerationRequest,
    PositionCardGenerationResult,
    PositionCardGenerator,
    SourceIdentity,
    validate_generation_result,
)
from sqlmodel import Session

from domain.agent_execution import repository, snapshot
from domain.agent_execution.cache_key import position_card_cache_key
from domain.agent_execution.fingerprint import as_of_bucket, input_fingerprint
from domain.agent_execution.models import (
    AgentRun,
    AnchorType,
    InputVersionChangedError,
    LeaseNotHeldError,
    NegotiationPositionAnalysis,
    NegotiationPositionEvidence,
    NegotiationPositionPrice,
    anchor_of,
)
from domain.agent_execution.pii_guard import assert_no_personal_data
from domain.agent_execution.service import current_anchor_version


class GenerationBindingError(RuntimeError):
    """이 실행에 쓸 모델·프롬프트·워크플로 바인딩을 확정할 수 없다.

    다른 사무소의 설정을 넣었는지, 이미 다른 구성으로 묶인 실행인지 구분해서 알리지 않는다.
    구분해서 알리면 남의 설정 존재 여부가 새어 나간다.
    """


class SourceChangedError(RuntimeError):
    """AI 호출 도중 모델 입력이 바뀌었다. 이 결과는 저장할 수 없다.

    앵커 장부 필드, 단지명, 당사자 역할, 상담 로그 집합, 로그 범위, 날짜 bucket 중 하나라도
    달라지면 이전 입력으로 만든 카드는 지금 상태를 대리하지 않는다.
    """


class CachedCardUnavailableError(RuntimeError):
    """재사용하려던 카드가 저장 직전에 더 이상 유효하지 않다.

    준비와 저장 사이에 무효화됐거나 조건에 맞지 않게 됐다. 이 실행은 다시 준비해서 새로
    생성해야 하므로 재시도 가능한 오류로 올린다.
    """


@dataclass(frozen=True)
class GenerationBinding:
    """실행 1건에 쓸 생성 구성.

    Backend 는 Provider 나 모델을 고르지 않는다. 무엇을 쓸지는 호출 조립 지점이 정해서
    여기에 주입하고, Backend 는 그 설정이 이 사무소의 포지션 카드용인지 확인한 뒤 allowlist
    필드만 snapshot 으로 기록한다. 호출자가 준 임의 dict 는 저장하지 않는다.
    """

    generator: PositionCardGenerator
    model_config_id: int

    @property
    def prompt_version(self) -> str:
        return self.generator.versions.prompt_version

    @property
    def workflow_version(self) -> str:
        return self.generator.versions.workflow_version


@dataclass(frozen=True)
class AnchorPositionCardResult:
    """유스케이스 결과. 카드가 새로 생겼는지 재사용됐는지 알려준다."""

    run_id: int
    position_analysis_id: int
    cache_hit: bool
    cache_key: str
    negotiation_side: NegotiationSide
    anchor_id: int
    target_label: str


@dataclass(frozen=True)
class PreparedGeneration:
    """준비 단계 결과. ORM 행도 열린 transaction 도 들고 있지 않다.

    `source`, `scope_identity`, `input_fingerprint` 는 cache hit 에서도 항상 채운다. 저장 직전
    재검증이 cache miss 에서만 돌면 재사용 경로로 낡은 카드가 그대로 확정된다.

    `scope` 객체 자체는 들고 다니지 않는다. 저장 단계는 현재 장부에서 범위를 **다시** 만들어야
    준비 이후에 생긴 당사자 관계와 그 로그를 볼 수 있다. 준비 시점 범위는 digest 로만 비교한다.
    """

    brokerage_id: int
    anchor_type: AnchorType
    anchor_id: int
    negotiation_side: NegotiationSide
    target_label: str
    data_version: int
    cache_key: str
    scope_identity: str
    source: SourceIdentity
    input_fingerprint: str
    as_of_bucket: str
    model_snapshot: dict[str, object]
    cached_analysis_id: int | None
    request: PositionCardGenerationRequest | None
    secrets: tuple[str, ...]


def _require_leased_run(
    session: Session, run_id: int, worker_id: str, attempt_count: int
) -> AgentRun:
    run = repository.find_leased_run(session, run_id, worker_id, attempt_count)
    if run is None:
        raise LeaseNotHeldError("the worker does not hold a valid lease on this run")
    return run


def _resolve_binding(
    session: Session,
    run: AgentRun,
    binding: GenerationBinding,
    worker_id: str,
    attempt_count: int,
) -> dict[str, object]:
    """실행의 모델 바인딩을 확정한다. 처음이면 기록하고, 이미 있으면 같은지 확인한다.

    바인딩이 일부만 채워진 행은 새 값으로 덮지 않는다. 어떤 구성으로 돌았는지 확인할 수 없는
    실행을 정상으로 만들면 감사 추적이 끊긴다.
    """
    config = repository.find_position_card_model_config(
        session, run.brokerage_id, binding.model_config_id
    )
    if config is None:
        raise GenerationBindingError("the model configuration is not usable for this run")
    expected = repository.safe_model_snapshot(config)

    recorded = (run.model_config_id, run.prompt_version, run.workflow_version)
    if all(value is None for value in recorded):
        changed = repository.bind_run_execution_configuration(
            session,
            run.id or 0,
            run.brokerage_id,
            worker_id,
            attempt_count,
            model_config_id=binding.model_config_id,
            model_snapshot=expected,
            prompt_version=binding.prompt_version,
            workflow_version=binding.workflow_version,
        )
        if changed != 1:
            raise GenerationBindingError("the execution binding could not be recorded")
        return expected

    if any(value is None for value in recorded):
        raise GenerationBindingError("the run carries an incomplete execution binding")

    if (
        run.model_config_id != binding.model_config_id
        or run.prompt_version != binding.prompt_version
        or run.workflow_version != binding.workflow_version
        or run.model_snapshot != expected
    ):
        raise GenerationBindingError("the run is already bound to a different configuration")
    return expected


def prepare_generation(
    session: Session,
    run_id: int,
    worker_id: str,
    attempt_count: int,
    binding: GenerationBinding,
    *,
    as_of: datetime | None = None,
) -> PreparedGeneration:
    """1단계. 바인딩을 확정하고 입력을 조립한 뒤 transaction 을 닫는다."""
    moment = as_of or datetime.now(UTC)
    try:
        run = _require_leased_run(session, run_id, worker_id, attempt_count)
        model_snapshot = _resolve_binding(session, run, binding, worker_id, attempt_count)

        anchor_type, anchor_id = anchor_of(run)
        if current_anchor_version(session, run, anchor_type, anchor_id) != run.input_data_version:
            raise InputVersionChangedError("the anchor changed after the run was queued")

        assembled = snapshot.build_anchor_snapshot(
            session,
            run.brokerage_id,
            anchor_type,
            anchor_id,
            as_of=moment,
            requested_by=run.requested_by,
        )
        request = assembled.request
        if request.source.data_version != run.input_data_version:
            raise InputVersionChangedError("the anchor changed while the snapshot was assembled")

        side = NegotiationSide(anchor_type.value)
        fingerprint = input_fingerprint(request)
        scope_identity = assembled.scope.identity()
        cache_key = position_card_cache_key(
            brokerage_id=run.brokerage_id,
            negotiation_side=side.value,
            anchor_type=side.value,
            anchor_id=request.anchor_id,
            data_version=request.source.data_version,
            interaction_count=request.source.interaction_count,
            last_interaction_at=request.source.last_interaction_at,
            max_interaction_id=request.source.max_interaction_id,
            agent_type=run.agent_type,
            model_config_id=binding.model_config_id,
            prompt_version=binding.prompt_version,
            workflow_version=binding.workflow_version,
            input_fingerprint=fingerprint,
            scope_identity=scope_identity,
        )
        # cache key 만 믿지 않는다. 대상, 측면, 입력 버전과 저장된 상담 집합까지 대조한다.
        cached = repository.find_active_position_card(
            session,
            run.brokerage_id,
            cache_key=cache_key,
            negotiation_side=side.value,
            listing_id=anchor_id if side is NegotiationSide.LISTING else None,
            requirement_id=anchor_id if side is NegotiationSide.REQUIREMENT else None,
            data_version=run.input_data_version,
            interactions=repository.InteractionSummary(
                request.source.interaction_count,
                request.source.last_interaction_at,
                request.source.max_interaction_id,
            ),
        )
        prepared = PreparedGeneration(
            brokerage_id=run.brokerage_id,
            anchor_type=anchor_type,
            anchor_id=anchor_id,
            negotiation_side=side,
            target_label=request.target_label,
            data_version=run.input_data_version,
            cache_key=cache_key,
            scope_identity=scope_identity,
            source=request.source,
            input_fingerprint=fingerprint,
            as_of_bucket=as_of_bucket(request),
            model_snapshot=model_snapshot,
            cached_analysis_id=cached.id if cached else None,
            # cache hit 이면 마스킹 본문을 들고 다니지 않는다. 신원과 범위만 남긴다.
            request=None if cached else request,
            secrets=() if cached else assembled.secrets,
        )
        session.commit()
    except BaseException:
        # 도메인 오류에서도 열린 transaction 을 남기지 않는다. 남기면 AI 를 기다리는 동안
        # 이 커넥션이 idle in transaction 으로 잠긴다.
        session.rollback()
        raise
    else:
        session.rollback()
    return prepared


def _evidence_rows(
    brokerage_id: int, analysis_id: int, analysis: PositionCardAnalysis, contents: dict[int, str]
) -> list[NegotiationPositionEvidence]:
    """카드 항목별 근거를 결정적인 `field_name` 으로 펼친다."""
    grouped: list[tuple[str, tuple[Evidence, ...]]] = [
        ("intent", analysis.intent.evidence),
        ("urgency", analysis.urgency.evidence),
        ("contactability", analysis.contactability.evidence),
    ]
    grouped.extend(
        (f"price.{assessment.price_kind.value}", assessment.basis) for assessment in analysis.price
    )
    for label, conditions in (
        ("timing.constraints", analysis.timing.constraints),
        ("flexible", analysis.flexible),
        ("inflexible", analysis.inflexible),
    ):
        grouped.extend(
            (f"{label}.{index}", condition.evidence) for index, condition in enumerate(conditions)
        )

    rows: list[NegotiationPositionEvidence] = []
    for field_name, evidence in grouped:
        for order, item in enumerate(evidence):
            start = end = None
            if item.kind is EvidenceKind.QUOTE and item.quote_text is not None:
                # 길이를 보존한 마스킹이라 마스킹 본문의 위치가 원문의 같은 위치다.
                content = contents[item.interaction_id or 0]
                start = content.index(item.quote_text)
                end = start + len(item.quote_text)
            rows.append(
                NegotiationPositionEvidence(
                    brokerage_id=brokerage_id,
                    position_analysis_id=analysis_id,
                    field_name=field_name,
                    evidence_type=item.kind.value,
                    interaction_id=item.interaction_id,
                    quote_text=item.quote_text,
                    quote_start_offset=start,
                    quote_end_offset=end,
                    note=item.note,
                    display_order=order,
                )
            )
    return rows


def _card_row(
    run: AgentRun,
    prepared: PreparedGeneration,
    request: PositionCardGenerationRequest,
    result: PositionCardGenerationResult,
) -> NegotiationPositionAnalysis:
    analysis = result.analysis
    listing_side = prepared.negotiation_side is NegotiationSide.LISTING
    # 가격이 정확히 하나일 때만 기존 scalar 컬럼을 호환 projection 으로 채운다. 여러 개일 때
    # 첫 번째를 대표로 고르면 나머지 거래 유형의 금액이 조용히 사라진다.
    single = analysis.price[0] if len(analysis.price) == 1 else None
    return NegotiationPositionAnalysis(
        brokerage_id=run.brokerage_id,
        agent_run_id=run.id or 0,
        negotiation_side=prepared.negotiation_side.value,
        unit_id=run.target_unit_id if listing_side else None,
        listing_id=prepared.anchor_id if listing_side else None,
        requirement_id=None if listing_side else prepared.anchor_id,
        target_label=prepared.target_label,
        cache_key=prepared.cache_key,
        source_interaction_count=request.source.interaction_count,
        last_interaction_at=request.source.last_interaction_at,
        data_version=request.source.data_version,
        negotiation_intent=analysis.intent.value.value,
        stated_price_amount=single.stated_amount if single else None,
        estimated_price_amount=single.estimated_amount if single else None,
        price_estimation_basis=None,
        urgency=analysis.urgency.value.value,
        preferred_timing=analysis.timing.model_dump(mode="json"),
        flexible_conditions=[item.model_dump(mode="json") for item in analysis.flexible],
        inflexible_conditions=[item.model_dump(mode="json") for item in analysis.inflexible],
        contactability_status=analysis.contactability.status.value,
        contactability_note=analysis.contactability.note,
        analysis_snapshot=result.model_dump(mode="json"),
    )


def _price_rows(
    brokerage_id: int, analysis_id: int, analysis: PositionCardAnalysis
) -> list[NegotiationPositionPrice]:
    return [
        NegotiationPositionPrice(
            brokerage_id=brokerage_id,
            position_analysis_id=analysis_id,
            price_kind=assessment.price_kind.value,
            stated_amount=assessment.stated_amount,
            stated_monthly_amount=assessment.stated_monthly_amount,
            estimated_amount=assessment.estimated_amount,
            estimated_monthly_amount=assessment.estimated_monthly_amount,
            display_order=order,
        )
        for order, assessment in enumerate(analysis.price)
    ]


def _output_snapshot(
    run: AgentRun,
    prepared: PreparedGeneration,
    result: PositionCardGenerationResult | None,
    analysis_id: int,
) -> dict[str, object]:
    """실행에 남길 비식별 요약. 카드 본문과 상담 로그는 여기에 중복 저장하지 않는다.

    cache hit 이면 진단이 없다. 없는 값을 지어내지 않고 실행에 기록된 model snapshot 의
    허용 필드만 쓴다.
    """
    diagnostics = result.diagnostics if result else None
    return {
        "anchor_type": prepared.anchor_type.value,
        "anchor_id": prepared.anchor_id,
        "target_label": prepared.target_label,
        "input_data_version": prepared.data_version,
        "position_analysis_id": analysis_id,
        "cache_hit": result is None,
        "contract_version": result.contract_version if result else _CONTRACT_VERSION_FOR_CACHE_HIT,
        "prompt_version": result.prompt_version if result else run.prompt_version,
        "workflow_version": result.workflow_version if result else run.workflow_version,
        "provider": diagnostics.provider.value
        if diagnostics
        else prepared.model_snapshot.get("provider"),
        "model": diagnostics.model if diagnostics else prepared.model_snapshot.get("model_name"),
    }


# cache hit 은 모델을 부르지 않지만 카드 자체는 이 계약 버전으로 만들어져 저장돼 있다.
_CONTRACT_VERSION_FOR_CACHE_HIT = "position-card:v1"


def _expected_model_snapshot(
    session: Session, run: AgentRun, binding: GenerationBinding
) -> dict[str, object]:
    """지금 이 실행에 기대되는 안전한 model snapshot."""
    config = repository.find_position_card_model_config(
        session, run.brokerage_id, binding.model_config_id
    )
    if config is None:
        raise GenerationBindingError("the model configuration is not usable for this run")
    return repository.safe_model_snapshot(config)


def _require_reusable_card(
    session: Session, run: AgentRun, prepared: PreparedGeneration, source: SourceIdentity
) -> int:
    """재사용할 카드를 저장 직전에 다시 조회한다.

    준비와 저장 사이에 `invalidated_at` 이 찍히거나 조건이 어긋날 수 있다. 준비 시점 ID 를
    그대로 믿으면 무효화된 카드를 가리킨 채 `ANCHOR_READY` 로 넘어간다. 여기서는 새 모델
    호출을 하지 않고, 다시 준비할 수 있게 재시도 가능한 오류로 올린다.
    """
    listing_side = prepared.negotiation_side is NegotiationSide.LISTING
    found = repository.lock_active_position_card_for_store(
        session,
        run.brokerage_id,
        cache_key=prepared.cache_key,
        negotiation_side=prepared.negotiation_side.value,
        listing_id=prepared.anchor_id if listing_side else None,
        requirement_id=None if listing_side else prepared.anchor_id,
        data_version=prepared.data_version,
        interactions=repository.InteractionSummary(
            source.interaction_count, source.last_interaction_at, source.max_interaction_id
        ),
    )
    if found is None or found.id is None or found.id != prepared.cached_analysis_id:
        raise CachedCardUnavailableError("the cached position card is no longer reusable")
    return found.id


def store_generated_card(
    session: Session,
    run_id: int,
    worker_id: str,
    attempt_count: int,
    binding: GenerationBinding,
    prepared: PreparedGeneration,
    result: PositionCardGenerationResult | None,
) -> AnchorPositionCardResult:
    """3단계. 재검증하고 카드·가격·근거·상태를 한 transaction 에 저장한다."""
    try:
        run = _require_leased_run(session, run_id, worker_id, attempt_count)
        if run.brokerage_id != prepared.brokerage_id:
            raise LeaseNotHeldError("the run belongs to a different brokerage")
        # model_snapshot 도 실행 감사 계약의 일부다. 네 값을 모두 본다.
        expected_snapshot = _expected_model_snapshot(session, run, binding)
        if (
            run.model_config_id != binding.model_config_id
            or run.prompt_version != binding.prompt_version
            or run.workflow_version != binding.workflow_version
            or run.model_snapshot != expected_snapshot
            or prepared.model_snapshot != expected_snapshot
        ):
            raise GenerationBindingError("the run binding changed while the card was generated")

        if (
            current_anchor_version(session, run, prepared.anchor_type, prepared.anchor_id)
            != prepared.data_version
        ):
            raise InputVersionChangedError("the anchor changed while the card was generated")

        # 범위를 현재 장부에서 **다시** 만든다. 준비 시점 범위를 재사용하면 그 사이에 생긴
        # 당사자 관계와 그 로그를 저장 단계가 영영 보지 못한다.
        current_scope = repository.build_interaction_scope(
            session, run.brokerage_id, prepared.anchor_type, prepared.anchor_id
        )
        if current_scope.identity() != prepared.scope_identity:
            # 로그 수가 우연히 같아도 범위가 달라졌으면 다른 입력이다.
            raise SourceChangedError("the consultation log scope changed during generation")

        # cache hit 과 miss 모두 여기서 상담 집합을 다시 센다. 재사용 경로만 빠져나가면
        # 낡은 카드가 그대로 확정된다.
        current = snapshot.current_source_identity(session, current_scope, prepared.data_version)
        if current != prepared.source:
            raise SourceChangedError(
                "the consultation log set changed while the card was generated"
            )

        # 앵커 row_version 은 세대 스펙·단지명·당사자 역할·날짜 bucket 이 바뀌어도 그대로다.
        # 모델에 넘긴 입력 전체를 다시 조립해 지문으로 비교한다.
        rebuilt = snapshot.build_anchor_snapshot(
            session,
            run.brokerage_id,
            prepared.anchor_type,
            prepared.anchor_id,
            as_of=datetime.fromisoformat(prepared.as_of_bucket).replace(tzinfo=UTC),
            requested_by=run.requested_by,
        )
        if input_fingerprint(rebuilt.request) != prepared.input_fingerprint:
            raise SourceChangedError("the model input changed while the card was generated")

        analysis_id = prepared.cached_analysis_id
        request = prepared.request
        if result is None:
            # cache hit. 재사용하려던 카드가 저장 직전에도 유효한지 다시 확인한다.
            analysis_id = _require_reusable_card(session, run, prepared, current)
        elif result is not None and request is not None:
            if (
                result.prompt_version != binding.prompt_version
                or result.workflow_version != binding.workflow_version
            ):
                raise GenerationBindingError(
                    "the result was produced by a different prompt or workflow version"
                )
            validate_generation_result(request, result)
            assert_no_personal_data(result.analysis, prepared.secrets)

            stored = repository.insert_position_card(
                session, _card_row(run, prepared, request, result)
            )
            if stored is None:
                # 같은 키를 다른 실행이 먼저 넣었다. 진 쪽은 그 카드를 재사용한다.
                won = repository.lock_card_that_won_the_cache_key(
                    session, run.brokerage_id, prepared.cache_key
                )
                if won is None:  # pragma: no cover - 방어
                    raise SourceChangedError("the winning card disappeared")
                analysis_id = won.id
            else:
                analysis_id = stored.id or 0
                repository.insert_position_prices(
                    session, _price_rows(run.brokerage_id, analysis_id, result.analysis)
                )
                repository.insert_position_evidence(
                    session,
                    _evidence_rows(
                        run.brokerage_id, analysis_id, result.analysis, request.log_contents()
                    ),
                )

        if analysis_id is None:
            raise SourceChangedError("no position card is available for this run")

        usage = result.diagnostics.usage if result and result.diagnostics else None
        latency = result.diagnostics.latency_ms if result and result.diagnostics else None
        changed = repository.mark_run_anchor_ready(
            session,
            run_id,
            run.brokerage_id,
            worker_id,
            attempt_count,
            output_snapshot=_output_snapshot(run, prepared, result, analysis_id),
            input_tokens=usage.input_tokens if usage else 0,
            # total 만 오는 Provider 가 있어 output 을 total 로 덮지 않는다.
            output_tokens=usage.output_tokens if usage and usage.output_tokens else 0,
            latency_ms=int(latency) if latency is not None else None,
        )
        if changed != 1:
            raise LeaseNotHeldError("the lease was lost before the run could advance")
        session.commit()
    except BaseException:
        session.rollback()
        raise

    return AnchorPositionCardResult(
        run_id=run_id,
        position_analysis_id=analysis_id,
        cache_hit=result is None,
        cache_key=prepared.cache_key,
        negotiation_side=prepared.negotiation_side,
        anchor_id=prepared.anchor_id,
        target_label=prepared.target_label,
    )


async def generate_and_store_anchor_position_card(
    session: Session,
    *,
    run_id: int,
    worker_id: str,
    attempt_count: int,
    binding: GenerationBinding,
    as_of: datetime | None = None,
) -> AnchorPositionCardResult:
    """선점한 실행의 앵커 포지션 카드를 확보하고 `ANCHOR_READY` 로 옮긴다.

    cache hit 이면 모델을 호출하지 않는다. AI 호출은 두 transaction 사이에서 일어나며 그
    동안 이 세션은 열린 transaction 을 갖지 않는다.
    """
    prepared = prepare_generation(session, run_id, worker_id, attempt_count, binding, as_of=as_of)

    result: PositionCardGenerationResult | None = None
    if prepared.request is not None:
        result = await binding.generator.generate_position_card(prepared.request)

    return store_generated_card(
        session, run_id, worker_id, attempt_count, binding, prepared, result
    )
