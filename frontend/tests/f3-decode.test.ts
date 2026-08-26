/**
 * F3 공개 계약 decoder 테스트.
 *
 * 서버가 계약대로 보내는지가 아니라, **계약과 다른 응답이 왔을 때 화면이 그것을 정상으로
 * 그리지 않는지**를 확인한다. 배포 불일치를 조용히 삼키면 빈 판정이 사실처럼 보인다.
 *
 * 동시에 서버가 열어둔 값(`status`, `failure_code`)을 좁히지 않는지도 확인한다. 여기서
 * 열거형으로 막으면 Backend가 상태를 하나 추가할 때 화면 전체가 계약 오류로 죽는다.
 */

import assert from "node:assert/strict";
import { test } from "node:test";
import { DecodeError } from "../src/shared/decode/index.ts";
import {
  decodeCandidate,
  decodeFeedback,
  decodeRun,
  decodeRunResult,
} from "../src/features/f3/model/decode.ts";
import { isTerminal, toGradeLabel, toPanelState } from "../src/features/f3/model/viewModel.ts";

function runResponse(overrides: Record<string, unknown> = {}) {
  return {
    run_id: 51,
    run_group_id: "018f7c9e-0f2f-7c1e-9a3b-2f7c9e0f2f7c",
    status: "QUEUED",
    anchor_type: "LISTING",
    anchor_id: 123,
    input_data_version: 3,
    created_at: "2026-08-19T02:13:44.512834+00:00",
    ...overrides,
  };
}

function candidateResponse(overrides: Record<string, unknown> = {}) {
  return {
    candidate_id: 81,
    rank: 1,
    selected_for_cards: true,
    sql_score: "0.8421",
    price_amount: 2880000000,
    monthly_amount: null,
    received_at: "2026-08-01",
    match_grade: "STRONG",
    evaluation_basis: "예산과 희망 평형이 모두 맞는다",
    primary_obstacle: null,
    possible_concession: null,
    recommended_action: { channel: "CALL", message: "먼저 연락해 조건을 확인한다" },
    exclusion_reason: null,
    evidence: [],
    ...overrides,
  };
}

function resultResponse(overrides: Record<string, unknown> = {}) {
  return {
    ...runResponse({ status: "COMPLETED" }),
    started_at: "2026-08-19T02:13:45+00:00",
    completed_at: "2026-08-19T02:14:10+00:00",
    failure_code: null,
    failure_message: null,
    anchor_card: null,
    candidate_selection: {
      criteria: { price_ceiling_amount: 3000000000, demand_types: ["SALE"] },
      total_count: 2,
      carded_count: 2,
      remaining_count: 0,
    },
    candidates: [candidateResponse(), candidateResponse({ candidate_id: 82, rank: 2 })],
    candidates_total: 2,
    limit: 20,
    offset: 0,
    ...overrides,
  };
}

test("실행 접수 응답을 읽는다", () => {
  const run = decodeRun(runResponse());
  assert.equal(run.run_id, 51);
  assert.equal(run.anchor_type, "LISTING");
  assert.equal(run.input_data_version, 3);
});

test("계약에 없는 앵커 종류는 거절한다", () => {
  assert.throws(() => decodeRun(runResponse({ anchor_type: "PARTY" })), DecodeError);
});

test("필수 식별자가 없으면 정상 응답으로 읽지 않는다", () => {
  assert.throws(() => decodeRun(runResponse({ run_id: null })), DecodeError);
  assert.throws(() => decodeCandidate(candidateResponse({ candidate_id: "81" })), DecodeError);
});

test("서버가 열어둔 status는 좁히지 않는다", () => {
  // Backend가 상태를 추가해도 화면이 계약 오류로 죽지 않아야 한다.
  const run = decodeRun(runResponse({ status: "FAILED_RETRYABLE" }));
  assert.equal(run.status, "FAILED_RETRYABLE");
  // 모르는 상태는 실패가 아니라 진행 중으로 다룬다.
  assert.equal(toPanelState("FAILED_RETRYABLE", 0), "running");
  assert.equal(isTerminal("FAILED_RETRYABLE"), false);
});

test("판정 전 후보는 등급이 비어 있고 판정 실패가 아니다", () => {
  const candidate = decodeCandidate(
    candidateResponse({ selected_for_cards: false, match_grade: null, evaluation_basis: null }),
  );
  assert.equal(candidate.selected_for_cards, false);
  assert.equal(candidate.match_grade, null);
  assert.equal(toGradeLabel(null), null);
});

test("등급은 계약값만 화면 표기로 옮긴다", () => {
  assert.equal(toGradeLabel("STRONG"), "강함");
  assert.equal(toGradeLabel("WEAK"), "약함");
  assert.equal(toGradeLabel("REJECTED"), "기각");
  // 같은 뜻의 동의어는 계약값이 아니다.
  assert.equal(toGradeLabel("HIGH"), null);
  assert.equal(toGradeLabel("EXCLUDED"), null);
});

test("진행 중 실행은 빈 카드·후보로 온다", () => {
  const result = decodeRunResult(
    resultResponse({ status: "QUEUED", candidates: [], candidates_total: 0 }),
  );
  assert.equal(result.anchor_card, null);
  assert.deepEqual(result.candidates, []);
  assert.equal(toPanelState(result.status, result.candidates.length), "queued");
});

test("후보 0건 완료는 실패가 아니라 빈 결과다", () => {
  const result = decodeRunResult(
    resultResponse({ candidates: [], candidates_total: 0 }),
  );
  assert.equal(toPanelState(result.status, result.candidates.length), "empty");
  // 왜 비었는지 설명할 조회 조건은 남아 있어야 한다.
  assert.notEqual(result.candidate_selection.criteria, null);
});

test("후보 순서는 응답 배열 순서를 그대로 유지한다", () => {
  // 서버는 판정된 후보에 판정 순위를, 판정 전 후보에 SQL 순위를 담고 페이지는 SQL 순서로
  // 자른다. 화면이 rank로 다시 정렬하면 페이지 경계와 어긋난다.
  const result = decodeRunResult(
    resultResponse({
      candidates: [
        candidateResponse({ candidate_id: 91, rank: 5 }),
        candidateResponse({ candidate_id: 92, rank: 2 }),
      ],
    }),
  );
  assert.deepEqual(
    result.candidates.map((candidate) => candidate.candidate_id),
    [91, 92],
  );
});

test("피드백 응답은 계약 어휘만 받는다", () => {
  const feedback = decodeFeedback({
    feedback_id: 12,
    target: "MATCH_CANDIDATE",
    target_id: 81,
    feedback_type: "NOT_INTERESTED",
    reason: "WRONG_JUDGMENT",
    field_name: "match_grade",
    created_at: "2026-08-24T12:00:00+09:00",
  });
  assert.equal(feedback.feedback_type, "NOT_INTERESTED");
  assert.equal(feedback.reason, "WRONG_JUDGMENT");

  assert.throws(
    () =>
      decodeFeedback({
        feedback_id: 12,
        target: "MATCH_CANDIDATE",
        target_id: 81,
        feedback_type: "NOT_INTERESTED",
        reason: "심심해서",
        field_name: null,
        created_at: null,
      }),
    DecodeError,
  );
});

test("종료 상태는 진행 중과 구분한다", () => {
  // polling을 멈출 기준이다. 여기서 빠지면 끝난 실행을 영원히 다시 조회한다.
  for (const status of ["COMPLETED", "FAILED_TERMINAL", "SUPERSEDED", "CANCELLED"]) {
    assert.equal(isTerminal(status), true, status);
  }
  for (const status of ["QUEUED", "RUNNING", "ANCHOR_READY", "JUDGING"]) {
    assert.equal(isTerminal(status), false, status);
  }
});

test("영구 실패는 서버가 준 공개 문구를 그대로 싣는다", () => {
  const result = decodeRunResult(
    resultResponse({
      status: "FAILED_TERMINAL",
      completed_at: null,
      failure_code: "LEASE_EXPIRED_MAX_ATTEMPTS",
      failure_message: "실행이 최대 시도 횟수를 초과해 종료되었습니다",
      candidates: [],
      candidates_total: 0,
    }),
  );

  assert.equal(toPanelState(result.status, result.candidates_total), "failed");
  // 화면이 문구를 새로 짓지 않는다. 서버가 allowlist로 만든 값만 보여준다.
  assert.equal(result.failure_message, "실행이 최대 시도 횟수를 초과해 종료되었습니다");
  assert.equal(result.failure_code, "LEASE_EXPIRED_MAX_ATTEMPTS");
});

test("입력이 바뀐 실행은 실패가 아니라 교체로 다룬다", () => {
  // 후보가 이미 있어도 결과를 반영하지 않았다는 뜻이므로 완료로 그리면 안 된다.
  const result = decodeRunResult(
    resultResponse({
      status: "SUPERSEDED",
      failure_code: "INPUT_SUPERSEDED",
      failure_message: "실행 중 입력 데이터가 변경되어 결과를 반영하지 않았습니다",
    }),
  );

  assert.equal(result.candidates_total, 2);
  assert.equal(toPanelState(result.status, result.candidates_total), "superseded");
});

test("실패 코드가 없으면 실패 문구도 없다", () => {
  const result = decodeRunResult(resultResponse());
  assert.equal(result.failure_code, null);
  assert.equal(result.failure_message, null);
});
