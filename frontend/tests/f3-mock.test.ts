/**
 * F3 mock 시나리오 테스트.
 *
 * mock은 화면을 확인하려고 만든 도구지만, 검증 없이 두면 "화면이 안 나온다"의 원인이 화면인지
 * mock인지 알 수 없게 된다. 여기서는 두 가지를 본다.
 *
 * 1. 단계가 시간에 따라 순서대로 넘어가고, 각 단계가 그 시점까지 저장됐을 만한 것만 내놓는가
 * 2. 지어낸 응답이 **실제 decoder를 통과하는가**. mock이 계약에서 어긋나면 여기서 먼저 깨진다
 */

import assert from "node:assert/strict";
import { test } from "node:test";
import { decodeRunResult, decodeRunStatus } from "../src/features/f3/model/decode.ts";
import {
  CARD_LIMIT,
  TOTAL_CANDIDATES,
  resultPayload,
  statusAt,
  statusPayload,
} from "../src/features/f3/mock/scenario.ts";
import type { MockRun } from "../src/features/f3/mock/scenario.ts";
import { toPanelState } from "../src/features/f3/model/viewModel.ts";

const LISTING_RUN: MockRun = {
  runId: 9001,
  anchorType: "LISTING",
  anchorId: 123,
  createdAt: 0,
};

const PAGE = { limit: 20, offset: 0 };

function resultAt(elapsed: number, page = PAGE) {
  return decodeRunResult(resultPayload(LISTING_RUN, statusAt(elapsed), page));
}

test("단계는 시간 순서대로 넘어간다", () => {
  assert.equal(statusAt(0), "QUEUED");
  assert.equal(statusAt(1_500), "RUNNING");
  assert.equal(statusAt(3_000), "ANCHOR_READY");
  assert.equal(statusAt(5_000), "CANDIDATES_READY");
  assert.equal(statusAt(7_000), "CANDIDATE_CARDS_READY");
  assert.equal(statusAt(9_000), "JUDGING");
  assert.equal(statusAt(11_000), "COMPLETED");
  // 한참 뒤에 열어도 완료에서 멈춘다.
  assert.equal(statusAt(600_000), "COMPLETED");
});

test("상태 응답은 완료 전에 completed_at을 채우지 않는다", () => {
  const judging = decodeRunStatus(statusPayload(LISTING_RUN, statusAt(9_000)));
  assert.equal(judging.status, "JUDGING");
  assert.notEqual(judging.started_at, null);
  assert.equal(judging.completed_at, null);

  const done = decodeRunStatus(statusPayload(LISTING_RUN, statusAt(11_000)));
  assert.notEqual(done.completed_at, null);
});

test("접수 직후에는 카드도 후보도 없다", () => {
  const result = resultAt(0);
  assert.equal(result.anchor_card, null);
  assert.deepEqual(result.candidates, []);
  assert.equal(result.candidates_total, 0);
  // 후보 0건이지만 완료가 아니므로 "후보 없음"으로 그리면 안 된다.
  assert.equal(toPanelState(result.status, result.candidates.length), "queued");
});

test("앵커 카드는 후보보다 먼저 도착한다", () => {
  const result = resultAt(3_000);
  assert.equal(result.status, "ANCHOR_READY");
  assert.notEqual(result.anchor_card, null);
  assert.deepEqual(result.candidates, []);
  // 카드 본문은 구조를 계약하지 않은 객체이므로 통째로 보존한다.
  assert.ok(result.anchor_card != null && "intent" in result.anchor_card.analysis);
});

test("후보는 판정보다 먼저 도착하고 그때는 등급이 없다", () => {
  const result = resultAt(5_000);
  assert.equal(result.status, "CANDIDATES_READY");
  assert.equal(result.candidates_total, TOTAL_CANDIDATES);
  assert.ok(result.candidates.every((candidate) => candidate.match_grade === null));
  // 조회 조건은 후보가 0건이어도 채워진다.
  assert.notEqual(result.candidate_selection.criteria, null);
});

test("완료 결과는 카드화된 후보만 등급을 갖는다", () => {
  const result = resultAt(11_000);
  assert.equal(toPanelState(result.status, result.candidates.length), "ready");

  const graded = result.candidates.filter((candidate) => candidate.match_grade != null);
  const pending = result.candidates.filter((candidate) => candidate.match_grade == null);

  // 첫 페이지는 20건이고 그중 15건이 카드화 대상이다.
  assert.equal(result.candidates.length, 20);
  assert.equal(graded.length, CARD_LIMIT);
  assert.equal(pending.length, 5);
  assert.ok(pending.every((candidate) => candidate.selected_for_cards === false));

  const grades = new Set(graded.map((candidate) => candidate.match_grade));
  assert.deepEqual([...grades].sort(), ["REJECTED", "STRONG", "WEAK"]);
});

test("기각 후보만 기각 사유를 갖고 추천 행동은 갖지 않는다", () => {
  const rejected = resultAt(11_000).candidates.filter(
    (candidate) => candidate.match_grade === "REJECTED",
  );
  assert.ok(rejected.length > 0);
  assert.ok(rejected.every((candidate) => candidate.exclusion_reason != null));
  assert.ok(rejected.every((candidate) => candidate.recommended_action == null));
});

test("페이지는 전체 후보를 자르고 순서를 유지한다", () => {
  const first = resultAt(11_000, { limit: 20, offset: 0 });
  const second = resultAt(11_000, { limit: 20, offset: 20 });

  assert.equal(first.candidates_total, TOTAL_CANDIDATES);
  assert.equal(second.candidates.length, TOTAL_CANDIDATES - 20);
  assert.equal(second.offset, 20);

  // 두 페이지가 겹치지 않는다. rank로 다시 정렬하지 않고 배열 순서를 그대로 쓴다.
  const ids = [...first.candidates, ...second.candidates].map((candidate) => candidate.candidate_id);
  assert.equal(new Set(ids).size, TOTAL_CANDIDATES);
  assert.deepEqual(ids, [...ids].sort((a, b) => a - b));
});

test("판정된 후보만 피드백 대상을 갖는다", () => {
  const done = resultAt(12_000);
  const judged = done.candidates.filter((candidate) => candidate.match_grade != null);
  const pending = done.candidates.filter((candidate) => candidate.match_grade == null);

  // 판정 행이 있어야 관심없음을 보낼 수 있다. 서버와 같은 규칙이다.
  assert.ok(judged.length > 0);
  assert.ok(judged.every((candidate) => candidate.judgment_id != null));
  assert.ok(pending.length > 0);
  assert.ok(pending.every((candidate) => candidate.judgment_id === null));
});

test("mock 후보는 계약에 없는 표시 필드를 만들지 않는다", () => {
  const [candidate] = resultAt(12_000).candidates;
  assert.ok(candidate != null);
  // decoder가 통과시킨 뒤에도 이름·연락처·희망 단지가 후보에 없다. 표시 이름은 화면이 자기
  // 사무소의 F1 장부에서 찾는다.
  assert.deepEqual(
    Object.keys(candidate).filter((key) => /name|phone|contact|complex|title/i.test(key)),
    [],
  );
});
