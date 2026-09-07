export type LedgerSource = "mock" | "api";

export interface AppEnv {
  /** 동일 origin의 /api 하위 기본 경로. */
  apiBaseUrl: string;
  /** 개발 세션 로그인 UI를 공개할지 여부. API 등록 여부는 Backend가 최종 통제한다. */
  authDevelopmentEnabled: boolean;
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
  /** 캘린더 일정 출처. 지정하지 않으면 장부를 따라간다(F3와 같은 이유). */
  calendarSource: LedgerSource;
  /** mock에서 생성할 매물장 행 수. */
  mockRowCount: number;
  /** mock 응답 지연(ms). */
  mockLatencyMs: number;
}

type EnvSource = Readonly<Record<string, unknown>>;

export const APP_ENV_KEYS = [
  "VITE_AUTH_DEVELOPMENT_ENABLED",
  "VITE_LEDGER_SOURCE",
  "VITE_F3_SOURCE",
  "VITE_CALENDAR_SOURCE",
  "VITE_API_BASE_URL",
  "VITE_MOCK_ROW_COUNT",
  "VITE_MOCK_LATENCY_MS",
] as const;

function readRequiredBoolean(source: EnvSource, key: string): boolean {
  const value = source[key];
  if (value === "true") return true;
  if (value === "false") return false;
  throw new Error(`${key} must be exactly "true" or "false"`);
}

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

/**
 * 지정하지 않으면 장부 출처를 따르는 값을 읽는다. 백엔드가 없는 환경에서 그 기능만 실서버를
 * 부르지 않게 한다. F3와 캘린더가 같은 이유로 이 함수를 공유한다.
 */
function readSourceWithFallback(source: EnvSource, key: string, fallback: LedgerSource): LedgerSource {
  const raw = source[key];
  if (raw === undefined || raw === null || (typeof raw === "string" && raw.trim() === "")) {
    return fallback;
  }
  const value = readRequiredString(source, key);
  if (value !== "mock" && value !== "api") {
    throw new Error(`${key} must be either "mock" or "api"`);
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
    authDevelopmentEnabled: readRequiredBoolean(source, "VITE_AUTH_DEVELOPMENT_ENABLED"),
    ledgerSource,
    f3Source: readSourceWithFallback(source, "VITE_F3_SOURCE", ledgerSource),
    calendarSource: readSourceWithFallback(source, "VITE_CALENDAR_SOURCE", ledgerSource),
    mockRowCount: readNonNegativeInteger(source, "VITE_MOCK_ROW_COUNT"),
    mockLatencyMs: readNonNegativeInteger(source, "VITE_MOCK_LATENCY_MS"),
  });
}
