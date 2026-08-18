"""후보 추출 — LLM 0회.

수용 기준 1(후보 추출이 LLM 없이 동작한다)과 7(추출 조건에 대리의 추정값이 반영된다)이
이 모듈의 계약이다. 상한은 장부 표기 예산이 아니라 **앵커 카드의 추정값**을 쓴다.
표기와 추정이 갈리는 케이스에서 후보 집합이 달라지는 것이 F3 의 존재 이유다.
"""

from __future__ import annotations

from dataclasses import dataclass

from domain.negotiation.grading import PRICE_GATE

TOP_N = 15
"""중개 판정 한 번에 넘길 후보 상한. 프롬프트 길이와 판정 품질의 절충이다."""

PYEONG_BONUS = 2.0
PYEONG_PENALTY = -5.0


@dataclass(frozen=True)
class CandidateRow:
    """후보 추출이 보는 최소 장부 값. 상담 로그도 카드도 아직 필요 없다."""

    unit_id: int
    label: str
    book_amount: float
    pyeong: float | None


@dataclass(frozen=True)
class DroppedCandidate:
    unit_id: int
    label: str
    book_amount: float
    reason: str


@dataclass(frozen=True)
class CandidateSelection:
    cap: float
    gate: float
    kept: tuple[CandidateRow, ...]
    dropped: tuple[DroppedCandidate, ...]

    @property
    def total(self) -> int:
        return len(self.kept) + len(self.dropped)


def price_gate(cap: float) -> float:
    """상한을 넘겨도 협상 여지가 있는 구간까지는 후보로 본다."""
    return cap * (1 + PRICE_GATE)


def anchor_cap(estimated_price: float | None, book_budget: float | None) -> float | None:
    """앵커 카드의 추정값이 있으면 그것을, 없으면 장부 표기를 상한으로 쓴다."""
    return estimated_price if estimated_price is not None else book_budget


def select_candidates(
    rows: list[CandidateRow],
    *,
    cap: float,
    desired_pyeong: float | None,
    top_n: int = TOP_N,
) -> CandidateSelection:
    """가격 게이트로 자르고 상한 근접도 + 평형 충족으로 정렬해 상위 N 건만 남긴다.

    난수도 모델 호출도 없다 — 같은 입력이면 항상 같은 집합이 나온다.
    """
    gate = price_gate(cap)
    scored: list[tuple[float, int, CandidateRow]] = []
    dropped: list[DroppedCandidate] = []

    for row in rows:
        if row.book_amount > gate:
            dropped.append(
                DroppedCandidate(row.unit_id, row.label, row.book_amount, "가격 게이트 밖")
            )
            continue
        fit = PYEONG_BONUS
        if desired_pyeong is not None:
            fit = PYEONG_BONUS if (row.pyeong or 0) >= desired_pyeong else PYEONG_PENALTY
        scored.append((-abs(row.book_amount - cap) + fit, row.unit_id, row))

    # 동점이면 unit_id 오름차순 — 정렬을 안정적으로 만들어 재현성을 보장한다.
    scored.sort(key=lambda item: (-item[0], item[1]))
    kept = [row for _, _, row in scored[:top_n]]
    dropped.extend(
        DroppedCandidate(row.unit_id, row.label, row.book_amount, f"상위 {top_n}건 컷")
        for _, _, row in scored[top_n:]
    )
    return CandidateSelection(cap=cap, gate=gate, kept=tuple(kept), dropped=tuple(dropped))
