"""장부 행 → 대리 입력. 여기 있는 값은 전부 코드가 산출한다.

LLM 에게 절대 맡기지 않는 것 세 가지 (F3 제외 범위 「날짜 계산은 코드다」· F3-SQ-05)

  인도 가능일  `available_from`  임대차 상태·만기·인도 희망일에서
  인도 마감일  `hard_deadline`   손님 희망 입주일에서
  보류 게이트  `hold_flags`      화자 구성·공동명의·선행 조건에서

로그 원문 재구성도 코드가 한다. 상담 로그는 화자와 시각이 정규 컬럼으로 쪼개져 저장돼 있어서
(`counterparty_role`·`counterparty_index`·`interaction_at`) 대리에게 넘기기 전에 사구팔구 표기
`[YY-MM-DD HH:MM 구분]인덱스본문` 로 되돌려야 한다.
"""

from __future__ import annotations

from datetime import UTC, date, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from brokerage_ai.f3.contracts import PositionCardInput

from domain.property_ledger.models import (
    ClientInteraction,
    PropertyListing,
    PropertyRequirement,
    PropertyUnit,
    PropertyUnitPartyRelation,
)

KST = ZoneInfo("Asia/Seoul")
WON_PER_EOK = 100_000_000

SETTLEMENT_DAYS = 90
"""자가 거주에 인도 희망일 진술이 없을 때 통상 잔금까지 걸리는 기간."""

VACANT_DAYS = 30
"""공실 세대의 정리 기간."""

TENANCY_LABEL = {
    "SELF_OCCUPIED": "자가",
    "LEASED": "임차",
    "VACANT": "공실",
    "UNKNOWN": "불명",
}

SPEAKER_CATEGORY = {
    "OWNER_SIDE": "주",
    "TENANT": "세",
    "CO_BROKER": "중",
    "BUYER": "손",
    "OTHER": "기",
}

SPEAKER_INDEX = {1: "①", 2: "②", 3: "③", 4: "④", 5: "⑤"}

DEMAND_TO_DEAL = {"BUY": "매매", "SELL": "매매", "JEONSE": "임대", "MONTHLY_RENT": "임대"}

OWNER_STATEMENT_CUTOFF_DAYS = 230
"""이보다 오래된 소유자측 진술만 있으면 응대자 결정권을 확인해야 한다."""


def to_eok(amount: int | None) -> float | None:
    """DB 는 원 단위 정수, 판정 로직은 억 단위 실수로 다룬다."""
    if amount is None:
        return None
    return round(amount / WON_PER_EOK, 4)


def to_float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def unit_label(unit: PropertyUnit) -> str:
    return f"{unit.building_number}동 {unit.unit_number}호"


def listing_deal_type(listing: PropertyListing | None) -> str | None:
    if listing is None:
        return None
    if listing.is_sale_available:
        return "매매"
    if listing.is_jeonse_available or listing.is_monthly_rent_available:
        return "임대"
    return None


def listing_book_amount(listing: PropertyListing | None) -> float | None:
    """장부 표기 금액. 대리는 이 값을 참고만 하고 실제 값은 로그에서 읽는다."""
    if listing is None:
        return None
    if listing.is_sale_available:
        return to_eok(listing.sale_price)
    if listing.is_jeonse_available:
        return to_eok(listing.jeonse_deposit_amount)
    if listing.is_monthly_rent_available:
        return to_eok(listing.monthly_rent_deposit_amount)
    return None


def format_log_line(interaction: ClientInteraction) -> str:
    """`[YY-MM-DD HH:MM 구분]인덱스본문`.

    `interaction_at` 은 timestamptz 이고 시드는 UTC 로 들어 있다. KST 로 되돌리지 않으면
    프롬프트 규칙 3(「최신 진술이 과거를 이긴다」)의 날짜 경계가 어긋난다.
    """
    category = SPEAKER_CATEGORY.get(interaction.counterparty_role or "", "기")
    index = SPEAKER_INDEX.get(interaction.counterparty_index or 0, "")
    moment = interaction.interaction_at
    if moment is None:
        return f"[?? ?? {category}]{index}{interaction.interaction_content}"
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    stamp = moment.astimezone(KST).strftime("%y-%m-%d %H:%M")
    return f"[{stamp} {category}]{index}{interaction.interaction_content}"


def sorted_log_lines(interactions: list[ClientInteraction]) -> tuple[str, ...]:
    """최신이 먼저 오게 정렬한다 — 프로토타입과 같은 순서여야 카드가 대조된다."""
    ordered = sorted(
        interactions,
        key=lambda row: (row.interaction_at is not None, row.interaction_at),
        reverse=True,
    )
    return tuple(format_log_line(row) for row in ordered)


def available_from(unit: PropertyUnit, as_of: date) -> tuple[date | None, str]:
    """인도 가능일과 그 근거. 알 수 없으면 (None, 사유) — 판정 불가로 넘어간다."""
    blocked = unit.custom_fields.get("handover_blocked_reason")
    if blocked:
        return None, f"선행 조건 미확정 — {blocked}"

    if unit.tenancy_status == "LEASED":
        expiry = unit.tenancy_expiry_date
        return expiry, (f"임차 만기 {expiry}" if expiry else "임차 중 · 만기 불명")

    preferred = unit.custom_fields.get("handover_pref_date")
    if isinstance(preferred, str) and preferred:
        return date.fromisoformat(preferred), "소유자 진술 인도 희망일"

    if unit.tenancy_status == "VACANT":
        return as_of + timedelta(days=VACANT_DAYS), f"공실 · 기준일 +{VACANT_DAYS}일"
    if unit.tenancy_status == "SELF_OCCUPIED":
        return as_of + timedelta(days=SETTLEMENT_DAYS), f"자가 거주 · 기준일 +{SETTLEMENT_DAYS}일"
    return None, "임대차 상태 불명"


def hard_deadline(requirement: PropertyRequirement) -> date | None:
    """희망 입주일이 곧 인도 마감일이다. 없으면 시점 자유."""
    return requirement.desired_move_in_date


def hold_flags(
    unit: PropertyUnit,
    relations: list[PropertyUnitPartyRelation],
    interactions: list[ClientInteraction],
    as_of: date,
) -> list[str]:
    """보류 게이트 — 확인이 필요한 미확정 차단 요인.

    로그 문자열을 훑는 게 아니라 관계 구조(`role_index`·`is_co_owner`)에서 뽑는다.
    """
    flags: list[str] = []
    roles = {row.counterparty_role for row in interactions}
    cutoff = as_of - timedelta(days=OWNER_STATEMENT_CUTOFF_DAYS)
    recent_owner = [
        row
        for row in interactions
        if row.counterparty_role == "OWNER_SIDE"
        and row.interaction_at is not None
        and row.interaction_at.astimezone(KST).date() >= cutoff
    ]
    if "TENANT" in roles and not recent_owner:
        flags.append("응대자 결정권 미확인 — 최근 진술이 임차인(세) 발화뿐")

    if any(relation.is_co_owner for relation in relations):
        owner_indexes = {
            row.counterparty_index
            for row in interactions
            if row.counterparty_role == "OWNER_SIDE" and row.counterparty_index
        }
        if len(owner_indexes) >= 2:
            flags.append(
                f"공동명의 — 소유자측 화자 {len(owner_indexes)}명의 진술이 있다. 단독 결정 불가"
            )
        else:
            flags.append("공동명의 — 단독 결정 불가")

    blocked = unit.custom_fields.get("handover_blocked_reason")
    if blocked:
        flags.append(f"선행 조건 — {blocked} (순서가 있는 성사)")
    return flags


def listing_card_input(
    unit: PropertyUnit,
    listing: PropertyListing | None,
    interactions: list[ClientInteraction],
) -> PositionCardInput:
    """매물 대리 입력. 손님 쪽 값은 인자로도 들어오지 않는다 (수용 기준 3)."""
    tenancy = TENANCY_LABEL.get(unit.tenancy_status or "", "불명")
    notes = [note for note in (unit.memo, listing.memo if listing else None) if note]
    notes.append(f"현 임대차 {tenancy}")
    return PositionCardInput(
        side="매물",
        label=unit_label(unit),
        pyeong=to_float(unit.pyeong),
        deal_type_book=listing_deal_type(listing),
        book_amount=listing_book_amount(listing),
        note=" · ".join(notes),
        logs=sorted_log_lines(interactions),
    )


def requirement_card_input(
    requirement: PropertyRequirement,
    party_name: str,
    interactions: list[ClientInteraction],
) -> PositionCardInput:
    """손님 대리 입력. 매물 쪽 값은 인자로도 들어오지 않는다 (수용 기준 3)."""
    pyeongs = requirement.desired_pyeongs or []
    return PositionCardInput(
        side="손님",
        label=party_name,
        pyeong=to_float(pyeongs[0]) if pyeongs else None,
        deal_type_book=DEMAND_TO_DEAL.get(requirement.demand_type, "매매"),
        book_amount=to_eok(requirement.max_budget_amount),
        note=requirement.memo,
        logs=sorted_log_lines(interactions),
    )


def normalize_quote(text: str) -> str:
    """공백만 접는다. 모델이 줄바꿈이나 여백을 다르게 붙여도 같은 문장으로 본다."""
    return " ".join(text.split())


def match_interaction(
    quote: str | None, interactions: list[ClientInteraction]
) -> ClientInteraction | None:
    """카드의 인용문을 원본 상담 로그 행으로 되짚는다.

    `negotiation_position_evidence` 의 `ck_position_evidence_source` 가 QUOTE 근거에
    `interaction_id` 를 요구한다 — 인용문만으로는 추적 사슬이 끊긴다. 되짚지 못하면
    호출부가 INFERENCE 로 낮춰 기록한다.
    """
    if not quote:
        return None
    needle = normalize_quote(quote)
    if not needle:
        return None

    for row in interactions:
        if normalize_quote(format_log_line(row)) == needle:
            return row
    for row in interactions:
        content = normalize_quote(row.interaction_content)
        if content and (content in needle or needle in content):
            return row
    return None
