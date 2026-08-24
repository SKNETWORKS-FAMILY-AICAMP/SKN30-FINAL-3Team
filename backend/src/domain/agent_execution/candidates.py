"""결정적 SQL 후보 추출.

LLM 을 쓰지 않는다 (F3-SQ-01). 앵커 **카드의 추정값**을 조회 조건으로 삼아 (F3-SQ-03)
반대편 장부에서 후보를 고르고, 가격 근접도·평형 일치·접수 최신성으로 점수를 낸다
(F3-SQ-04). 이 점수는 **카드화 우선순위**일 뿐이며 중개 등급이 아니다.

상위 15건만 카드화하지만 나머지를 버리지 않는다 (F3-BR-13, F3-BR-14). 전체 후보의 ID,
구성 점수, 정렬 순서와 사용한 조회 조건을 `match_evaluation.candidate_selection_snapshot`
에 그대로 보존한다. 컷이 아니라 페이징이다.

점수 계산은 Python 에서 한다. SQL 부동소수 정렬은 DB 버전과 로케일에 따라 동점 순서가
흔들릴 수 있고, 여기서는 tie-breaker 까지 결정적이어야 한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlmodel import Session

from domain.agent_execution import repository
from domain.agent_execution.models import (
    ANCHOR_READY_STATUS,
    CANDIDATES_READY_STATUS,
    AgentRun,
    AnchorType,
    InputVersionChangedError,
    LeaseNotHeldError,
    MatchEvaluation,
    NegotiationPositionAnalysis,
    anchor_of,
)
from domain.agent_execution.service import current_anchor_version

# snapshot 구조가 바뀌면 올린다. 저장된 예전 snapshot 을 새 구조로 읽지 않기 위해서다.
# v2 는 거래 유형·활성 상태 조건과 월세 두 축을 조회 조건에 함께 담는다.
CANDIDATE_SELECTION_SCHEMA_VERSION = "candidate-selection:v2"

# ── 거래 유형 어휘 ─────────────────────────────────────────────────────────────
#
# 매물장과 구입장은 **같은 거래를 다른 말로 부른다** (F1 데이터 항목 13.1·13.2).
# 매물장은 거래 가능 플래그를 `매매`·`전세`·`월세` 로 두고, 구입장 `구분` 은
# `매수`·`매도`·`전세`·`월세` 다. 이 표가 그 대응의 유일한 정본이다.
#
# `매도` 는 팔려는 수요라 매물의 반대편이 아니다. 어느 방향으로도 매핑하지 않으므로
# 매도 구입장은 매물 앵커의 후보가 되지 않고, 매도 구입장을 앵커로 잡으면 호환되는 매물
# 거래 유형이 없어 후보가 0건이 된다.

PRICE_KIND_TO_DEMAND_TYPES: dict[str, frozenset[str]] = {
    "SALE": frozenset({"매수"}),
    "JEONSE": frozenset({"전세"}),
    "MONTHLY_RENT": frozenset({"월세"}),
}

DEMAND_TYPE_TO_PRICE_KIND: dict[str, str] = {
    "매수": "SALE",
    "전세": "JEONSE",
    "월세": "MONTHLY_RENT",
}

# ── 활성 업무 상태 ─────────────────────────────────────────────────────────────
#
# F1 은 아직 매물·구입장 상태 값 목록을 확정하지 않았다 (API 계약). 확정 전까지는 서버가
# 신규 저장에 쓰는 기본값을 "아직 진행 중" 으로 본다. 종료된 건이 후보로 올라오면 이미 끝난
# 거래에 연락하자는 제안이 나온다.
#
# 값 목록이 확정되면 이 두 집합을 먼저 고치고 project-wiki 를 함께 갱신한다.

ACTIVE_LISTING_STATUSES = frozenset({"RECEIVED"})
ACTIVE_REQUIREMENT_STATUSES = frozenset({"ACTIVE"})

# 우선 카드화하는 상위 건수 (F3-BR-13). 나머지는 snapshot 에 그대로 남는다.
CANDIDATE_CARD_LIMIT = 15

# 가격 밴드. 앵커 추정가에서 이 비율만큼 벗어난 후보까지 포함한다. 정확히 일치하는 값만
# 남기면 "예산이 조금 모자란 손님"이 통째로 사라지는데, 그 손님이야말로 양보 지점을 물어볼
# 대상이다. MVP 조정값이며 승인된 요구사항 수치가 아니다.
PRICE_TOLERANCE_RATIO = Decimal("0.10")

# 평형 일치 허용 오차(평). 장부 평형은 소수점 표기가 제각각이라 정확히 같은 값만 세면
# 실제로 같은 평형이 어긋난다.
PYEONG_TOLERANCE = Decimal("1")

# 점수 가중치. 셋의 합은 1 이다. MVP 조정값이며 중개 등급과 무관하다 (F3-SQ-04).
PRICE_WEIGHT = Decimal("0.5")
AREA_WEIGHT = Decimal("0.3")
RECENCY_WEIGHT = Decimal("0.2")

# 접수 최신성의 반감 기준일. 접수 30일이 지나면 최신성 점수가 절반이 된다.
RECENCY_HALF_LIFE_DAYS = Decimal("30")

# 점수는 소수점 6자리에서 고정한다. 부동소수 잔차 때문에 동점이 동점으로 보이지 않으면
# tie-breaker 가 의미를 잃는다.
SCORE_PRECISION = Decimal("0.000001")


class AnchorCardMissingError(RuntimeError):
    """`ANCHOR_READY` 인데 재사용할 앵커 카드를 찾을 수 없다.

    실행이 가리키는 카드가 무효화됐거나 다른 사무소의 것이다. 이 상태로는 후보 조회 조건을
    만들 수 없다.
    """


@dataclass(frozen=True)
class CandidateScore:
    """후보 1건의 구성 점수. 최종 중개 등급이 아니라 카드화 우선순위다."""

    candidate_id: int
    price_proximity: Decimal
    area_match: Decimal
    recency: Decimal
    total: Decimal
    price_amount: int | None
    monthly_amount: int | None
    received_at: date | None

    def as_snapshot(self, rank: int, selected: bool) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "rank": rank,
            "selected_for_cards": selected,
            "score": str(self.total),
            "price_proximity": str(self.price_proximity),
            "area_match": str(self.area_match),
            "recency": str(self.recency),
            "price_amount": self.price_amount,
            # 월세 후보의 월 차임. 비교 축이 아니라 보존값이다.
            "monthly_amount": self.monthly_amount,
            "received_at": self.received_at.isoformat() if self.received_at else None,
        }


@dataclass(frozen=True)
class CandidateCriteria:
    """실제로 적용한 조회 조건. 후보가 0건이어도 이 값은 그대로 저장한다 (F3-CR-11)."""

    candidate_side: AnchorType
    price_kind: str | None
    price_amount: int | None
    monthly_amount: int | None
    price_is_estimated: bool
    price_floor_amount: int | None
    price_ceiling_amount: int | None
    anchor_pyeong: Decimal | None
    complex_id: int | None
    demand_types: tuple[str, ...]
    active_statuses: tuple[str, ...]
    as_of: date

    def as_snapshot(self) -> dict[str, object]:
        return {
            "candidate_side": self.candidate_side.value,
            "price_kind": self.price_kind,
            "price_amount": self.price_amount,
            # 월세 앵커의 월 차임. 구입장에 대응하는 예산 축이 없어 비교에는 쓰지 않는다.
            "monthly_amount": self.monthly_amount,
            "price_source": "ESTIMATED" if self.price_is_estimated else "STATED",
            "price_tolerance_ratio": str(PRICE_TOLERANCE_RATIO),
            "price_floor_amount": self.price_floor_amount,
            "price_ceiling_amount": self.price_ceiling_amount,
            "compared_amount_axis": _compared_axis(self.price_kind),
            "anchor_pyeong": str(self.anchor_pyeong) if self.anchor_pyeong is not None else None,
            "pyeong_tolerance": str(PYEONG_TOLERANCE),
            "complex_id": self.complex_id,
            "demand_types": list(self.demand_types),
            "active_statuses": list(self.active_statuses),
            "as_of": self.as_of.isoformat(),
        }


def _compared_axis(price_kind: str | None) -> str | None:
    """무엇을 비교했는지 snapshot 에 남긴다.

    월세는 보증금과 월 차임이 별도 축인데 구입장에는 월 차임에 대응하는 예산 축이 없다.
    그래서 보증금만 비교한다. 이 사실을 저장해 두지 않으면 나중에 결과를 보고 무엇을
    비교한 것인지 알 수 없다.
    """
    if price_kind is None:
        return None
    return "MONTHLY_RENT_DEPOSIT" if price_kind == "MONTHLY_RENT" else price_kind


@dataclass(frozen=True)
class CandidateSelection:
    """후보 추출 결과. 상위 15건은 카드화 대상이고 나머지도 전부 보존한다."""

    criteria: CandidateCriteria
    ordered: tuple[CandidateScore, ...]

    @property
    def total_count(self) -> int:
        return len(self.ordered)

    @property
    def carded(self) -> tuple[CandidateScore, ...]:
        return self.ordered[:CANDIDATE_CARD_LIMIT]

    @property
    def remaining_count(self) -> int:
        return max(0, self.total_count - CANDIDATE_CARD_LIMIT)

    def snapshot(self, anchor: NegotiationPositionAnalysis) -> dict[str, object]:
        """조회 조건과 **전체** 후보 집합. 15건 이후를 조용히 지우지 않는다."""
        return {
            "schema": CANDIDATE_SELECTION_SCHEMA_VERSION,
            "anchor": {
                "negotiation_side": anchor.negotiation_side,
                "position_analysis_id": anchor.id,
                "listing_id": anchor.listing_id,
                "requirement_id": anchor.requirement_id,
                "data_version": anchor.data_version,
            },
            "criteria": self.criteria.as_snapshot(),
            "score_weights": {
                "price_proximity": str(PRICE_WEIGHT),
                "area_match": str(AREA_WEIGHT),
                "recency": str(RECENCY_WEIGHT),
                "recency_half_life_days": str(RECENCY_HALF_LIFE_DAYS),
            },
            "card_limit": CANDIDATE_CARD_LIMIT,
            "total_count": self.total_count,
            "carded_count": len(self.carded),
            "remaining_count": self.remaining_count,
            # ponytail: 후보 수에 비례해 JSONB 가 커진다. 7,200행 규모에서 수백 KB 수준이다.
            # 페이징 조회가 실제로 느려지면 후보 집합만 별도 테이블로 옮긴다.
            "candidates": [
                score.as_snapshot(rank=index + 1, selected=index < CANDIDATE_CARD_LIMIT)
                for index, score in enumerate(self.ordered)
            ],
        }


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(SCORE_PRECISION)


def _price_proximity(anchor_amount: int | None, candidate_amount: int | None) -> Decimal:
    """가격 근접도. 금액을 알 수 없는 후보는 0 이라 뒤로 밀린다.

    중립값 0.5 를 주면 금액을 아는 후보와 모르는 후보의 순서가 뒤섞인다. 카드화는 15장
    한정이므로 판단 재료가 있는 후보를 먼저 세우는 쪽이 낫다.
    """
    if not anchor_amount or candidate_amount is None:
        return Decimal(0)
    gap = abs(Decimal(candidate_amount) - Decimal(anchor_amount)) / Decimal(anchor_amount)
    return _quantize(max(Decimal(0), Decimal(1) - gap))


def _area_match(anchor_pyeong: Decimal | None, candidate_pyeongs: tuple[Decimal, ...]) -> Decimal:
    """평형 일치. 희망 평형을 밝히지 않은 후보는 0 이다.

    조건이 없다는 것과 조건이 맞는다는 것을 같은 점수로 두면, 아무 조건도 적지 않은 행이
    정확히 맞는 행과 같은 순위를 받는다.
    """
    if anchor_pyeong is None or not candidate_pyeongs:
        return Decimal(0)
    closest = min(abs(value - anchor_pyeong) for value in candidate_pyeongs)
    return Decimal(1) if closest <= PYEONG_TOLERANCE else Decimal(0)


def _recency(received_at: date | None, as_of: date) -> Decimal:
    """접수 최신성. 미래 접수일도 1 로 고정해 음수 경과일이 점수를 부풀리지 않게 한다."""
    if received_at is None:
        return Decimal(0)
    days = Decimal(max(0, (as_of - received_at).days))
    return _quantize(Decimal(1) / (Decimal(1) + days / RECENCY_HALF_LIFE_DAYS))


def _score(
    candidate_id: int,
    *,
    anchor_amount: int | None,
    candidate_amount: int | None,
    candidate_monthly_amount: int | None = None,
    anchor_pyeong: Decimal | None,
    candidate_pyeongs: tuple[Decimal, ...],
    received_at: date | None,
    as_of: date,
) -> CandidateScore:
    """가격 근접도는 **주 금액 축 하나**만 비교한다.

    월세의 월 차임은 구입장에 대응하는 예산 축이 없어 점수에 넣지 않는다. 값은 버리지 않고
    snapshot 에 그대로 보존해 화면이 보증금과 차임을 함께 보여줄 수 있게 한다.
    """
    price = _price_proximity(anchor_amount, candidate_amount)
    area = _area_match(anchor_pyeong, candidate_pyeongs)
    recency = _recency(received_at, as_of)
    total = _quantize(price * PRICE_WEIGHT + area * AREA_WEIGHT + recency * RECENCY_WEIGHT)
    return CandidateScore(
        candidate_id=candidate_id,
        price_proximity=price,
        area_match=area,
        recency=recency,
        total=total,
        price_amount=candidate_amount,
        monthly_amount=candidate_monthly_amount,
        received_at=received_at,
    )


def _order(scores: list[CandidateScore]) -> tuple[CandidateScore, ...]:
    """동점에서도 항상 같은 순서가 나오게 한다.

    점수 내림차순 → 접수 최신순 → ID 오름차순. 마지막 tie-breaker 가 유일하므로 전체
    순서가 결정적이다. 접수일이 없는 후보는 가장 오래된 것으로 취급한다.
    """
    return tuple(
        sorted(
            scores,
            key=lambda item: (
                -item.total,
                -(item.received_at.toordinal() if item.received_at else 0),
                item.candidate_id,
            ),
        )
    )


def _anchor_price(
    prices: list[repository.CandidatePriceRow],
) -> tuple[str | None, int | None, int | None, bool]:
    """후보 조회의 가격 축. `(price_kind, 주 금액, 월 차임, 추정가 여부)` 다.

    카드는 매매·전세·월세를 동시에 담을 수 있다. MVP 는 카드에 실린 **첫 번째** 거래
    유형(`display_order` 최소)을 축으로 쓴다. 이 순서는 카드 생성 시 `PriceKind` 열거 순서로
    결정적으로 정해지므로 같은 카드에서 항상 같은 축이 나온다.

    추정가가 있으면 추정가를 쓴다 (F3-SQ-03). 없으면 장부 표기가로 내려간다. 월세는 보증금과
    월 차임을 각각 같은 규칙으로 고른다.
    """
    if not prices:
        return None, None, None, False
    primary = prices[0]
    estimated = primary.estimated_amount is not None
    amount = primary.estimated_amount if estimated else primary.stated_amount
    monthly = (
        primary.estimated_monthly_amount
        if primary.estimated_monthly_amount is not None
        else primary.stated_monthly_amount
    )
    return primary.price_kind, amount, monthly, estimated


def _listing_anchor_criteria(
    session: Session, brokerage_id: int, anchor: NegotiationPositionAnalysis, as_of: date
) -> CandidateCriteria:
    """매물 앵커는 구입장 후보를 찾는다. 예산이 앵커 추정가에 닿는 손님이 대상이다.

    거래 유형이 맞는 손님만 본다. 매매 매물에 전세 손님이 붙거나 월세 매물에 매수 손님이
    붙으면 안 된다. 카드에 금액이 하나도 없으면 거래 유형을 정할 수 없어 후보도 없다.
    """
    prices = repository.list_position_card_prices(session, brokerage_id, anchor.id or 0)
    price_kind, amount, monthly, estimated = _anchor_price(prices)
    unit = repository.find_unit_specification(session, brokerage_id, anchor.unit_id or 0)
    floor = (
        int(Decimal(amount) * (Decimal(1) - PRICE_TOLERANCE_RATIO)) if amount is not None else None
    )
    return CandidateCriteria(
        candidate_side=AnchorType.REQUIREMENT,
        price_kind=price_kind,
        price_amount=amount,
        monthly_amount=monthly,
        price_is_estimated=estimated,
        # 예산 하한만 건다. 앵커보다 예산이 큰 손님은 언제나 후보다.
        price_floor_amount=floor,
        price_ceiling_amount=None,
        anchor_pyeong=unit.pyeong if unit else None,
        complex_id=unit.complex_id if unit else None,
        demand_types=tuple(sorted(PRICE_KIND_TO_DEMAND_TYPES.get(price_kind or "", frozenset()))),
        active_statuses=tuple(sorted(ACTIVE_REQUIREMENT_STATUSES)),
        as_of=as_of,
    )


def _requirement_anchor_criteria(
    session: Session,
    brokerage_id: int,
    anchor: NegotiationPositionAnalysis,
    demand_type: str | None,
    as_of: date,
) -> CandidateCriteria:
    """구입장 앵커는 매물 후보를 찾는다. 추정 예산 상한에 닿는 매물이 대상이다.

    후보 매물의 거래 유형은 앵커 카드의 `price_kind`(항상 `BUDGET`)가 아니라 구입장의
    **`demand_type`** 이 정한다. 매수 손님에게 월세 매물을 붙이지 않는다. 대응하는 거래
    유형이 없는 구분(`매도` 등)은 후보가 0건이다.
    """
    prices = repository.list_position_card_prices(session, brokerage_id, anchor.id or 0)
    _, amount, _, estimated = _anchor_price(prices)
    ceiling = (
        int(Decimal(amount) * (Decimal(1) + PRICE_TOLERANCE_RATIO)) if amount is not None else None
    )
    return CandidateCriteria(
        candidate_side=AnchorType.LISTING,
        price_kind=DEMAND_TYPE_TO_PRICE_KIND.get(demand_type or ""),
        price_amount=amount,
        monthly_amount=None,
        price_is_estimated=estimated,
        price_floor_amount=None,
        # 예산 상한만 건다. 싼 매물은 언제나 후보다.
        price_ceiling_amount=ceiling,
        anchor_pyeong=None,
        complex_id=None,
        demand_types=(demand_type,) if demand_type else (),
        active_statuses=tuple(sorted(ACTIVE_LISTING_STATUSES)),
        as_of=as_of,
    )


def select_candidates(
    session: Session,
    brokerage_id: int,
    anchor: NegotiationPositionAnalysis,
    anchor_type: AnchorType,
    *,
    as_of: date,
) -> CandidateSelection:
    """앵커 카드에서 반대편 후보를 고르고 점수를 매긴다. 아무것도 저장하지 않는다.

    LLM 을 부르지 않고 DB 쓰기도 하지 않는 순수 조회다. 조회 자체가 사무소와 F1 삭제 범위를
    적용하므로 다른 사무소의 행과 화면에서 사라진 행은 후보로 나오지 않는다.
    """
    if anchor_type is AnchorType.LISTING:
        criteria = _listing_anchor_criteria(session, brokerage_id, anchor, as_of)
        rows = repository.list_requirement_candidates(
            session,
            brokerage_id,
            demand_types=criteria.demand_types,
            active_statuses=criteria.active_statuses,
            budget_floor_amount=criteria.price_floor_amount,
            complex_id=criteria.complex_id,
        )
        scores = [
            _score(
                row.requirement_id,
                anchor_amount=criteria.price_amount,
                candidate_amount=row.max_budget_amount,
                anchor_pyeong=criteria.anchor_pyeong,
                candidate_pyeongs=row.desired_pyeongs,
                received_at=row.received_at,
                as_of=as_of,
            )
            for row in rows
        ]
    else:
        specification = repository.find_requirement_specification(
            session, brokerage_id, anchor.requirement_id or 0
        )
        criteria = _requirement_anchor_criteria(
            session,
            brokerage_id,
            anchor,
            specification.demand_type if specification else None,
            as_of,
        )
        preferred = repository.list_requirement_complex_ids(
            session, brokerage_id, anchor.requirement_id or 0
        )
        desired = specification.desired_pyeongs if specification else ()
        rows = repository.list_listing_candidates(
            session,
            brokerage_id,
            price_kind=criteria.price_kind,
            active_statuses=criteria.active_statuses,
            price_ceiling_amount=criteria.price_ceiling_amount,
            complex_ids=preferred,
        )
        scores = [
            _score(
                row.listing_id,
                anchor_amount=criteria.price_amount,
                candidate_amount=row.price_amount,
                candidate_monthly_amount=row.monthly_amount,
                # 매물 후보는 세대 평형 하나를 갖고, 앵커 구입장이 희망 평형 목록을 갖는다.
                # 비교 방향만 뒤집고 판정 규칙은 같게 둔다.
                anchor_pyeong=row.pyeong,
                candidate_pyeongs=desired,
                received_at=row.received_at,
                as_of=as_of,
            )
            for row in rows
        ]

    return CandidateSelection(criteria=criteria, ordered=_order(scores))


def _require_anchor_card(
    session: Session, run: AgentRun, anchor_type: AnchorType, anchor_id: int
) -> NegotiationPositionAnalysis:
    """실행이 확보한 앵커 카드를 되찾는다.

    `ANCHOR_READY` 전이와 같은 transaction 에서 기록한 `redacted_output_snapshot` 의
    `position_analysis_id` 를 쓴다. 그 ID 를 그대로 믿지 않고 사무소·측면·대상·활성 여부를
    다시 확인한다.
    """
    recorded = run.redacted_output_snapshot.get("position_analysis_id")
    if not isinstance(recorded, int):
        raise AnchorCardMissingError("the run does not record an anchor position card")
    found = repository.find_position_card_for_target(
        session,
        run.brokerage_id,
        position_analysis_id=recorded,
        negotiation_side=anchor_type.value,
        listing_id=anchor_id if anchor_type is AnchorType.LISTING else None,
        requirement_id=anchor_id if anchor_type is AnchorType.REQUIREMENT else None,
    )
    if found is None:
        raise AnchorCardMissingError("the anchor position card is no longer usable")
    return found


def store_candidate_selection(
    session: Session,
    run_id: int,
    worker_id: str,
    attempt_count: int,
    *,
    as_of: datetime | None = None,
) -> CandidateSelection:
    """`ANCHOR_READY` 실행의 후보를 뽑아 저장하고 `CANDIDATES_READY` 로 옮긴다.

    모델을 부르지 않으므로 조회·계산·저장을 한 transaction 안에서 끝낸다. 후보가 0건이어도
    조회 조건과 빈 후보 집합을 저장하고 정상 전이한다 (F3-CR-11).
    """
    moment = (as_of or datetime.now(UTC)).astimezone(UTC)
    try:
        run = repository.find_leased_run(
            session, run_id, worker_id, attempt_count, status=ANCHOR_READY_STATUS
        )
        if run is None:
            raise LeaseNotHeldError("the worker does not hold a valid lease on this run")

        anchor_type, anchor_id = anchor_of(run)
        if current_anchor_version(session, run, anchor_type, anchor_id) != run.input_data_version:
            raise InputVersionChangedError("the anchor changed after the card was stored")

        anchor = _require_anchor_card(session, run, anchor_type, anchor_id)
        selection = select_candidates(
            session, run.brokerage_id, anchor, anchor_type, as_of=moment.date()
        )

        # 재선점으로 이 단계가 다시 돌 수 있다. 헤더가 이미 있으면 새로 만들지 않고 갱신한다.
        header = repository.find_match_evaluation_for_run(session, run.brokerage_id, run_id)
        snapshot = selection.snapshot(anchor)
        if header is None:
            repository.insert_match_evaluation(
                session,
                MatchEvaluation(
                    brokerage_id=run.brokerage_id,
                    agent_run_id=run_id,
                    anchor_position_analysis_id=anchor.id or 0,
                    candidate_count=len(selection.carded),
                    data_version=run.input_data_version,
                    candidate_selection_snapshot=snapshot,
                ),
            )
        else:
            repository.update_match_evaluation_selection(
                session,
                run.brokerage_id,
                header.id or 0,
                anchor_position_analysis_id=anchor.id or 0,
                candidate_count=len(selection.carded),
                candidate_selection_snapshot=snapshot,
            )

        changed = repository.advance_run_status(
            session,
            run_id,
            run.brokerage_id,
            worker_id,
            attempt_count,
            expected_status=ANCHOR_READY_STATUS,
            next_status=CANDIDATES_READY_STATUS,
        )
        if changed != 1:
            raise LeaseNotHeldError("the lease was lost before the run could advance")
        session.commit()
    except BaseException:
        session.rollback()
        raise

    return selection
