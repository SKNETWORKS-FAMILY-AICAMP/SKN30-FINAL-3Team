"""Read-only, scoped projections. No client contacts or raw ledger notes go to the AI."""

from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal

from brokerage_ai.chatbot import (
    ChatAction,
    ChatField,
    ChatFilters,
    ChatInput,
    ChatIntent,
    ChatResult,
    ChatResultItem,
)
from sqlalchemy import Engine, false, func, or_, select, text, true
from sqlmodel import Session, col

from domain.chatbot.models import now
from domain.chatbot.normalization import Bounds, ClarificationNeeded, parse_bounds, parse_dates
from domain.property_ledger.models import (
    PropertyComplex,
    PropertyRequirement,
    PropertyRequirementComplex,
    PropertyUnit,
)
from domain.property_ledger.repository import latest_listing_alias
from domain.time_keeper.models import AgendaWindow
from domain.time_keeper.repository import agenda_union

QUERY_TOOLS = ("properties", "buyers", "agenda")
QUERY_TIMEOUT_MS = 5000
TRANSACTIONS = {"SALE": "매매", "JEONSE": "전세", "RENT": "월세"}
# F1 demand_type stores Korean vocabulary (same mapping as candidate selection).
DEMAND_TYPES = {"SALE": "매수", "JEONSE": "전세", "RENT": "월세"}
CATEGORY_LABELS = {
    "TENANCY_EXPIRY": "임대차 만기",
    "CLIENT_TENANCY_EXPIRY": "손님 거주지 만기",
    "REQUEST_EXPIRY": "구입 의뢰 만기",
    "MOVE_IN": "희망 입주",
    "LISTING_REVALIDATION": "매물 조건 재확인",
}
RETIRED_AGENDA_CATEGORIES = frozenset({"LISTING_RECONTACT", "CLIENT_RECONTACT"})


def _ensure_supported_agenda(filters: dict) -> None:
    if filters.get("tool") == "agenda" and RETIRED_AGENDA_CATEGORIES.intersection(
        filters.get("categories", [])
    ):
        raise ClarificationNeeded(
            "재연락 기능은 지원하지 않아요. 일정·만기·매물 재확인을 다시 조회해 주세요."
        )


def _scalar_conditions(column, values: dict) -> list:
    bounds = Bounds(
        **{
            **values,
            "minimum": Decimal(values["minimum"]) if values["minimum"] is not None else None,
            "maximum": Decimal(values["maximum"]) if values["maximum"] is not None else None,
        }
    )
    result = [column.is_not(None)]
    if bounds.minimum is not None:
        result.append(
            column >= bounds.minimum if bounds.minimum_inclusive else column > bounds.minimum
        )
    if bounds.maximum is not None:
        result.append(
            column <= bounds.maximum if bounds.maximum_inclusive else column < bounds.maximum
        )
    return result


def _overlap_conditions(low, high, values: dict) -> list:
    # A missing endpoint is unknown, not infinity. Only a known endpoint can prove
    # overlap when one side is absent; both missing endpoints are always excluded.
    effective_low, effective_high = func.coalesce(low, high), func.coalesce(high, low)
    result = [or_(low.is_not(None), high.is_not(None))]
    if values["minimum"] is not None:
        minimum = Decimal(values["minimum"])
        result.append(
            effective_high >= minimum if values["minimum_inclusive"] else effective_high > minimum
        )
    if values["maximum"] is not None:
        maximum = Decimal(values["maximum"])
        result.append(
            effective_low <= maximum if values["maximum_inclusive"] else effective_low < maximum
        )
    return result


def normalize(intent: ChatIntent, request: ChatInput) -> dict:
    raw = intent.filters.model_dump(mode="json", exclude_none=True)
    if intent.mode == "refine":
        if request.active_filters.get("tool") != intent.tool:
            raise ClarificationNeeded("어떤 검색 결과를 이어서 볼지 먼저 알려 주세요.")
        previous = {
            key: value
            for key, value in request.active_filters.items()
            if key in ChatFilters.model_fields
        }
        # Empty category defaults do not erase the current scope on ordinary refinement.
        previous.update({key: value for key, value in raw.items() if key != "categories" or value})
        raw = previous
    if raw.get("status") in ("진행", "진행 중", "진행중", "접수", "접수 중", "접수중"):
        raw["status"] = "RECEIVED" if intent.tool == "properties" else "ACTIVE"
    filters = ChatFilters.model_validate(raw)
    result = filters.model_dump(mode="json", exclude_none=True)
    result["tool"] = intent.tool
    _ensure_supported_agenda(result)
    if filters.status and filters.status not in ("RECEIVED", "ACTIVE"):
        raise ClarificationNeeded("현재 지원하는 진행 상태로 다시 알려 주세요.")
    if filters.status and (
        (intent.tool == "properties" and filters.status != "RECEIVED")
        or (intent.tool == "buyers" and filters.status != "ACTIVE")
    ):
        raise ClarificationNeeded("매물 접수 또는 구입 의뢰 진행 상태를 알려 주세요.")
    if intent.tool != "agenda" and (filters.date_expression or filters.categories):
        raise ClarificationNeeded("기간 조회는 일정·할 일에서 지원해요.")
    if intent.tool == "agenda":
        if any(
            (
                filters.price_expression,
                filters.deposit_expression,
                filters.rent_expression,
                filters.area_expression,
                filters.complex_name,
                filters.transaction_type,
                filters.status,
            )
        ):
            raise ClarificationNeeded("일정은 기간과 종류로 조회할 수 있어요.")
        start, end = parse_dates(filters.date_expression, request.as_of)
        result.update(start_date=start.isoformat(), end_date=end.isoformat())
    if filters.area_expression:
        if filters.area_basis is None:
            raise ClarificationNeeded("전용면적인지 공급면적인지 알려 주세요.")
        if intent.tool == "buyers":
            raise ClarificationNeeded(
                "구입장 희망 면적의 전용·공급 기준이 저장되어 있지 않아 면적으로 조회할 수 없어요. "
                "거래 유형·예산·단지 조건으로 검색해 주세요."
            )
        result["area_bounds"] = parse_bounds(filters.area_expression, area=True).dump()
    for key in ("price", "deposit", "rent"):
        expression = getattr(filters, f"{key}_expression")
        if expression:
            if key in ("deposit", "rent") and intent.tool == "buyers":
                raise ClarificationNeeded(
                    "구입장에는 월세·보증금 구분 예산이 없어요. 전체 예산으로 조회해 주세요."
                )
            if not filters.transaction_type and intent.tool == "properties":
                raise ClarificationNeeded("매매·전세·월세 중 어느 금액을 조회할지 알려 주세요.")
            if key == "rent" and filters.transaction_type != "RENT":
                raise ClarificationNeeded("월세 금액 조건은 월세 매물에서 지원해요.")
            if key == "deposit" and filters.transaction_type == "SALE":
                raise ClarificationNeeded("매매 매물은 매매 금액으로 조회해 주세요.")
            if (
                key == "price"
                and filters.transaction_type == "RENT"
                and intent.tool == "properties"
            ):
                raise ClarificationNeeded("월세는 보증금과 월 임대료를 구분해 알려 주세요.")
            result[f"{key}_bounds"] = parse_bounds(expression).dump()
    if filters.sort in ("price_asc", "price_desc"):
        if intent.tool == "agenda":
            raise ClarificationNeeded("일정은 날짜순으로 조회할 수 있어요.")
        if intent.tool == "properties" and filters.transaction_type is None:
            raise ClarificationNeeded("금액순으로 정렬할 거래 유형을 알려 주세요.")
    return result


def _format_amount(value) -> str:
    return "미입력" if value is None else f"{int(value):,}원"


def _field(label: str, value) -> ChatField:
    return ChatField(label=label, value="미입력" if value is None else str(value))


def _base_result(kind, filters, items, total, offset):
    label = {"properties": "매물", "buyers": "구입 의뢰", "agenda": "일정·할 일"}[kind]
    description = f"조건에 맞는 {label} {total}건을 찾았어요."
    if kind == "buyers" and filters.get("price_bounds"):
        description += " 저장된 희망 예산 범위와 검색 범위가 겹치는 의뢰예요."
    return ChatResult(
        kind=kind,
        text=description,
        filters=filters,
        items=tuple(items),
        total=total,
        offset=offset,
        as_of=now(),
    )


async def _completed_thread(function, *args):
    """Cancellation retains the request slot until the bounded DB thread really exits."""
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # Task.cancel can be repeated by shutdown/maintenance while the SQL timeout drains.
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if not task.cancelled():
            task.exception()
        raise


class ChatLookup:
    def __init__(self, engine: Engine, brokerage_id: int, *, on_search=None):
        self.engine, self.brokerage_id = engine, brokerage_id
        self.on_search = on_search

    async def execute(self, intent: ChatIntent, request: ChatInput) -> ChatResult:
        # Revalidate even when called by a fake workflow or an alternate trusted model adapter.
        intent = ChatIntent.model_validate(intent.model_dump())
        try:
            if intent.tool == "open_result":
                return await _completed_thread(self._reference, intent, request)
            if intent.tool not in QUERY_TOOLS:
                raise ClarificationNeeded("조회할 매물·구입장·일정을 알려 주세요.")
            filters = normalize(intent, request)
            if self.on_search is not None:
                await self.on_search(filters)
            return await _completed_thread(self.search, filters, 0)
        except ClarificationNeeded as error:
            return ChatResult(
                kind="clarification", text=str(error), filters=request.active_filters, as_of=now()
            )

    def search(self, filters: dict, offset: int = 0) -> ChatResult:
        if not 0 <= offset <= 100000 or filters.get("tool") not in QUERY_TOOLS:
            raise ClarificationNeeded("조회 조건이나 페이지가 올바르지 않아요.")
        # Saved result pages bypass normalize; retired capabilities are not empty results.
        try:
            _ensure_supported_agenda(filters)
        except ClarificationNeeded as error:
            return ChatResult(kind="clarification", text=str(error), filters=filters, as_of=now())
        with Session(self.engine) as session:
            # Count and page share a snapshot during concurrent ledger edits.
            session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            session.execute(
                text("SELECT set_config('statement_timeout', :timeout, true)"),
                {"timeout": f"{QUERY_TIMEOUT_MS}ms"},
            )
            if filters.get("complex_name"):
                name = filters["complex_name"]
                base = select(col(PropertyComplex.id)).where(
                    col(PropertyComplex.brokerage_id) == self.brokerage_id
                )
                exact = (
                    session.execute(
                        base.where(func.lower(col(PropertyComplex.name)) == name.lower()).limit(2)
                    )
                    .scalars()
                    .all()
                )
                matches = (
                    exact
                    or session.execute(
                        base.where(
                            col(PropertyComplex.name).icontains(name, autoescape=True)
                        ).limit(2)
                    )
                    .scalars()
                    .all()
                )
                if len(matches) > 1:
                    raise ClarificationNeeded(
                        "여러 단지가 일치해요. 단지 이름을 더 구체적으로 알려 주세요."
                    )
                # Use only the matched ID; a missing name cannot remove the filter.
                filters = {**filters, "complex_id": matches[0] if matches else -1}
            if filters["tool"] == "properties":
                return self._properties(session, filters, offset)
            if filters["tool"] == "buyers":
                return self._buyers(session, filters, offset)
            return self._agenda(session, filters, offset)

    def _properties(self, session, filters, offset):
        listing = latest_listing_alias()
        query = (
            select(PropertyUnit, PropertyComplex, listing)
            .join(
                PropertyComplex,
                (col(PropertyComplex.brokerage_id) == col(PropertyUnit.brokerage_id))
                & (col(PropertyComplex.id) == col(PropertyUnit.complex_id)),
            )
            .outerjoin(listing, true())
            .where(
                col(PropertyUnit.brokerage_id) == self.brokerage_id,
                col(PropertyUnit.is_deleted) == false(),
            )
        )
        if filters.get("complex_name"):
            query = query.where(col(PropertyComplex.id) == filters["complex_id"])
        if filters.get("status"):
            query = query.where(listing.status == filters["status"])
        transaction = filters.get("transaction_type")
        price = {
            "SALE": listing.sale_price,
            "JEONSE": listing.jeonse_deposit_amount,
            "RENT": listing.monthly_rent_amount,
        }.get(transaction, listing.sale_price)
        available = {
            "SALE": listing.is_sale_available,
            "JEONSE": listing.is_jeonse_available,
            "RENT": listing.is_monthly_rent_available,
        }.get(transaction)
        if available is not None:
            query = query.where(available.is_(True))
        columns = {
            "price": price,
            "deposit": listing.monthly_rent_deposit_amount
            if transaction == "RENT"
            else listing.jeonse_deposit_amount,
            "rent": listing.monthly_rent_amount,
            "area": col(PropertyUnit.exclusive_area_sqm)
            if filters.get("area_basis") == "exclusive"
            else col(PropertyUnit.supply_area_sqm),
        }
        for key, column in columns.items():
            if filters.get(f"{key}_bounds"):
                query = query.where(*_scalar_conditions(column, filters[f"{key}_bounds"]))
        total = session.execute(select(func.count()).select_from(query.subquery())).scalar_one()
        sort = filters.get("sort")
        if sort in ("price_asc", "price_desc"):
            query = query.order_by(
                price.asc().nullslast() if sort == "price_asc" else price.desc().nullslast()
            )
        else:
            query = query.order_by(listing.received_at.desc().nullslast())
        rows = session.execute(
            query.order_by(col(PropertyUnit.id).asc()).limit(10).offset(offset)
        ).all()
        items = []
        for unit, complex_, listing_ in rows:
            fields = [
                _field("전용면적(㎡)", unit.exclusive_area_sqm),
                _field("공급면적(㎡)", unit.supply_area_sqm),
            ]
            if listing_:
                if listing_.is_sale_available:
                    fields.append(_field("매매", _format_amount(listing_.sale_price)))
                if listing_.is_jeonse_available:
                    fields.append(_field("전세", _format_amount(listing_.jeonse_deposit_amount)))
                if listing_.is_monthly_rent_available:
                    fields.extend(
                        [
                            _field("보증금", _format_amount(listing_.monthly_rent_deposit_amount)),
                            _field("월세", _format_amount(listing_.monthly_rent_amount)),
                        ]
                    )
            items.append(
                ChatResultItem(
                    id=str(unit.id),
                    title=complex_.name,
                    subtitle=f"{unit.building_number or ''}동 {unit.unit_number}호",
                    fields=tuple(fields),
                    action=ChatAction(
                        type="open_property", target_id=unit.id, label="매물 상세 보기"
                    ),
                )
            )
        return _base_result("properties", filters, items, total, offset)

    def _buyers(self, session, filters, offset):
        query = select(PropertyRequirement).where(
            col(PropertyRequirement.brokerage_id) == self.brokerage_id,
            col(PropertyRequirement.is_deleted) == false(),
        )
        if filters.get("complex_name"):
            matching = (
                select(col(PropertyRequirementComplex.requirement_id))
                .join(
                    PropertyComplex,
                    (
                        col(PropertyComplex.brokerage_id)
                        == col(PropertyRequirementComplex.brokerage_id)
                    )
                    & (col(PropertyComplex.id) == col(PropertyRequirementComplex.complex_id)),
                )
                .where(
                    col(PropertyRequirementComplex.brokerage_id) == self.brokerage_id,
                    col(PropertyComplex.id) == filters["complex_id"],
                )
            )
            query = query.where(col(PropertyRequirement.id).in_(matching))
        if filters.get("transaction_type"):
            query = query.where(
                col(PropertyRequirement.demand_type) == DEMAND_TYPES[filters["transaction_type"]]
            )
        if filters.get("status"):
            query = query.where(col(PropertyRequirement.status) == filters["status"])
        for key, low, high in (
            (
                "price",
                col(PropertyRequirement.min_budget_amount),
                col(PropertyRequirement.max_budget_amount),
            ),
            ("area", col(PropertyRequirement.min_area_sqm), col(PropertyRequirement.max_area_sqm)),
        ):
            if filters.get(f"{key}_bounds"):
                query = query.where(*_overlap_conditions(low, high, filters[f"{key}_bounds"]))
        total = session.execute(select(func.count()).select_from(query.subquery())).scalar_one()
        sort = filters.get("sort")
        if sort in ("price_asc", "price_desc"):
            price = col(PropertyRequirement.max_budget_amount)
            query = query.order_by(
                price.asc().nullslast() if sort == "price_asc" else price.desc().nullslast()
            )
        else:
            query = query.order_by(col(PropertyRequirement.received_at).desc())
        rows = session.execute(
            query.order_by(col(PropertyRequirement.id).desc()).limit(10).offset(offset)
        ).scalars()
        items = [
            ChatResultItem(
                id=str(row.id),
                title=f"구입 의뢰 #{row.id}",
                subtitle=str(TRANSACTIONS.get(row.demand_type, row.demand_type)),
                fields=(
                    _field("최소 예산", _format_amount(row.min_budget_amount)),
                    _field("최대 예산", _format_amount(row.max_budget_amount)),
                    _field("희망 입주일", row.desired_move_in_date),
                ),
                action=ChatAction(type="open_buyer", target_id=row.id, label="구입장 상세 보기"),
            )
            for row in rows
        ]
        return _base_result("buyers", filters, items, total, offset)

    def _agenda(self, session, filters, offset):
        start, end = (
            date.fromisoformat(filters["start_date"]),
            date.fromisoformat(filters["end_date"]),
        )
        window = AgendaWindow(
            as_of=start,
            earliest=start,
            latest=end,
            revalidation_days=30,
            per_category_limit=100,
        )
        combined = agenda_union(self.brokerage_id, window)
        query = select(combined).where(combined.c.due_date.between(start, end))
        categories = filters.get("categories", [])
        if categories:
            query = query.where(combined.c.category.in_(categories))
        total = session.execute(select(func.count()).select_from(query.subquery())).scalar_one()
        rows = session.execute(
            query.order_by(
                combined.c.due_date,
                combined.c.category,
                combined.c.unit_id.asc().nullslast(),
                combined.c.listing_id.asc().nullslast(),
                combined.c.requirement_id.asc().nullslast(),
            )
            .limit(10)
            .offset(offset)
        ).mappings()
        items = []
        for row in rows:
            if row["unit_id"]:
                action = ChatAction(
                    type="open_property", target_id=row["unit_id"], label="매물 상세 보기"
                )
            else:
                action = ChatAction(
                    type="open_buyer", target_id=row["requirement_id"], label="구입장 상세 보기"
                )
            title = CATEGORY_LABELS.get(row["category"], row["category"])
            items.append(
                ChatResultItem(
                    id=f"{row['category']}:{row['unit_id']}:{row['listing_id']}:{row['requirement_id']}",
                    title=str(title),
                    subtitle=str(row["due_date"]),
                    fields=(_field("종류", CATEGORY_LABELS.get(row["category"], row["category"])),),
                    action=action,
                )
            )
        return _base_result("agenda", filters, items, total, offset)

    def _reference(self, intent, request):
        reference, ordinal = request.reference, intent.reference_ordinal
        if reference is None or ordinal is None or ordinal > len(reference.items):
            raise ClarificationNeeded("최근 검색 결과에서 몇 번째 항목인지 알려 주세요.")
        item = reference.items[ordinal - 1]
        action = item.action
        if reference.kind == "agenda" and action is not None:
            # Stored agenda identifiers preserve their original source category.
            _ensure_supported_agenda({"tool": "agenda", "categories": [item.id.partition(":")[0]]})
        if action is None or action.target_id is None:
            raise ClarificationNeeded("이 결과는 상세 화면을 열 수 없어요.")
        model = {
            "open_property": PropertyUnit,
            "open_buyer": PropertyRequirement,
        }.get(action.type)
        if model is None:
            raise ClarificationNeeded("이 동작은 지원하지 않아요.")
        with Session(self.engine) as session:
            session.execute(
                text("SELECT set_config('statement_timeout', :timeout, true)"),
                {"timeout": f"{QUERY_TIMEOUT_MS}ms"},
            )
            exists = session.execute(
                select(model.id).where(
                    model.id == action.target_id,
                    model.brokerage_id == self.brokerage_id,
                    model.is_deleted == false(),
                )
            ).first()
        if not exists:
            raise ClarificationNeeded("해당 항목이 삭제되었어요. 다시 검색해 주세요.")
        return ChatResult(
            kind="action",
            text=f"{ordinal}번째 항목의 상세 화면을 열 수 있어요.",
            filters=request.active_filters,
            actions=(action,),
            as_of=now(),
        )
