"""등급 산출 — 코드가 한다. LLM 은 카드 값을 채울 뿐이다.

같은 입력에 항상 같은 등급이 나와야 재현성(F3-NF-08)을 검증할 수 있으므로 이 모듈에는
모델 호출도 난수도 현재 시각 조회도 없다. 규칙은 `F3_판정규칙` 1부의 하드 게이트 5종과
5축 가중 점수이고, 상수는 `06_프로토타입_F3플로우/grading.py` 에서 검증된 값 그대로다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

PRICE_GATE = 0.15
"""앵커 상한 대비 이 비율을 넘는 후보는 하드 게이트 G5 로 기각한다."""

PRICE_BANDS: tuple[tuple[float, int], ...] = ((0.00, 40), (0.03, 32), (0.07, 22), (0.15, 10))
TIMING_BANDS: tuple[tuple[int, int], ...] = ((60, 25), (30, 18), (0, 10))

CUT_STRONG = 75
CUT_MID = 50
UNKNOWN_PENALTY = 0.70
UNKNOWN_FLAG = 0.50

WEIGHTS = {"price": 40, "timing": 25, "cond": 15, "intent": 12, "contact": 8}
GRADE_ORDER = ("약함", "중간", "강함")
CONTACT_RANK = {"양호": 0, "주의": 1, "불가": 2}


@dataclass(frozen=True)
class AnchorFacts:
    """앵커(요청을 건 쪽)의 판정 입력. 카드 값 + 장부에서 코드가 뽑은 값."""

    deal_type: str | None = None
    budget_est: float | None = None
    deadline: date | None = None
    intent: str | None = None
    intent_ref: str | None = None
    contact: str | None = None
    hold: tuple[str, ...] = ()


@dataclass(frozen=True)
class CandidateFacts:
    """후보 1건의 판정 입력."""

    id: str
    label: str = ""
    deal_type: str | None = None
    deal_type_ref: str | None = None
    price_est: float | None = None
    concession: float = 0.0
    available_from: date | None = None
    available_note: str | None = None
    intent: str | None = None
    intent_ref: str | None = None
    contact: str | None = None
    contact_route: str | None = None
    cond_total: int = 0
    cond_met: int = 0
    cond_unknown: int = 0
    violates: tuple[str, ...] = ()
    hold: tuple[str, ...] = ()


@dataclass(frozen=True)
class AxisScore:
    points: float
    note: str


@dataclass(frozen=True)
class GradeResult:
    grade: str
    score: float | None
    hard: tuple[str, ...] = ()
    hold: tuple[str, ...] = ()
    axes: dict[str, AxisScore] = field(default_factory=dict)
    flags: tuple[str, ...] = ()

    @property
    def is_rejected(self) -> bool:
        return self.grade == "기각"


def _hard_gates(anchor: AnchorFacts, candidate: CandidateFacts) -> list[str]:
    """G1~G3. 가격(G5)과 시점(G4)은 각 축을 계산하면서 붙는다."""
    hard: list[str] = []
    if candidate.deal_type and anchor.deal_type and candidate.deal_type != anchor.deal_type:
        detail = f" · {candidate.deal_type_ref}" if candidate.deal_type_ref else ""
        hard.append(
            f"G1 거래 유형 불일치 — 앵커 {anchor.deal_type} / 후보 {candidate.deal_type}{detail}"
        )
    for side_label, intent, ref in (
        ("앵커", anchor.intent, anchor.intent_ref),
        ("후보", candidate.intent, candidate.intent_ref),
    ):
        if intent == "철회":
            hard.append(f"G2 {side_label} 의향 철회" + (f" — {ref}" if ref else ""))
    hard.extend(f"G3 필수 조건 위반 — {violation}" for violation in candidate.violates)
    return hard


def _price_axis(
    anchor: AnchorFacts, candidate: CandidateFacts, hard: list[str]
) -> tuple[AxisScore, float]:
    cap, price = anchor.budget_est, candidate.price_est
    if cap is None or price is None or cap == 0:
        return AxisScore(WEIGHTS["price"] / 2 * UNKNOWN_PENALTY, "판정 불가 — 추정값 없음"), 1.0

    adjusted = price - candidate.concession
    gap = (adjusted - cap) / cap
    note = f"이격 {gap * 100:+.1f}% (후보 {adjusted:.1f} / 상한 {cap:.1f})"
    if candidate.concession:
        note += f", 양보 {candidate.concession}억 반영"

    if gap > PRICE_GATE:
        hard.append(f"G5 가격 이격 {gap * 100:+.1f}% — 상한 {PRICE_GATE * 100:.0f}% 초과")
        return AxisScore(0, note), 0.0
    points = next(score for threshold, score in PRICE_BANDS if gap <= threshold)
    return AxisScore(points, note), 0.0


def _timing_axis(
    anchor: AnchorFacts, candidate: CandidateFacts, hard: list[str]
) -> tuple[AxisScore, float]:
    deadline, handover = anchor.deadline, candidate.available_from
    if deadline is None or handover is None:
        note = "판정 불가 — 한쪽 기한 불명" + ("" if deadline else " (앵커 시점 자유)")
        return AxisScore(WEIGHTS["timing"] / 2 * UNKNOWN_PENALTY, note), 1.0

    margin = (deadline - handover).days
    if margin < 0:
        hard.append(f"G4 시점 충돌 — 인도 {handover} > 마감 {deadline} ({-margin}일 초과)")
        return AxisScore(0, f"여유 {margin}일"), 0.0
    points = next(score for threshold, score in TIMING_BANDS if margin >= threshold)
    return AxisScore(points, f"여유 {margin}일"), 0.0


def _condition_axis(candidate: CandidateFacts) -> tuple[AxisScore, float]:
    total, met, unknown = candidate.cond_total, candidate.cond_met, candidate.cond_unknown
    if total == 0 or total == unknown:
        return AxisScore(WEIGHTS["cond"] / 2 * UNKNOWN_PENALTY, "판정 불가"), 1.0

    known_ratio = (total - unknown) / total
    points = (
        WEIGHTS["cond"]
        * (met / (total - unknown))
        * (known_ratio + (1 - known_ratio) * UNKNOWN_PENALTY)
    )
    note = f"{met}/{total - unknown} 충족" + (f", {unknown}건 불명" if unknown else "")
    return AxisScore(points, note), (0.5 if unknown else 0.0)


def _intent_axis(anchor: AnchorFacts, candidate: CandidateFacts) -> tuple[AxisScore, float]:
    confirmed = sum(1 for value in (anchor.intent, candidate.intent) if value == "있음")
    points = (2, 6, 12)[confirmed]
    note = f"앵커 {anchor.intent} / 후보 {candidate.intent}"
    return AxisScore(points, note), (0.0 if confirmed == 2 else 1.0)


def _contact_axis(anchor: AnchorFacts, candidate: CandidateFacts) -> AxisScore:
    worst = max(
        CONTACT_RANK.get(anchor.contact or "", 2),
        CONTACT_RANK.get(candidate.contact or "", 2),
    )
    return AxisScore((8, 5, 2)[worst], f"앵커 {anchor.contact} / 후보 {candidate.contact}")


def _demote(grade: str) -> str:
    return GRADE_ORDER[max(0, GRADE_ORDER.index(grade) - 1)]


def grade(anchor: AnchorFacts, candidate: CandidateFacts) -> GradeResult:
    """하드 게이트가 하나라도 걸리면 기각, 아니면 5축 합계로 등급을 낸다."""
    hard = _hard_gates(anchor, candidate)
    axes: dict[str, AxisScore] = {}
    unknown = 0.0

    axes["price"], price_unknown = _price_axis(anchor, candidate, hard)
    axes["timing"], timing_unknown = _timing_axis(anchor, candidate, hard)
    axes["cond"], cond_unknown = _condition_axis(candidate)
    axes["intent"], intent_unknown = _intent_axis(anchor, candidate)
    axes["contact"] = _contact_axis(anchor, candidate)
    unknown = price_unknown + timing_unknown + cond_unknown + intent_unknown

    hold = tuple(candidate.hold) + tuple(anchor.hold)
    if hard:
        return GradeResult(grade="기각", score=None, hard=tuple(hard), hold=hold, axes=axes)

    score = round(sum(axes[name].points for name in WEIGHTS), 1)
    resolved = "강함" if score >= CUT_STRONG else ("중간" if score >= CUT_MID else "약함")

    flags: list[str] = []
    if hold:
        resolved = _demote(resolved)
        flags.append("확인 필요로 1단계 강등")
    if unknown / 4 > UNKNOWN_FLAG:
        resolved = _demote(resolved)
        flags.append("근거 부족으로 1단계 강등")

    return GradeResult(
        grade=resolved,
        score=score,
        hard=(),
        hold=hold,
        axes=axes,
        flags=tuple(flags),
    )
