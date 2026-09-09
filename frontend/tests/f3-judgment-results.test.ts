import assert from "node:assert/strict";
import { test } from "node:test";
import { DecodeError } from "../src/shared/decode/index.ts";
import {
  decodeDetail,
  decodeTarget,
  gradeLabel,
} from "../src/features/f3/judgments/model.ts";
import { readJudgmentLocation } from "../src/features/f3/judgments/navigation.ts";
const target = {
  anchor: {
    anchor_type: "LISTING",
    anchor_id: 7,
    property_unit_id: 3,
    display_name: "합성 매물",
    assignee_id: null,
    assignee_name: null,
    trade_type: null,
    complex_name: null,
    current_conditions: null,
  },
  result_id: null,
  run_id: null,
  eligibility: "ELIGIBLE",
  eligibility_reason: null,
  content_availability: "AVAILABLE",
  freshness: "NONE",
  generation: "QUEUED",
  generated_at: null,
  meaningful_changed_at: null,
  summary: null,
  representative_candidates: [],
};
test("미생성 대상은 판정 건수를 0으로 가장하지 않는다", () => {
  const result = decodeTarget(target);
  assert.equal(result.summary, null);
  assert.equal(result.anchor.property_unit_id, 3);
  assert.equal(result.anchor.anchor_id, 7);
});
test("완료 결과의 현재성·생성 상태는 독립이며 비공개 건수 null을 보존한다", () => {
  const result = decodeDetail({
    ...target,
    result_id: 5,
    freshness: "STALE",
    generation: "FAILED",
    content_availability: "UNAVAILABLE",
    current_result_id: 6,
    candidates: [],
    selected_candidate: null,
    next_cursor: null,
    anchor_card: null,
  });
  assert.equal(result.freshness, "STALE");
  assert.equal(result.generation, "FAILED");
  assert.equal(result.summary, null);
  assert.equal(result.current_result_id, 6);
});
test("불완전한 응답과 범위가 다른 대상 종류를 거절한다", () => {
  assert.throws(
    () =>
      decodeTarget({
        ...target,
        anchor: { ...target.anchor, anchor_type: "PARTY" },
      }),
    DecodeError,
  );
  assert.throws(
    () => decodeTarget({ ...target, summary: { total_count: 18 } }),
    DecodeError,
  );
});
test("미판정은 기각으로 표시하지 않는다", () => {
  assert.equal(gradeLabel(null), "AI 미판정");
  assert.equal(gradeLabel("REJECTED"), "기각");
});
test("복원은 안전한 양의 정수와 지정된 대상 종류만 수용한다", () => {
  assert.deepEqual(
    readJudgmentLocation(
      "?view=f3-judgments&anchor_type=LISTING&anchor_id=7&result_id=8&candidate_id=9",
    ).selection,
    { anchor_type: "LISTING", anchor_id: 7, result_id: 8, candidate_id: 9 },
  );
  for (const id of ["-1", "0", "1.1", "9007199254740992", "name"])
    assert.equal(
      readJudgmentLocation(
        `?view=f3-judgments&anchor_type=LISTING&anchor_id=${id}`,
      ).selection,
      null,
    );
  assert.equal(
    readJudgmentLocation("?view=f3-judgments&anchor_type=PARTY&anchor_id=1")
      .selection,
    null,
  );
});

test("시드 예시 표시는 명시된 boolean만 수용하고 이전 API 누락은 false로 읽는다", () => {
  assert.equal(decodeTarget(target).is_synthetic_fixture, false);
  assert.equal(decodeTarget({ ...target, is_synthetic_fixture: false }).is_synthetic_fixture, false);
  assert.equal(decodeTarget({ ...target, is_synthetic_fixture: true }).is_synthetic_fixture, true);
  for (const invalid of ["true", "false", 1, null]) {
    assert.throws(() => decodeTarget({ ...target, is_synthetic_fixture: invalid }), DecodeError);
  }
});
