"""Deterministic Korean units, inclusive/exclusive bounds and KST calendar periods."""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation


class ClarificationNeeded(ValueError):
    pass


@dataclass(frozen=True)
class Bounds:
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    minimum_inclusive: bool = True
    maximum_inclusive: bool = True

    def dump(self) -> dict:
        return {
            "minimum": str(self.minimum) if self.minimum is not None else None,
            "maximum": str(self.maximum) if self.maximum is not None else None,
            "minimum_inclusive": self.minimum_inclusive,
            "maximum_inclusive": self.maximum_inclusive,
        }


def _money(value: str) -> Decimal:
    value = value.replace(",", "").replace(" ", "").removesuffix("원")
    if not value:
        raise ClarificationNeeded("금액과 단위를 함께 알려 주세요.")
    if re.fullmatch(r"\d+(?:\.\d+)?", value):
        amount = Decimal(value)
    else:
        tokens = re.findall(r"(\d+(?:\.\d+)?)(억|천만|백만|십만|만|천)", value)
        if "".join(number + unit for number, unit in tokens) != value:
            raise ClarificationNeeded("금액은 5억, 3천만원처럼 알려 주세요.")
        units = {
            "억": 100000000,
            "천만": 10000000,
            "백만": 1000000,
            "십만": 100000,
            "만": 10000,
            "천": 1000,
        }
        amount = sum((Decimal(number) * units[unit] for number, unit in tokens), Decimal(0))
    if amount > 10**15 or amount != amount.to_integral():
        raise ClarificationNeeded("원 단위의 유효한 금액을 알려 주세요.")
    return amount


def _area(value: str) -> Decimal:
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(평|㎡|m2|m²|제곱미터)", value.strip())
    if not match:
        raise ClarificationNeeded("면적과 평 또는 ㎡ 단위를 함께 알려 주세요.")
    amount = Decimal(match[1]) * (Decimal("3.305785") if match[2] == "평" else 1)
    if amount > 100000:
        raise ClarificationNeeded("유효한 면적을 알려 주세요.")
    return amount


def parse_bounds(expression: str, *, area=False) -> Bounds:
    expression = expression.strip()
    converter = _area if area else _money
    combined = re.fullmatch(r"(.+?)\s*(이상|초과)\s+(.+?)\s*(이하|미만)", expression)
    if combined:
        low, high = converter(combined[1]), converter(combined[3])
        if low > high:
            raise ClarificationNeeded("범위의 최솟값이 최댓값보다 커요.")
        return Bounds(low, high, combined[2] == "이상", combined[4] == "이하")
    if "부터" in expression:
        expression = expression.replace("부터", "~").removesuffix("까지").strip()
    elif expression.endswith("까지"):
        expression = expression.removesuffix("까지").strip() + " 이하"
    # Only known grammar is accepted; model-produced SQL or unknown suffixes never become a filter.
    try:
        parts = re.split(r"\s*(?:~|∼)\s*", expression)
        if len(parts) == 2:
            first, second = parts
            if re.fullmatch(r"\d+(?:\.\d+)?", first.strip()):
                unit = re.search(r"(억|천만|백만|십만|만|천|원|평|㎡|m2|m²|제곱미터)\s*$", second)
                if unit:
                    first += unit[1]
            low, high = converter(first), converter(second)
            if low > high:
                raise ClarificationNeeded("범위의 최솟값이 최댓값보다 커요.")
            return Bounds(low, high)
        match = re.fullmatch(r"(.+?)\s*(이하|미만|이상|초과|이내|이하로|이상으로)?", expression)
        if not match:
            raise ClarificationNeeded("범위를 다시 알려 주세요.")
        value, comparison = converter(match[1].strip()), match[2]
        if comparison in ("이하", "이내", "이하로", "미만"):
            return Bounds(maximum=value, maximum_inclusive=comparison != "미만")
        if comparison in ("이상", "이상으로", "초과"):
            return Bounds(minimum=value, minimum_inclusive=comparison != "초과")
        return Bounds(value, value)
    except (InvalidOperation, OverflowError) as error:
        raise ClarificationNeeded("숫자와 단위를 다시 알려 주세요.") from error


def parse_dates(expression: str | None, today: date) -> tuple[date, date]:
    value = (expression or "이번 달").replace(" ", "")
    if value in ("오늘", "금일"):
        return today, today
    if value == "내일":
        return today + timedelta(days=1), today + timedelta(days=1)
    if value in ("이번주", "다음주"):
        start = today - timedelta(days=today.weekday())
        if value == "다음주":
            start += timedelta(days=7)
        return start, start + timedelta(days=6)
    if value in ("이번달", "이번월", "다음달", "다음월"):
        month, year = today.month, today.year
        if value.startswith("다음"):
            month, year = (1, year + 1) if month == 12 else (month + 1, year)
        return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])
    rolling = re.fullmatch(r"(?:앞으로|향후)?(\d+)일(?:이내|간)?", value)
    if rolling and 1 <= int(rolling[1]) <= 730:
        return today, today + timedelta(days=int(rolling[1]) - 1)
    try:
        parts = value.split("~")
        if len(parts) == 1:
            first = last = date.fromisoformat(parts[0])
        elif len(parts) == 2:
            first, last = (date.fromisoformat(part) for part in parts)
        else:
            raise ValueError
        if first > last or (last - first).days > 730:
            raise ValueError
        return first, last
    except ValueError as error:
        raise ClarificationNeeded(
            "오늘, 이번 주 또는 YYYY-MM-DD~YYYY-MM-DD 기간을 알려 주세요."
        ) from error
