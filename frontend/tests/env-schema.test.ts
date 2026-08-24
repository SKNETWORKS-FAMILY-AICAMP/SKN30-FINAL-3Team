import assert from "node:assert/strict";
import test from "node:test";

import { parseAppEnv } from "../src/config/envSchema.ts";

function validEnv(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    VITE_LEDGER_SOURCE: "mock",
    VITE_API_BASE_URL: "/api/v1",
    VITE_MOCK_ROW_COUNT: "7200",
    VITE_MOCK_LATENCY_MS: "350",
    ...overrides,
  };
}

test("parses the complete public frontend environment", () => {
  const parsed = parseAppEnv(validEnv());

  assert.deepEqual(parsed, {
    apiBaseUrl: "/api/v1",
    ledgerSource: "mock",
    mockRowCount: 7200,
    mockLatencyMs: 350,
  });
  assert.ok(Object.isFrozen(parsed));
});

test("accepts and normalizes any same-origin /api subtree", () => {
  for (const [value, expected] of [
    ["/api", "/api"],
    ["/api/", "/api"],
    ["/api/v2", "/api/v2"],
    ["/api/tenant/v3/", "/api/tenant/v3"],
  ]) {
    assert.equal(parseAppEnv(validEnv({ VITE_API_BASE_URL: value })).apiBaseUrl, expected);
  }
});

test("rejects cross-origin or non-api base URLs", () => {
  for (const value of [
    "https://example.com/api",
    "//example.com/api",
    "/apix/v1",
    "/api/../admin",
    "/api/v1?debug=true",
    "/api/v1#fragment",
  ]) {
    assert.throws(
      () => parseAppEnv(validEnv({ VITE_API_BASE_URL: value })),
      /VITE_API_BASE_URL/,
      value,
    );
  }
});

test("rejects missing and invalid ledger sources", () => {
  assert.throws(
    () => parseAppEnv(validEnv({ VITE_LEDGER_SOURCE: "fixture" })),
    /VITE_LEDGER_SOURCE/,
  );
  assert.throws(
    () => parseAppEnv(validEnv({ VITE_LEDGER_SOURCE: undefined })),
    /VITE_LEDGER_SOURCE/,
  );
});

test("rejects invalid mock numeric settings instead of silently falling back", () => {
  const invalidValues: ReadonlyArray<readonly [string, string]> = [
    ["VITE_MOCK_ROW_COUNT", "-1"],
    ["VITE_MOCK_ROW_COUNT", "1.5"],
    ["VITE_MOCK_LATENCY_MS", "10ms"],
    ["VITE_MOCK_LATENCY_MS", "9007199254740992"],
  ];

  for (const [key, value] of invalidValues) {
    assert.throws(() => parseAppEnv(validEnv({ [key]: value })), new RegExp(key), `${key}=${value}`);
  }
});
