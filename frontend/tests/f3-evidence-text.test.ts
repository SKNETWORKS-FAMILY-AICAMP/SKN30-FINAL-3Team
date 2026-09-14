import assert from "node:assert/strict";
import { test } from "node:test";
import { evidenceFieldLabel, judgmentText } from "../src/features/f3/model/evidenceText.ts";
import { toCandidateView } from "../src/features/f3/model/viewModel.ts";
import { EMPTY_LEDGER_INDEX } from "../src/features/f3/model/candidateLabel.ts";
import { decodeCandidate } from "../src/features/f3/model/decode.ts";
import { candidateEntry } from "../src/features/f3/mock/scenario.ts";

test("근거의 일정·가격·조건과 과거 배열 경로를 한국어로 표시한다", () => {
  for (const [key, expected] of [
    ["timing.hard_deadline", "확정 기한"], ["timing.constraints", "일정 조건"],
    ["price.stated_amount", "제시 금액"], ["price[0].stated_monthly_amount", "제시 월세"],
    ["analysis.price.0.estimated_amount", "추정 금액"],
    ["timing.constraints[0].description", "일정 조건"],
    ["flexible", "조율 가능한 조건"], ["inflexible", "조율이 어려운 조건"],
    ["intent.value", "거래 의향"], ["urgency", "긴급도"],
    ["contactability.status", "연락 가능 상태"], ["price.SALE", "매매가"], ["price.BUDGET", "예산"],
  ]) assert.equal(evidenceFieldLabel(key!), expected);
});

test("미지의 영문 항목은 중립 제목으로 표시하고 한국어·빈 항목은 보존한다", () => {
  for (const key of ["future.internal_key", "constructor", "toString", "입주 timing"]) {
    assert.equal(evidenceFieldLabel(key), "판정 근거");
  }
  assert.equal(evidenceFieldLabel("입주 조건"), "입주 조건");
  assert.equal(evidenceFieldLabel(null), null);
  assert.equal(evidenceFieldLabel(" "), null);
});

test("설명 속 알려진 키만 치환하고 날짜·금액·일반 영문·미지의 경로를 보존한다", () => {
  assert.equal(judgmentText("hard_deadline 2027-05-07, price.stated_amount 5천만원·예산 8천만원"),
    "확정 기한 2027-05-07, 제시 금액 5천만원·예산 8천만원");
  assert.equal(judgmentText("`analysis.price[0].stated_amount`와 timing.constraints. hard_deadline은 확인됨"),
    "`제시 금액`와 일정 조건. 확정 기한은 확인됨");
  const untouched = "VIP LH GTX 84A surprise overpriced new.hard_deadline hard_deadline_extra timing.unknown";
  assert.equal(judgmentText(untouched), untouched);
  assert.equal(judgmentText(null), null);
});

test("표시 변환은 설명 전체에 적용하되 응답·상담 인용·판정 식별자를 바꾸지 않는다", () => {
  const dto = decodeCandidate({
    ...candidateEntry({ runId: 1, anchorType: "LISTING", anchorId: 1, createdAt: 0 }, 0, true),
    evaluation_basis: "timing.hard_deadline 2027-05-07로 일치한다.",
    primary_obstacle: "inflexible 확인", possible_concession: "flexible 확인",
    exclusion_reason: "price.stated_amount 확인", recommended_action: { message: "hard_deadline 확인" },
    evidence: [{ field_name: "timing.hard_deadline", evidence_type: "QUOTE", interaction_id: 7,
      quote_text: "고객 원문: hard_deadline, LH, 2027-05-07", quote_start_offset: 0,
      quote_end_offset: 37, note: "hard_deadline 2027-05-07 확인", evidence_side: "ANCHOR" }],
  });
  const original = structuredClone(dto);
  const view = toCandidateView(dto, EMPTY_LEDGER_INDEX, "LISTING");
  assert.equal(view.evaluationBasis, "확정 기한 2027-05-07로 일치한다.");
  assert.equal(view.blocker, "조율이 어려운 조건 확인");
  assert.equal(view.concession, "조율 가능한 조건 확인");
  assert.equal(view.exclusionReason, "제시 금액 확인");
  assert.equal(view.recommendedAction, "확정 기한 확인");
  assert.equal(view.evidence[0]?.fieldName, "확정 기한");
  assert.equal(view.evidence[0]?.note, "확정 기한 2027-05-07 확인");
  assert.equal(view.evidence[0]?.quote, dto.evidence[0]?.quote_text);
  assert.equal(view.evidence[0]?.interactionId, 7);
  assert.equal(view.candidateId, dto.candidate_id);
  assert.equal(view.feedbackTargetId, dto.judgment_id);
  assert.equal(view.rank, dto.rank);
  assert.equal(view.grade, "강함");
  assert.deepEqual(dto, original);
});
