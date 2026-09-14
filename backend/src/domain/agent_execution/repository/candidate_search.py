from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any, NamedTuple

from sqlalchemy import literal, or_
from sqlalchemy import select as sql_select
from sqlmodel import Session, col, select

from domain.property_ledger.models import (
    Party,
    PropertyListing,
    PropertyRequirement,
    PropertyRequirementComplex,
    PropertyUnit,
)


class RequirementCandidateRow(NamedTuple):
    """구입장 후보 1건의 점수 계산 입력."""

    requirement_id: int
    max_budget_amount: int | None
    desired_pyeongs: tuple[Decimal, ...]
    received_at: date | None


def list_requirement_candidates(
    session: Session,
    brokerage_id: int,
    *,
    demand_types: Sequence[str],
    active_statuses: Sequence[str],
    budget_floor_amount: int | None,
    complex_id: int | None,
) -> list[RequirementCandidateRow]:
    """매물 앵커의 반대편 후보. 조건에 맞는 구입장만 돌려준다 (F3-SQ-01).

    포함·제외는 전부 SQL 조건이다. 사무소, 구입장 삭제, 인물 삭제, **거래 구분**, **활성
    업무 상태**, 예산 하한과 희망 단지가 조건이며 평형과 최신성은 점수로만 반영한다.

    `demand_types` 는 앵커 매물의 거래 유형과 호환되는 구입장 구분이다. 매매 매물에 전세
    손님이 붙거나 월세 매물에 매수 손님이 붙으면 안 된다. 비어 있으면 호환되는 구분이
    없다는 뜻이므로 후보도 없다.

    희망 단지를 하나도 지정하지 않은 구입장은 단지를 가리지 않는 손님이므로 포함한다.
    예산이 비어 있는 구입장도 포함한다. 예산 미기재는 "못 산다"가 아니라 "아직 모른다"이며,
    금액을 모르는 후보는 가격 근접도 0 으로 뒤에 밀린다.
    """
    if not demand_types:
        return []

    conditions: list[Any] = [
        col(PropertyRequirement.brokerage_id) == brokerage_id,
        col(PropertyRequirement.is_deleted).is_(False),
        col(Party.is_deleted).is_(False),
        col(PropertyRequirement.demand_type).in_(sorted(demand_types)),
        col(PropertyRequirement.status).in_(sorted(active_statuses)),
    ]
    if budget_floor_amount is not None:
        conditions.append(
            or_(
                col(PropertyRequirement.max_budget_amount).is_(None),
                col(PropertyRequirement.max_budget_amount) >= budget_floor_amount,
            )
        )
    if complex_id is not None:
        wants_any_complex = (
            ~select(literal(1))
            .where(
                col(PropertyRequirementComplex.brokerage_id) == brokerage_id,
                col(PropertyRequirementComplex.requirement_id) == PropertyRequirement.id,
            )
            .exists()
        )
        wants_this_complex = (
            select(literal(1))
            .where(
                col(PropertyRequirementComplex.brokerage_id) == brokerage_id,
                col(PropertyRequirementComplex.requirement_id) == PropertyRequirement.id,
                col(PropertyRequirementComplex.complex_id) == complex_id,
            )
            .exists()
        )
        conditions.append(or_(wants_any_complex, wants_this_complex))

    statement = (
        select(
            col(PropertyRequirement.id),
            col(PropertyRequirement.max_budget_amount),
            col(PropertyRequirement.desired_pyeongs),
            col(PropertyRequirement.received_at),
        )
        .join(
            Party,
            (col(Party.brokerage_id) == PropertyRequirement.brokerage_id)
            & (col(Party.id) == PropertyRequirement.party_id),
        )
        .where(*conditions)
        .order_by(col(PropertyRequirement.id).asc())
    )
    return [
        RequirementCandidateRow(row[0], row[1], tuple(row[2] or ()), row[3])
        for row in session.execute(statement).all()
    ]


class ListingCandidateRow(NamedTuple):
    """매물 후보 1건의 점수 계산 입력.

    `price_amount` 는 요청한 거래 유형의 주 금액이다. 월세는 보증금이고 월 차임은
    `monthly_amount` 에 따로 담는다. 두 축을 하나로 접지 않는다.
    """

    listing_id: int
    price_amount: int | None
    monthly_amount: int | None
    pyeong: Decimal | None
    received_at: date | None


# 거래 유형별로 어떤 플래그와 어떤 금액 컬럼을 보는지. 여기 한 곳에만 둔다.
# 매매가가 있다고 전세 손님의 후보가 되면 안 되므로 유형을 섞어 coalesce 하지 않는다.
_LISTING_TRADE_COLUMNS: dict[str, tuple[Any, Any, Any]] = {
    "SALE": (PropertyListing.is_sale_available, PropertyListing.sale_price, None),
    "JEONSE": (
        PropertyListing.is_jeonse_available,
        PropertyListing.jeonse_deposit_amount,
        None,
    ),
    "MONTHLY_RENT": (
        PropertyListing.is_monthly_rent_available,
        PropertyListing.monthly_rent_deposit_amount,
        PropertyListing.monthly_rent_amount,
    ),
}


def list_listing_candidates(
    session: Session,
    brokerage_id: int,
    *,
    price_kind: str | None,
    active_statuses: Sequence[str],
    price_ceiling_amount: int | None,
    complex_ids: Sequence[int],
) -> list[ListingCandidateRow]:
    """구입장 앵커의 반대편 후보. 조건에 맞는 매물만 돌려준다 (F3-SQ-01).

    `price_kind` 는 앵커 구입장의 `demand_type` 과 호환되는 매물 거래 유형이다. 그 유형의
    **거래 가능 플래그가 참인 매물만** 후보이며 금액도 그 유형의 컬럼만 본다. 플래그가
    거짓인 채 남아 있는 과거 금액을 후보 가격으로 쓰지 않는다. 호환되는 유형이 없으면
    후보도 없다.

    F1 매물 조회와 같은 범위를 본다. **부모 세대 삭제 여부까지** 본다. 세대 소프트 삭제는
    딸린 매물 행을 건드리지 않아 매물 행만 보면 화면에 없는 세대의 매물이 후보로 올라온다.

    희망 단지를 지정한 구입장이면 그 단지의 매물만 본다. 지정하지 않았으면 단지를 가리지
    않는다.
    """
    trade = _LISTING_TRADE_COLUMNS.get(price_kind or "")
    if trade is None:
        return []
    available, amount_column, monthly_column = trade

    price = col(amount_column)
    conditions: list[Any] = [
        col(PropertyListing.brokerage_id) == brokerage_id,
        col(PropertyListing.is_deleted).is_(False),
        col(PropertyUnit.is_deleted).is_(False),
        col(available).is_(True),
        col(PropertyListing.status).in_(sorted(active_statuses)),
    ]
    if price_ceiling_amount is not None:
        # 보증금·매매가 축만 비교한다. 구입장에는 월 차임에 대응하는 예산 축이 없다.
        conditions.append(or_(price.is_(None), price <= price_ceiling_amount))
    if complex_ids:
        conditions.append(col(PropertyUnit.complex_id).in_(list(complex_ids)))

    statement = (
        sql_select(
            col(PropertyListing.id),
            price,
            col(monthly_column) if monthly_column is not None else literal(None),
            col(PropertyUnit.pyeong),
            col(PropertyListing.received_at),
        )
        .join(
            PropertyUnit,
            (col(PropertyUnit.brokerage_id) == PropertyListing.brokerage_id)
            & (col(PropertyUnit.id) == PropertyListing.unit_id),
        )
        .where(*conditions)
        .order_by(col(PropertyListing.id).asc())
    )
    # 금액은 위 매핑이 정한 컬럼에서만 읽는다. 조회 조건과 같은 한 곳을 쓴다.
    return [ListingCandidateRow(*row) for row in session.execute(statement).all()]
