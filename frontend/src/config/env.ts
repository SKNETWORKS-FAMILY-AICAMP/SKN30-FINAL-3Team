/**
 * 빌드 시점 환경 설정.
 *
 * `import.meta.env`는 문자열 아니면 undefined이므로 그대로 믿지 않고 여기서 좁힌다.
 * 비밀값은 넣지 않는다. Vite의 `VITE_` 변수는 번들에 그대로 박히므로 공개해도 되는 값만 둔다.
 */

export type LedgerSource = "mock" | "api";

export interface AppEnv {
  /** API 기본 경로. 개발에서는 Vite proxy를 거치도록 같은 오리진 경로를 쓴다. */
  apiBaseUrl: string;
  /** 장부 데이터 출처. 백엔드 준비 전에는 mock으로 화면을 완성한다. */
  ledgerSource: LedgerSource;
  /** mock에서 생성할 매물장 행 수. 실제 API를 쓰면 무시된다. */
  mockRowCount: number;
  /** mock 응답 지연(ms). 로딩 상태를 실제로 확인하기 위한 값이다. */
  mockLatencyMs: number;
}

function readString(value: unknown, fallback: string): string {
  return typeof value === "string" && value.trim() !== "" ? value.trim() : fallback;
}

function readInteger(value: unknown, fallback: number): number {
  if (typeof value !== "string") return fallback;
  const parsed = Number.parseInt(value, 10);
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : fallback;
}

function readLedgerSource(value: unknown): LedgerSource {
  return value === "api" ? "api" : "mock";
}

const source = import.meta.env as Record<string, unknown>;

export const APP_ENV: AppEnv = Object.freeze({
  apiBaseUrl: readString(source["VITE_API_BASE_URL"], "/api/v1"),
  ledgerSource: readLedgerSource(source["VITE_LEDGER_SOURCE"]),
  mockRowCount: readInteger(source["VITE_MOCK_ROW_COUNT"], 7200),
  mockLatencyMs: readInteger(source["VITE_MOCK_LATENCY_MS"], 350),
});

export function isMockSource(): boolean {
  return APP_ENV.ledgerSource === "mock";
}
