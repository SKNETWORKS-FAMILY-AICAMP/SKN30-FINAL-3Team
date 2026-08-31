import assert from "node:assert/strict";
import { test } from "node:test";
import { describeF2Error } from "../src/features/f2/api/errors.ts";
import { apiErrorFromResponse, kindFromStatus } from "../src/shared/api/errors.ts";

const CASES = [
  {
    status: 401,
    code: "UNAUTHENTICATED",
    kind: "unauthorized",
    expected: /로그인 세션이 만료되었습니다/,
  },
  {
    status: 422,
    code: "VALIDATION_FAILED",
    kind: "validation",
    expected: /음성 파일과 입력 조건을 확인/,
  },
  {
    status: 502,
    code: "F2_PROCESSING_FAILED",
    kind: "server",
    expected: /음성메모를 처리하지 못했습니다/,
  },
  {
    status: 503,
    code: "F2_UNAVAILABLE",
    kind: "server",
    expected: /음성 분석 서비스를 현재 사용할 수 없습니다/,
  },
] as const;

for (const item of CASES) {
  test(`F2 ${item.status}는 공통 envelope를 보존하고 안전한 기능 문구를 표시한다`, async () => {
    const response = new Response(
      JSON.stringify({
        code: item.code,
        message: "서버 원문: 노출하면 안 되는 Provider 상세",
        request_id: `req-${item.status}`,
      }),
      { status: item.status, headers: { "Content-Type": "application/json" } },
    );

    const error = await apiErrorFromResponse(response);
    assert.equal(error.kind, item.kind);
    assert.equal(error.status, item.status);
    assert.equal(error.code, item.code);
    assert.equal(error.requestId, `req-${item.status}`);

    const message = describeF2Error(error);
    assert.match(message, item.expected);
    assert.match(message, new RegExp(`요청 번호 req-${item.status}`));
    assert.doesNotMatch(message, /서버 원문|Provider 상세/);
  });
}

test("계약에 없는 4xx는 서버 오류가 아니라 계약 오류로 분류한다", () => {
  assert.equal(kindFromStatus(418), "contract");
  assert.equal(kindFromStatus(429), "contract");

  // 현재 계약에 있는 상태의 기존 분류는 유지한다.
  assert.equal(kindFromStatus(400), "validation");
  assert.equal(kindFromStatus(403), "forbidden");
  assert.equal(kindFromStatus(404), "notFound");
  assert.equal(kindFromStatus(409), "conflict");
  assert.equal(kindFromStatus(422), "validation");
  assert.equal(kindFromStatus(500), "server");
});

test("ApiError가 아닌 예외도 원문 없이 복구 문구로 바꾼다", () => {
  const message = describeF2Error(new Error("secret provider failure"));

  assert.match(message, /음성메모 분석을 완료하지 못했습니다/);
  assert.doesNotMatch(message, /secret provider failure/);
});
