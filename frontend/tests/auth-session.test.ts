/**
 * 인증 경계 테스트.
 *
 * 두 가지만 본다.
 *   1. 서버 응답을 화면 모델로 바꾸는 경계가 잘못된 형태를 통과시키지 않는가.
 *   2. 로그인 실패 문구가 계정 존재 여부를 흘리지 않는가.
 *
 * 둘 다 화면 없이 검증할 수 있고, 틀렸을 때 대가가 큰 지점이다.
 */

import assert from "node:assert/strict";
import test from "node:test";

import {
  AuthError,
  describeAuthError,
  isSessionLost,
  kindFromStatus,
} from "../src/features/auth/model/authError.ts";
import { decodeAuthUser, decodeSessionPayload } from "../src/features/auth/model/user.ts";

const VALID_USER = {
  id: 7,
  brokerage_id: 3,
  login_id: "agent01",
  display_name: "김담당",
  role: "STAFF",
};

test("세션 응답을 화면 모델로 옮긴다", () => {
  const payload = decodeSessionPayload({ user: VALID_USER, csrf_token: "token-abc" });

  assert.deepEqual(payload.user, {
    id: 7,
    brokerageId: 3,
    loginId: "agent01",
    displayName: "김담당",
    role: "STAFF",
  });
  assert.equal(payload.csrfToken, "token-abc");
});

test("모르는 역할은 가장 낮은 권한으로 떨어뜨린다", () => {
  // 서버가 역할을 추가했을 때 화면이 로그인 자체를 막으면 배포 순서만으로 사용자가 잠긴다.
  // 통과시키되 권한은 올려주지 않는다.
  const user = decodeAuthUser({ ...VALID_USER, role: "SUPER_ADMIN" });
  assert.equal(user.role, "READ_ONLY");
});

test("필드가 빠지거나 형이 다르면 계약 오류로 막는다", () => {
  const cases: unknown[] = [
    null,
    "문자열",
    [VALID_USER],
    { ...VALID_USER, id: "7" },
    { ...VALID_USER, id: 1.5 },
    { ...VALID_USER, display_name: "" },
    (() => {
      const { login_id: _omitted, ...rest } = VALID_USER;
      return rest;
    })(),
  ];

  for (const value of cases) {
    assert.throws(
      () => decodeAuthUser(value),
      (error: unknown) => error instanceof AuthError && error.kind === "contract",
      `통과시키면 안 되는 값: ${JSON.stringify(value)}`,
    );
  }
});

test("CSRF 원문이 없는 세션 응답은 거절한다", () => {
  // 토큰 없이 인증됨으로 넘어가면 이후 모든 저장이 403으로 죽는다. 여기서 막는 편이 낫다.
  assert.throws(
    () => decodeSessionPayload({ user: VALID_USER }),
    (error: unknown) => error instanceof AuthError && error.kind === "contract",
  );
});

test("자격증명 거절과 세션 없음은 같은 문구로 답한다", () => {
  // 문구가 갈리면 아이디가 존재하는지 넘겨짚을 단서가 된다.
  const unauthenticated = describeAuthError(
    new AuthError({ kind: "unauthenticated", message: "no active session for agent01" }),
  );
  const rejected = describeAuthError(
    new AuthError({ kind: "rejected", message: "user agent01 is deactivated" }),
  );

  assert.equal(unauthenticated, rejected);
});

test("서버 원문 message를 사용자 문구로 내보내지 않는다", () => {
  const shown = describeAuthError(
    new AuthError({ kind: "unauthenticated", message: "login_id=agent01 password mismatch" }),
  );

  assert.ok(!shown.includes("agent01"));
  assert.ok(!shown.includes("password"));
});

test("추적용 request_id는 문구에 덧붙인다", () => {
  const shown = describeAuthError(
    new AuthError({ kind: "server", message: "boom", requestId: "req-42" }),
  );

  assert.ok(shown.includes("req-42"));
});

test("AuthError가 아닌 값도 문구를 준다", () => {
  assert.ok(describeAuthError(new TypeError("undefined is not a function")).length > 0);
  assert.ok(describeAuthError(undefined).length > 0);
});

test("상태 코드를 오류 종류로 나눈다", () => {
  assert.equal(kindFromStatus(401), "unauthenticated");
  assert.equal(kindFromStatus(403), "rejected");
  // 개발 세션 경로는 설정된 local·dev에만 등록된다. 다른 환경의 404는 "없는 로그인 방식"이다.
  assert.equal(kindFromStatus(404), "unavailable");
  assert.equal(kindFromStatus(422), "rejected");
  assert.equal(kindFromStatus(500), "server");
  assert.equal(kindFromStatus(503), "server");
});

test("세션이 끊긴 오류만 재잠금 신호로 본다", () => {
  // 게이트를 다시 세우는 판단 기준이다. 권한 부족이나 서버 오류로 사용자를 튕기면 안 된다.
  assert.equal(isSessionLost(new AuthError({ kind: "unauthenticated", message: "" })), true);
  assert.equal(isSessionLost(new AuthError({ kind: "rejected", message: "" })), false);
  assert.equal(isSessionLost(new AuthError({ kind: "server", message: "" })), false);
  assert.equal(isSessionLost(new Error("boom")), false);
});
