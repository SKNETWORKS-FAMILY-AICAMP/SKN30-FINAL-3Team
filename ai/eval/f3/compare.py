"""F3 모델 비교 — 같은 입력을 여러 Provider·모델에 물리고 입력·출력·시간을 나란히 본다.

**왜 있나.** Worker 로 케이스를 돌리면 모델마다 카드가 달라지고, 그 카드가 판정 입력이
되므로 무엇이 모델 차이이고 무엇이 입력 차이인지 섞인다. 여기서는 두 단계를 나눠 각각
**같은 입력**을 준다.

- 카드 단계: 같은 앵커(장부 + 상담 로그)를 모든 대상에 준다.
- 판정 단계: DB 에 저장된 **같은 카드 집합**을 모든 대상에 준다.

vLLM 서버 하나는 모델 하나만 서빙하므로 14B 와 32B 를 동시에 잴 수 없다. 그래서 결과를
파일에 쌓고(`run`) 나중에 한꺼번에 렌더한다(`report`).

    # 14B 를 띄운 상태에서
    uv run --project backend python ai/eval/f3/compare.py run --target vllm:Qwen/Qwen3-14B-AWQ

    # 32B 로 바꿔 띄운 뒤
    uv run --project backend python ai/eval/f3/compare.py run --target vllm:Qwen/Qwen3-32B-AWQ

    # OpenAI 기준선 (요금이 든다)
    uv run --project backend python ai/eval/f3/compare.py run --target openai:gpt-4o-mini

    # 쌓인 결과를 표로
    uv run --project backend python ai/eval/f3/compare.py report

`--case A --case F` 로 케이스를 고를 수 있고, 생략하면 A~I 전부다.

Backend 의 snapshot 조립과 카드 되살리기를 그대로 쓰므로 `--project backend` 로 실행한다.
합성 사무소 데이터만 읽는다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend" / "src"))

from core.config import get_config  # noqa: E402
from domain.agent_execution.judgment import _judgment_card  # noqa: E402
from domain.agent_execution.models import (  # noqa: E402
    AgentRun,
    AnchorType,
    MatchEvaluation,
    NegotiationPositionAnalysis,
)
from domain.agent_execution.snapshot import build_anchor_snapshot  # noqa: E402
from domain.engine import create_database_engine  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from brokerage_ai.core.config import load_ai_config  # noqa: E402
from brokerage_ai.core.types import ModelRoute, ProviderKind  # noqa: E402
from brokerage_ai.f3 import (  # noqa: E402
    EvidenceKind,
    InputPrivacyMode,
    LlmPositionCardGenerator,
)
from brokerage_ai.f3.judgment_contracts import BrokerageJudgmentRequest  # noqa: E402
from brokerage_ai.f3.judgment_generator import LlmBrokerageJudgmentGenerator  # noqa: E402
from brokerage_ai.runtime import create_ai_runtime  # noqa: E402

BROKERAGE = "F3_SYNTHETIC 합성중개사무소"
RESULTS = Path(__file__).resolve().parent / "results" / "compare.jsonl"

# 케이스 → (앵커 종류, seed_key). 자동 증가 ID 는 DB 마다 달라 seed_key 로 찾는다.
CASES: dict[str, tuple[str, str]] = {
    "A": ("LISTING", "L1"),
    "B": ("REQUIREMENT", "R1"),
    "C": ("LISTING", "L5"),
    "D": ("REQUIREMENT", "R8"),
    "E": ("LISTING", "L4"),
    "F": ("LISTING", "BL01"),
    "G": ("REQUIREMENT", "BR01"),
    "H": ("LISTING", "BL13"),
    "I": ("LISTING", "BL23"),
}


@dataclass
class Target:
    provider: ProviderKind
    model: str

    @classmethod
    def parse(cls, raw: str) -> Target:
        provider, _, model = raw.partition(":")
        if not model:
            raise SystemExit(f"--target 형식은 provider:model 이다 (받은 값: {raw!r})")
        return cls(ProviderKind(provider), model)

    @property
    def label(self) -> str:
        return f"{self.provider.value}:{self.model}"


@dataclass
class Outcome:
    """한 (케이스, 단계, 대상) 의 결과. 실패도 기록한다 — 실패가 비교의 절반이다."""

    ok: bool
    seconds: float
    tokens_in: int | None = None
    tokens_out: int | None = None
    error_type: str | None = None
    error: str | None = None
    detail: dict = field(default_factory=dict)

    def row(self) -> dict:
        return {
            "ok": self.ok,
            "seconds": round(self.seconds, 1),
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "tok_per_sec": (
                round(self.tokens_out / self.seconds, 1)
                if self.ok and self.tokens_out and self.seconds > 0
                else None
            ),
            "error_type": self.error_type,
            "error": self.error,
            "detail": self.detail,
        }


def _anchor_id(session: Session, kind: str, seed_key: str) -> int | None:
    from domain.property_ledger.models import PropertyListing, PropertyRequirement  # noqa: PLC0415

    model = PropertyListing if kind == "LISTING" else PropertyRequirement
    rows = session.exec(select(model)).all()
    for row in rows:
        fields = row.custom_fields or {}
        if fields.get("seed_key") == seed_key:
            return row.id
    return None


def _card_summary(analysis) -> dict:
    """사람이 눈으로 비교할 카드 핵심값. 전체 JSON 은 따로 담는다."""
    everything = [
        *analysis.intent.evidence,
        *analysis.urgency.evidence,
        *analysis.timing.evidence,
        *analysis.contactability.evidence,
        *(e for p in analysis.price for e in p.basis),
        *(e for c in analysis.flexible for e in c.evidence),
        *(e for c in analysis.inflexible for e in c.evidence),
    ]
    quotes = sum(1 for e in everything if e.kind is EvidenceKind.QUOTE)
    return {
        "intent": analysis.intent.value.value,
        "urgency": analysis.urgency.value.value,
        "contactability": analysis.contactability.status.value,
        "price": [
            {
                "kind": p.price_kind.value,
                "stated": p.stated_amount,
                "estimated": p.estimated_amount,
            }
            for p in analysis.price
        ],
        "flexible": len(analysis.flexible),
        "inflexible": len(analysis.inflexible),
        "evidence_total": len(everything),
        "evidence_quote": quotes,
        "evidence_inference": len(everything) - quotes,
    }


async def _run_card(runtime, target: Target, request) -> Outcome:
    generator = LlmPositionCardGenerator(
        provider=runtime.providers.get_llm(target.provider),
        route=ModelRoute(provider=target.provider, model=target.model),
        allow_synthetic_prototype=True,
    )
    started = time.perf_counter()
    try:
        result = await generator.generate_position_card(request)
    except Exception as error:  # noqa: BLE001 - 실패 종류가 비교 대상이다
        return Outcome(
            ok=False,
            seconds=time.perf_counter() - started,
            error_type=type(error).__name__,
            error=str(error)[:300],
        )
    elapsed = time.perf_counter() - started
    usage = result.diagnostics.usage if result.diagnostics else None
    return Outcome(
        ok=True,
        seconds=elapsed,
        tokens_in=usage.input_tokens if usage else None,
        tokens_out=usage.output_tokens if usage else None,
        detail={
            "card": _card_summary(result.analysis),
            "card_json": json.loads(result.analysis.model_dump_json()),
        },
    )


async def _run_judgment(runtime, target: Target, anchor, candidates) -> Outcome:
    request = BrokerageJudgmentRequest(
        input_privacy_mode=InputPrivacyMode.SYNTHETIC_PROTOTYPE,
        anchor=anchor,
        candidates=candidates,
    )
    generator = LlmBrokerageJudgmentGenerator(
        provider=runtime.providers.get_llm(target.provider),
        route=ModelRoute(provider=target.provider, model=target.model),
        allow_synthetic_prototype=True,
    )
    started = time.perf_counter()
    try:
        result = await generator.judge_candidates(request)
    except Exception as error:  # noqa: BLE001
        return Outcome(
            ok=False,
            seconds=time.perf_counter() - started,
            error_type=type(error).__name__,
            error=str(error)[:300],
        )
    elapsed = time.perf_counter() - started
    usage = result.diagnostics.usage if result.diagnostics else None

    # Backend 가 저장 전에 하는 인용 대조를 여기서도 한다. 통과 못 하면 실제 실행은 실패한다.
    allowed: dict = {}
    for card in (anchor, *candidates):
        allowed.setdefault(card.negotiation_side, set()).update(card.quoted())
    forged = sum(
        1
        for c in result.candidates
        for item in c.evidence
        if item.source.kind is EvidenceKind.QUOTE
        and (item.source.interaction_id, item.source.quote_text)
        not in allowed.get(item.evidence_side, set())
    )
    return Outcome(
        ok=True,
        seconds=elapsed,
        tokens_in=usage.input_tokens if usage else None,
        tokens_out=usage.output_tokens if usage else None,
        detail={
            "forged_quotes": forged,
            "verdicts": [
                {
                    "card_id": c.card_id,
                    "grade": c.grade.value,
                    "rank": c.rank,
                    "basis": c.comparison_basis[:110],
                    "obstacle": c.primary_obstacle,
                }
                for c in sorted(result.candidates, key=lambda c: c.rank)
            ],
        },
    )


def _load_inputs(case: str) -> dict | None:
    """카드 단계 입력(앵커 snapshot)과 판정 단계 입력(저장된 카드 집합)을 한 번에 읽는다."""
    kind, seed_key = CASES[case]
    engine = create_database_engine(get_config())
    try:
        with Session(engine) as session:
            brokerage_id = get_config().auth.development.brokerage_id
            anchor_id = _anchor_id(session, kind, seed_key)
            if anchor_id is None:
                return None
            snapshot = build_anchor_snapshot(
                session,
                brokerage_id,
                AnchorType(kind),
                anchor_id,
                as_of=datetime.now(UTC),
                input_privacy_mode=InputPrivacyMode.SYNTHETIC_PROTOTYPE,
            )
            # 판정 입력은 이 앵커로 완료된 가장 최근 실행의 카드 집합을 쓴다.
            run = session.exec(
                select(AgentRun).where(AgentRun.status == "COMPLETED").order_by(AgentRun.id.desc())  # pyright: ignore[reportAttributeAccessIssue]
            ).first()
            judgment = None
            if run is not None and "position_analysis_id" in run.redacted_output_snapshot:
                evaluation = session.exec(
                    select(MatchEvaluation).where(MatchEvaluation.agent_run_id == run.id)
                ).first()
                entries = (
                    (evaluation.candidate_selection_snapshot or {}).get("candidate_cards", [])
                    if evaluation
                    else []
                )
                if entries:
                    anchor_card = session.get(
                        NegotiationPositionAnalysis,
                        run.redacted_output_snapshot["position_analysis_id"],
                    )
                    cards = [
                        session.get(NegotiationPositionAnalysis, e["position_analysis_id"])
                        for e in entries
                    ]
                    if anchor_card and all(cards):
                        judgment = (
                            _judgment_card(anchor_card),
                            tuple(_judgment_card(c) for c in cards),
                        )
            return {"request": snapshot.request, "judgment": judgment, "anchor_id": anchor_id}
    finally:
        engine.dispose()


async def command_run(cases: list[str], targets: list[Target]) -> None:
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    config = load_ai_config("local")
    stamp = datetime.now(UTC).isoformat()

    async with create_ai_runtime(config) as runtime:
        for case in cases:
            loaded = _load_inputs(case)
            if loaded is None:
                print(f"[{case}] 앵커를 찾지 못했다. 합성 seed 가 적재되어 있는지 확인한다.")
                continue
            request = loaded["request"]
            logs = request.consultation_logs
            print(f"\n[{case}] 앵커 {loaded['anchor_id']} · 상담 로그 {len(logs)}건")

            for target in targets:
                outcome = await _run_card(runtime, target, request)
                mark = "OK  " if outcome.ok else "FAIL"
                extra = (
                    f"out={outcome.tokens_out}"
                    if outcome.ok
                    else f"{outcome.error_type}: {(outcome.error or '')[:60]}"
                )
                print(f"  카드 {target.label:32s} {mark} {outcome.seconds:6.1f}s  {extra}")
                _append(
                    {
                        "at": stamp,
                        "case": case,
                        "stage": "card",
                        "target": target.label,
                        "input": {
                            "anchor_id": loaded["anchor_id"],
                            "logs": len(logs),
                            "log_excerpts": [log.masked_content[:70] for log in logs[:4]],
                        },
                        **outcome.row(),
                    }
                )

            if loaded["judgment"] is None:
                print("  판정 건너뜀 — 저장된 후보 카드 집합이 없다")
                continue
            anchor_card, candidate_cards = loaded["judgment"]
            for target in targets:
                outcome = await _run_judgment(runtime, target, anchor_card, candidate_cards)
                mark = "OK  " if outcome.ok else "FAIL"
                extra = (
                    f"판정 {len(outcome.detail['verdicts'])}건 · 위조 "
                    f"{outcome.detail['forged_quotes']}"
                    if outcome.ok
                    else f"{outcome.error_type}: {(outcome.error or '')[:60]}"
                )
                print(f"  판정 {target.label:32s} {mark} {outcome.seconds:6.1f}s  {extra}")
                _append(
                    {
                        "at": stamp,
                        "case": case,
                        "stage": "judgment",
                        "target": target.label,
                        "input": {
                            "anchor_card": anchor_card.card_id,
                            "candidates": [c.card_id for c in candidate_cards],
                        },
                        **outcome.row(),
                    }
                )
    print(f"\n결과 누적: {RESULTS}")


def _append(row: dict) -> None:
    with RESULTS.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def command_report(detail_case: str | None) -> None:
    if not RESULTS.exists():
        raise SystemExit(f"결과가 없다. 먼저 run 을 실행한다: {RESULTS}")
    rows = [json.loads(line) for line in RESULTS.read_text(encoding="utf-8").splitlines() if line]
    # 같은 (케이스, 단계, 대상) 이 여러 번 있으면 마지막 것만 본다.
    latest: dict[tuple[str, str, str], dict] = {}
    for row in rows:
        latest[(row["case"], row["stage"], row["target"])] = row

    targets = sorted({key[2] for key in latest})
    cases = sorted({key[0] for key in latest})
    width = max(26, max((len(t) for t in targets), default=26) + 2)

    def cell(row: dict | None) -> str:
        if row is None:
            return "-"
        if not row["ok"]:
            return f"FAIL {row['error_type']}"
        speed = f" {row['tok_per_sec']}t/s" if row["tok_per_sec"] else ""
        return f"OK {row['seconds']}s {row['tokens_out']}tok{speed}"

    for stage, title in (("card", "포지션 카드 생성"), ("judgment", "중개 판정")):
        present = [c for c in cases if any((c, stage, t) in latest for t in targets)]
        if not present:
            continue
        print(f"\n{'=' * (8 + width * len(targets))}")
        print(title)
        print("=" * (8 + width * len(targets)))
        print("케이스  " + "".join(f"{t:<{width}}" for t in targets))
        for case in present:
            print(
                f"{case:<8}"
                + "".join(f"{cell(latest.get((case, stage, t))):<{width}}" for t in targets)
            )

    _print_quality(latest, cases, targets)
    if detail_case:
        _print_detail(latest, detail_case, targets)


def _print_quality(latest: dict, cases: list[str], targets: list[str]) -> None:
    """성공 여부 말고 **무엇을 만들었는지**. 같은 입력이므로 값이 다르면 모델 차이다."""
    print(f"\n{'=' * 78}\n카드 내용 비교 (같은 앵커·같은 로그)\n{'=' * 78}")
    for case in cases:
        available = [(t, latest[(case, "card", t)]) for t in targets if (case, "card", t) in latest]
        if not any(row["ok"] for _, row in available):
            continue
        first = next(row for _, row in available if row["ok"])
        logs = first["input"]["logs"]
        print(f"\n[{case}] 앵커 {first['input']['anchor_id']} · 상담 로그 {logs}건")
        for excerpt in first["input"].get("log_excerpts", []):
            print(f"    입력: {excerpt}")
        for target, row in available:
            if not row["ok"]:
                print(f"    {target:<30} FAIL {row['error_type']}: {(row['error'] or '')[:60]}")
                continue
            card = row["detail"]["card"]
            price = (
                ", ".join(
                    f"{p['kind']} 장부{p['stated']}→추정{p['estimated']}" for p in card["price"]
                )
                or "없음"
            )
            print(
                f"    {target:<30} 의향={card['intent']} 긴급={card['urgency']} "
                f"접촉={card['contactability']}"
            )
            print(f"    {'':<30} 가격: {price}")
            print(
                f"    {'':<30} 근거 {card['evidence_total']}건"
                f"(인용 {card['evidence_quote']}/정황 {card['evidence_inference']}) "
                f"양보 {card['flexible']} 불가 {card['inflexible']}"
            )

    judged = [
        (case, t, latest[(case, "judgment", t)])
        for case in cases
        for t in targets
        if (case, "judgment", t) in latest
    ]
    if not judged:
        return
    print(f"\n{'=' * 78}\n판정 비교 (같은 카드 집합)\n{'=' * 78}")
    for case, target, row in judged:
        if not row["ok"]:
            print(f"[{case}] {target:<30} FAIL {row['error_type']}: {(row['error'] or '')[:70]}")
            continue
        verdicts = ", ".join(
            f"{v['rank']}위 {v['grade']}(#{v['card_id']})" for v in row["detail"]["verdicts"]
        )
        forged = row["detail"]["forged_quotes"]
        flag = "" if forged == 0 else f"  ⚠ 인용위조 {forged}건"
        print(f"[{case}] {target:<30} {verdicts}{flag}")


def _print_detail(latest: dict, case: str, targets: list[str]) -> None:
    """한 케이스의 카드 전문. 문장 표현까지 직접 비교할 때 쓴다."""
    print(f"\n{'=' * 78}\n[{case}] 카드 전문\n{'=' * 78}")
    for target in targets:
        row = latest.get((case, "card", target))
        if row is None or not row["ok"]:
            continue
        print(f"\n--- {target} ---")
        print(json.dumps(row["detail"]["card_json"], ensure_ascii=False, indent=2)[:2500])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    runner = sub.add_parser("run", help="지금 서빙 중인 대상으로 케이스를 돌려 결과를 쌓는다")
    runner.add_argument(
        "--target",
        action="append",
        required=True,
        help="provider:model. 예) vllm:Qwen/Qwen3-14B-AWQ, openai:gpt-4o-mini",
    )
    runner.add_argument("--case", action="append", choices=sorted(CASES), help="기본값 A~I 전부")

    reporter = sub.add_parser("report", help="쌓인 결과를 표로 렌더한다")
    reporter.add_argument("--case", help="이 케이스의 입력·출력 상세를 함께 출력한다")

    args = parser.parse_args()
    if args.command == "run":
        asyncio.run(command_run(args.case or sorted(CASES), [Target.parse(t) for t in args.target]))
    else:
        command_report(args.case)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
