/**
 * F3 피드백 오류 문구 테스트.
 *
 * 문구가 F3 안에 있어야 하는 이유는 ADR-004에 있다. 오류의 분류만 `shared/api`가 공유하고
 * 사용자 문구는 각 기능이 소유한다. 여기서는 그 소유가 실제로 지켜지는지와, 장부와 달라야 하는
 * 두 문구(404·오프라인)가 실제로 다른지를 본다.
 */

import assert from "node:assert/strict";
import { test } from "node:test";
import { describeFeedbackError } from "../src/features/f3/api/errors.ts";
import { ApiError } from "../src/shared/api/errors.ts";

function apiError(kind: ConstructorParameters<typeof ApiError>[0]["kind"], requestId?: string) {
  return new ApiError({ kind, message: "server said so", requestId });
}

test("판정이 사라진 404는 재조회를 안내한다", () => {
  const message = describeFeedbackError(apiError("notFound"));

  assert.match(message, /판정을 더 이상 찾을 수 없습니다/);
  // 판정은 사용자가 지우는 대상이 아니다. 장부의 "다른 사용자가 삭제했을 수 있습니다"를 그대로
  // 쓰면 사실이 아니고, 계약상 다른 사무소 소유일 때도 404다.
  assert.doesNotMatch(message, /삭제/);
});

test("오프라인 문구가 보관을 약속하지 않는다", () => {
  const message = describeFeedbackError(apiError("offline"));

  // 장부는 브라우저에 보관하고 복구 시 재전송한다(F1-GR-35). 피드백에는 그 큐가 없다.
  assert.doesNotMatch(message, /보관/);
});

test("모든 분류가 문구를 가진다", () => {
  const kinds = [
    "offline",
    "canceled",
    "unauthorized",
    "forbidden",
    "notFound",
    "conflict",
    "validation",
    "server",
    "contract",
  ] as const;

  for (const kind of kinds) {
    const message = describeFeedbackError(apiError(kind));
    assert.ok(message.length > 0, `${kind} 문구가 비었다`);
    // 서버 원문을 그대로 노출하지 않는다.
    assert.doesNotMatch(message, /server said so/);
  }
});

test("요청 번호가 있으면 덧붙인다", () => {
  assert.match(describeFeedbackError(apiError("server", "req-77")), /요청 번호 req-77/);
});

test("ApiError가 아닌 값도 문구를 받는다", () => {
  assert.match(describeFeedbackError(new Error("boom")), /알 수 없는 오류/);
  assert.match(describeFeedbackError(undefined), /알 수 없는 오류/);
});
