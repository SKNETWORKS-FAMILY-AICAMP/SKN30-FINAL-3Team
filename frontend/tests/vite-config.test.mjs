import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { findForbiddenProfileEnvFiles, parseBackendOrigin } from "../vite.config.mjs";
import { APP_ENV_KEYS } from "../src/config/envSchema.ts";

test("profile-specific env files are forbidden", () => {
  assert.deepEqual(
    findForbiddenProfileEnvFiles([
      ".env",
      ".env.example",
      ".env.local",
      ".env.development",
      ".env.production.local",
      ".env.prod",
    ]),
    [".env.development", ".env.prod", ".env.production.local"],
  );
});

test("the development backend target is an origin, not a bundled VITE value", () => {
  assert.equal(parseBackendOrigin(undefined), "http://127.0.0.1:8000");
  assert.equal(parseBackendOrigin("https://backend.example.com"), "https://backend.example.com");

  for (const value of [
    "ftp://backend.example.com",
    "https://user:secret@backend.example.com",
    "https://backend.example.com/api",
    "https://backend.example.com?debug=true",
  ]) {
    assert.throws(() => parseBackendOrigin(value), /FRONTEND_BACKEND_ORIGIN/, value);
  }
});

/**
 * 브라우저로 내보낼 설정은 명시적 allowlist다.
 *
 * `APP_ENV_KEYS`에만 추가하고 이 목록을 빠뜨리면 값이 번들에 정의되지 않아 늘 기본값으로
 * 떨어진다. 타입 검사도 테스트도 통과하는데 기능만 조용히 죽으므로 여기서 둘을 묶어 둔다.
 */
test("every validated public key reaches the browser bundle", async () => {
  const source = await readFile(new URL("../vite.config.mjs", import.meta.url), "utf8");
  const browserEnv = source.slice(
    source.indexOf("const browserEnv = {"),
    source.indexOf("};", source.indexOf("const browserEnv = {")),
  );

  for (const key of APP_ENV_KEYS) {
    assert.ok(browserEnv.includes(`${key}:`), `${key} must be defined in browserEnv`);
  }
});
