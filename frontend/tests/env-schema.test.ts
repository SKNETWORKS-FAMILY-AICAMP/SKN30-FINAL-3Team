import assert from "node:assert/strict";
import test from "node:test";

import { parseAppEnv } from "../src/config/envSchema.ts";

function validEnv(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    VITE_AUTH_DEVELOPMENT_ENABLED: "true",
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
    authDevelopmentEnabled: true,
    ledgerSource: "mock",
    f3Source: "mock",
    calendarSource: "mock",
    mockRowCount: 7200,
    mockLatencyMs: 350,
  });
  assert.ok(Object.isFrozen(parsed));
});

test('accepts the exact public boolean value "true"', () => {
  assert.equal(
    parseAppEnv(validEnv({ VITE_AUTH_DEVELOPMENT_ENABLED: "true" }))
      .authDevelopmentEnabled,
    true,
  );
});

test('accepts the exact public boolean value "false"', () => {
  assert.equal(
    parseAppEnv(validEnv({ VITE_AUTH_DEVELOPMENT_ENABLED: "false" }))
      .authDevelopmentEnabled,
    false,
  );
});

test("rejects a missing development-auth flag", () => {
  assert.throws(
    () => parseAppEnv(validEnv({ VITE_AUTH_DEVELOPMENT_ENABLED: undefined })),
    /VITE_AUTH_DEVELOPMENT_ENABLED/,
  );
});

test("rejects non-canonical development-auth flag values", () => {
  for (const value of ["", " ", "TRUE", "False", "1", "yes", true]) {
    assert.throws(
      () => parseAppEnv(validEnv({ VITE_AUTH_DEVELOPMENT_ENABLED: value })),
      /VITE_AUTH_DEVELOPMENT_ENABLED/,
      String(value),
    );
  }
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

test("F3 source defaults to the ledger source when unset", () => {
  // 백엔드가 없는 환경에서 F3만 실서버를 부르지 않게 한다.
  assert.equal(parseAppEnv(validEnv({ VITE_LEDGER_SOURCE: "api" })).f3Source, "api");
  assert.equal(parseAppEnv(validEnv({ VITE_LEDGER_SOURCE: "mock" })).f3Source, "mock");
  for (const unset of [undefined, "", "  "]) {
    assert.equal(parseAppEnv(validEnv({ VITE_F3_SOURCE: unset })).f3Source, "mock");
  }
});

test("F3 source can differ from the ledger source", () => {
  // Backend는 살아 있어도 Worker가 꺼져 있으면 실행이 QUEUED에 머문다. 그때 쓰는 조합이다.
  const parsed = parseAppEnv(validEnv({ VITE_LEDGER_SOURCE: "api", VITE_F3_SOURCE: "mock" }));
  assert.equal(parsed.ledgerSource, "api");
  assert.equal(parsed.f3Source, "mock");
});

test("rejects an invalid F3 source instead of falling back", () => {
  assert.throws(() => parseAppEnv(validEnv({ VITE_F3_SOURCE: "fixture" })), /VITE_F3_SOURCE/);
});

test("calendar source defaults to the ledger source when unset", () => {
  assert.equal(parseAppEnv(validEnv({ VITE_LEDGER_SOURCE: "api" })).calendarSource, "api");
  assert.equal(parseAppEnv(validEnv({ VITE_LEDGER_SOURCE: "mock" })).calendarSource, "mock");
  for (const unset of [undefined, "", "  "]) {
    assert.equal(parseAppEnv(validEnv({ VITE_CALENDAR_SOURCE: unset })).calendarSource, "mock");
  }
});

test("calendar source can differ from the ledger source", () => {
  const parsed = parseAppEnv(
    validEnv({ VITE_LEDGER_SOURCE: "api", VITE_CALENDAR_SOURCE: "mock" }),
  );
  assert.equal(parsed.ledgerSource, "api");
  assert.equal(parsed.calendarSource, "mock");
});

test("rejects an invalid calendar source instead of falling back", () => {
  assert.throws(
    () => parseAppEnv(validEnv({ VITE_CALENDAR_SOURCE: "fixture" })),
    /VITE_CALENDAR_SOURCE/,
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
