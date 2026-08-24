import assert from "node:assert/strict";
import test from "node:test";

import { findForbiddenProfileEnvFiles, parseBackendOrigin } from "../vite.config.mjs";

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
