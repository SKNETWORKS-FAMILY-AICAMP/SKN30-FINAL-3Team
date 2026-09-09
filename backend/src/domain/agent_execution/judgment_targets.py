"""현재 사무소의 최소 장부 표기. 상담 본문·연락처를 목록용으로 읽지 않는다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlmodel import Session

from core.errors import NotFoundError
from domain.agent_execution.models import AnchorType


@dataclass(frozen=True)
class TargetLabel:
    anchor_type: AnchorType
    anchor_id: int
    display_name: str
    property_unit_id: int | None
    assignee_id: int | None
    assignee_name: str | None
    trade_type: str | None
    complex_name: str | None
    current_conditions: str | None
    status: str
    complex_ids: tuple[int, ...]
    trade_types: tuple[str, ...]

    def public(self) -> dict[str, Any]:
        return {
            "anchor_type": self.anchor_type.value,
            "anchor_id": self.anchor_id,
            "display_name": self.display_name,
            "property_unit_id": self.property_unit_id,
            "assignee_id": self.assignee_id,
            "assignee_name": self.assignee_name,
            "trade_type": self.trade_type,
            "complex_name": self.complex_name,
            "current_conditions": self.current_conditions,
        }


def _amount(value: int | None) -> str:
    return "미기재" if value is None else f"{value:,}원"


def load_target_labels(
    session: Session, brokerage_id: int, anchor_type: AnchorType, *, ids: list[int] | None = None
) -> dict[int, TargetLabel]:
    """SQL join 한 번으로 표기·담당자·필터 필드만 읽는다. F1 상세 전수 호출 없음."""
    if anchor_type is AnchorType.LISTING:
        rows = session.execute(
            text("""
            SELECT l.id, l.unit_id, l.assigned_user_id, a.display_name AS assignee_name,
                   l.status, l.is_sale_available, l.sale_price, l.is_jeonse_available,
                   l.jeonse_deposit_amount, l.is_monthly_rent_available,
                   l.monthly_rent_deposit_amount, l.monthly_rent_amount,
                   c.id AS complex_id, c.name AS complex_name,
                   u.building_number, u.unit_number
            FROM property_listing l
            JOIN property_unit u ON (u.brokerage_id,u.id)=(l.brokerage_id,l.unit_id)
            JOIN property_complex c ON (c.brokerage_id,c.id)=(u.brokerage_id,u.complex_id)
            LEFT JOIN app_user a ON (a.brokerage_id,a.id)=(l.brokerage_id,l.assigned_user_id)
            WHERE l.brokerage_id=:b AND NOT l.is_deleted AND NOT u.is_deleted
                  AND NOT c.is_deleted
                  AND (CAST(:ids AS bigint[]) IS NULL OR l.id=ANY(:ids))
        """),
            {"b": brokerage_id, "ids": ids},
        ).mappings()
        labels = {}
        for row in rows:
            trades, conditions = [], []
            if row["is_sale_available"]:
                trades.append("SALE")
                conditions.append(f"매매 {_amount(row['sale_price'])}")
            if row["is_jeonse_available"]:
                trades.append("JEONSE")
                conditions.append(f"전세 {_amount(row['jeonse_deposit_amount'])}")
            if row["is_monthly_rent_available"]:
                trades.append("MONTHLY_RENT")
                conditions.append(
                    f"월세 {_amount(row['monthly_rent_deposit_amount'])} / "
                    f"{_amount(row['monthly_rent_amount'])}"
                )
            label = " ".join(
                str(v)
                for v in (row["complex_name"], row["building_number"], row["unit_number"])
                if v
            )
            labels[row["id"]] = TargetLabel(
                AnchorType.LISTING,
                row["id"],
                label,
                row["unit_id"],
                row["assigned_user_id"],
                row["assignee_name"],
                ",".join(trades) or None,
                row["complex_name"],
                " · ".join(conditions) or None,
                row["status"],
                (row["complex_id"],),
                tuple(trades),
            )
        return labels
    rows = session.execute(
        text("""
        SELECT r.id, r.assigned_user_id, a.display_name AS assignee_name,
               r.status, r.demand_type, r.min_budget_amount, r.max_budget_amount,
               r.desired_move_in_date, p.name AS party_name,
               COALESCE(cx.ids, ARRAY[]::bigint[]) AS complex_ids, cx.names AS complex_name
        FROM property_requirement r
        JOIN party p ON (p.brokerage_id,p.id)=(r.brokerage_id,r.party_id)
        LEFT JOIN app_user a ON (a.brokerage_id,a.id)=(r.brokerage_id,r.assigned_user_id)
        LEFT JOIN LATERAL (
            SELECT array_agg(c.id ORDER BY c.id) AS ids,
                   string_agg(c.name, ', ' ORDER BY c.name) AS names
            FROM property_requirement_complex rc JOIN property_complex c
              ON (c.brokerage_id,c.id)=(rc.brokerage_id,rc.complex_id)
            WHERE rc.brokerage_id=r.brokerage_id AND rc.requirement_id=r.id
                  AND NOT c.is_deleted
        ) cx ON true
        WHERE r.brokerage_id=:b AND NOT r.is_deleted AND NOT p.is_deleted
          AND (CAST(:ids AS bigint[]) IS NULL OR r.id=ANY(:ids))
    """),
        {"b": brokerage_id, "ids": ids},
    ).mappings()
    labels = {}
    for row in rows:
        trade = {"BUY": "SALE", "매수": "SALE", "전세": "JEONSE", "월세": "MONTHLY_RENT"}.get(
            row["demand_type"], str(row["demand_type"])
        )
        conditions = (
            f"예산 {_amount(row['min_budget_amount'])} ~ {_amount(row['max_budget_amount'])}"
        )
        if row["desired_move_in_date"]:
            conditions += f" · 입주 {row['desired_move_in_date']}"
        labels[row["id"]] = TargetLabel(
            AnchorType.REQUIREMENT,
            row["id"],
            row["party_name"],
            None,
            row["assigned_user_id"],
            row["assignee_name"],
            trade,
            row["complex_name"],
            conditions,
            row["status"],
            tuple(row["complex_ids"]),
            (trade,),
        )
    return labels


def require_label(labels: dict[int, TargetLabel], anchor_id: int) -> TargetLabel:
    label = labels.get(anchor_id)
    if label is None:
        raise NotFoundError("judgment target is not found")
    return label
