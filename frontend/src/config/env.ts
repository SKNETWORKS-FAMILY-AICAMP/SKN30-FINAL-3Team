/**
 * 빌드 시점 환경 설정.
 *
 * `import.meta.env`는 빌드 입력이므로 그대로 믿지 않고 순수 파서에서 검증한다.
 * 비밀값은 넣지 않는다. Vite의 `VITE_` 변수는 번들에 그대로 박히므로 공개해도 되는 값만 둔다.
 */

import { parseAppEnv } from "./envSchema.ts";

export type { AppEnv, LedgerSource } from "./envSchema.ts";

export const APP_ENV = parseAppEnv({
  VITE_LEDGER_SOURCE: import.meta.env.VITE_LEDGER_SOURCE,
  VITE_API_BASE_URL: import.meta.env.VITE_API_BASE_URL,
  VITE_MOCK_ROW_COUNT: import.meta.env.VITE_MOCK_ROW_COUNT,
  VITE_MOCK_LATENCY_MS: import.meta.env.VITE_MOCK_LATENCY_MS,
});

export function isMockSource(): boolean {
  return APP_ENV.ledgerSource === "mock";
}
