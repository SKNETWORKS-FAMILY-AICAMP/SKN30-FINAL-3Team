export type LedgerSource = "mock" | "api";

export interface AppEnv {
  /** 동일 origin의 /api 하위 기본 경로. */
  apiBaseUrl: string;
  /** 장부 데이터 출처. */
  ledgerSource: LedgerSource;
  /**
   * F3 교차 판정 출처.
   *
   * 장부와 따로 두는 이유는 두 기능의 가용성이 실제로 갈리기 때문이다. Backend는 살아 있어도
   * `WORKER_ENABLED=false`이면 F3 실행이 `QUEUED`에 머물러 완료 화면을 볼 수 없다. 그때
   * 장부는 `api`, F3만 `mock`으로 두고 화면을 확인한다. 지정하지 않으면 장부를 따라간다.
   */
  f3Source: LedgerSource;
  /** mock에서 생성할 매물장 행 수. */
  mockRowCount: number;
  /** mock 응답 지연(ms). */
  mockLatencyMs: number;
}

type EnvSource = Readonly<Record<string, unknown>>;

export const APP_ENV_KEYS = [
  "VITE_LEDGER_SOURCE",
  "VITE_F3_SOURCE",
  "VITE_API_BASE_URL",
  "VITE_MOCK_ROW_COUNT",
  "VITE_MOCK_LATENCY_MS",
] as const;

function readRequiredString(source: EnvSource, key: string): string {
  const value = source[key];
  if (typeof value !== "string" || value.trim() === "") {
    throw new Error(`${key} must be a non-empty string`);
  }
  return value.trim();
}

function readLedgerSource(source: EnvSource): LedgerSource {
  const value = readRequiredString(source, "VITE_LEDGER_SOURCE");
  if (value !== "mock" && value !== "api") {
    throw new Error('VITE_LEDGER_SOURCE must be either "mock" or "api"');
  }
  return value;
}

/** 지정하지 않으면 장부 출처를 따른다. 백엔드가 없는 환경에서 F3만 실서버를 부르지 않게 한다. */
function readF3Source(source: EnvSource, fallback: LedgerSource): LedgerSource {
  const raw = source["VITE_F3_SOURCE"];
  if (raw === undefined || raw === null || (typeof raw === "string" && raw.trim() === "")) {
    return fallback;
  }
  const value = readRequiredString(source, "VITE_F3_SOURCE");
  if (value !== "mock" && value !== "api") {
    throw new Error('VITE_F3_SOURCE must be either "mock" or "api"');
  }
  return value;
}

function readApiBaseUrl(source: EnvSource): string {
  const value = readRequiredString(source, "VITE_API_BASE_URL");
  const expectedOrigin = "https://frontend.invalid";
  let parsed: URL;

  if (!value.startsWith("/") || value.startsWith("//")) {
    throw new Error("VITE_API_BASE_URL must be a same-origin /api path");
  }

  try {
    parsed = new URL(value, expectedOrigin);
  } catch {
    throw new Error("VITE_API_BASE_URL must be a same-origin /api path");
  }

  if (
    parsed.origin !== expectedOrigin ||
    parsed.search !== "" ||
    parsed.hash !== "" ||
    !/^\/api(?:\/|$)/.test(parsed.pathname)
  ) {
    throw new Error("VITE_API_BASE_URL must be a same-origin /api path");
  }

  return parsed.pathname.replace(/\/+$/, "") || "/api";
}

function readNonNegativeInteger(source: EnvSource, key: string): number {
  const value = readRequiredString(source, key);
  if (!/^(?:0|[1-9]\d*)$/.test(value)) {
    throw new Error(`${key} must be a non-negative integer`);
  }

  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed)) {
    throw new Error(`${key} must be a non-negative safe integer`);
  }
  return parsed;
}

export function parseAppEnv(source: EnvSource): Readonly<AppEnv> {
  const ledgerSource = readLedgerSource(source);
  return Object.freeze({
    apiBaseUrl: readApiBaseUrl(source),
    ledgerSource,
    f3Source: readF3Source(source, ledgerSource),
    mockRowCount: readNonNegativeInteger(source, "VITE_MOCK_ROW_COUNT"),
    mockLatencyMs: readNonNegativeInteger(source, "VITE_MOCK_LATENCY_MS"),
  });
}
