import assert from "node:assert/strict";
import path from "node:path";
import { after, afterEach, before, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const originalFetch = globalThis.fetch;

let vite;
let analyzeVoiceMemo;
let setCsrfToken;
let ApiError;
let describeF2Error;

before(async () => {
  vite = await createServer({
    configFile: false,
    root: frontendRoot,
    logLevel: "silent",
    server: { middlewareMode: true, hmr: false },
  });

  ({ analyzeVoiceMemo } = await vite.ssrLoadModule("/src/features/f2/api/f2Api.ts"));
  ({ setCsrfToken } = await vite.ssrLoadModule("/src/shared/api/session.ts"));
  ({ ApiError } = await vite.ssrLoadModule("/src/shared/api/errors.ts"));
  ({ describeF2Error } = await vite.ssrLoadModule("/src/features/f2/api/errors.ts"));
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  setCsrfToken(null);
});

after(async () => {
  await vite?.close();
});

test("F2 multipart fetch 실패도 공통 ApiError와 안전한 화면 문구로 이어진다", async () => {
  setCsrfToken("csrf-for-test");
  let request;
  globalThis.fetch = async (url, init) => {
    request = { url, init };
    return new Response(
      JSON.stringify({
        code: "F2_UNAVAILABLE",
        message: "private provider endpoint and response",
        request_id: "123e4567-e89b-12d3-a456-426614174000",
      }),
      { status: 503, headers: { "Content-Type": "application/json" } },
    );
  };

  let caught;
  try {
    await analyzeVoiceMemo({
      audio: new File(["synthetic-audio"], "memo.wav", { type: "audio/wav" }),
      ledgerType: "property",
      draft: {},
    });
  } catch (error) {
    caught = error;
  }

  assert.ok(caught instanceof ApiError);
  assert.equal(caught.status, 503);
  assert.equal(caught.code, "F2_UNAVAILABLE");
  assert.equal(caught.requestId, "123e4567-e89b-12d3-a456-426614174000");
  assert.equal(request.url, "/api/v1/f2/analyses");
  assert.equal(request.init.method, "POST");
  assert.ok(request.init.body instanceof FormData);

  const shown = describeF2Error(caught);
  assert.match(shown, /음성 분석 서비스를 현재 사용할 수 없습니다/);
  assert.match(shown, /요청 번호 123e4567-e89b-12d3-a456-426614174000/);
  assert.doesNotMatch(shown, /private provider endpoint|response/);
});
