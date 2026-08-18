/**
 * 날짜 변환.
 *
 * API 계약 규칙(project-wiki contracts/api.md): 날짜와 시간은 타임존을 포함한 ISO 8601을 쓴다.
 * DB는 두 종류를 함께 쓴다.
 *
 *   DATE        (tenancy_expiry_date, received_at, desired_move_in_date …) → "YYYY-MM-DD"
 *   TIMESTAMPTZ (last_contact_at, interaction_at …)                        → ISO 8601 + offset
 *
 * 화면의 `<input type="date">`와 그리드 셀은 모두 "YYYY-MM-DD"만 다루므로
 * TIMESTAMPTZ는 표시할 때 날짜 부분만 잘라 쓰고, 되돌려 보낼 때는 원본 시각을 유지한다.
 */

const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;

/** DATE 컬럼 값을 화면 표기로. 형식이 어긋나면 값을 버리지 않고 그대로 노출한다. */
export function formatDate(value: string | null | undefined): string {
  if (value == null || value === "") return "";
  return DATE_ONLY.test(value) ? value : value;
}

/** 화면 입력을 DATE 컬럼 값으로. 빈 값은 null(컬럼 NULL)로 보낸다. */
export function parseDate(value: string | null | undefined): string | null {
  if (value == null) return null;
  const text = value.trim();
  if (text === "") return null;
  return DATE_ONLY.test(text) ? text : null;
}

/**
 * TIMESTAMPTZ를 화면의 날짜 표기로 자른다.
 * 사용자의 로컬 타임존 기준 날짜를 쓴다. 그리드의 「최근 통화일」이 사용자가 체감하는 날짜여야 한다.
 */
export function formatTimestampAsDate(value: string | null | undefined): string {
  if (value == null || value === "") return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "";
  const year = parsed.getFullYear();
  const month = String(parsed.getMonth() + 1).padStart(2, "0");
  const day = String(parsed.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

/**
 * 화면에서 고른 날짜를 TIMESTAMPTZ로 되돌린다.
 *
 * 날짜만 바뀌고 시각이 의미를 갖는 필드(last_contact_at)는 원본 시각을 잃지 않도록
 * `previous`의 시·분·초를 유지한다. 원본이 없으면 해당 날짜의 로컬 자정을 쓴다.
 */
export function parseDateAsTimestamp(
  value: string | null | undefined,
  previous?: string | null,
): string | null {
  const dateOnly = parseDate(value);
  if (dateOnly == null) return null;

  const parts = dateOnly.split("-").map(Number);
  const [year, month, day] = parts;
  if (year == null || month == null || day == null) return null;

  const base = previous != null && previous !== "" ? new Date(previous) : null;
  const hasBase = base != null && !Number.isNaN(base.getTime());

  const next = new Date(
    year,
    month - 1,
    day,
    hasBase ? base.getHours() : 0,
    hasBase ? base.getMinutes() : 0,
    hasBase ? base.getSeconds() : 0,
    hasBase ? base.getMilliseconds() : 0,
  );
  return toIsoWithOffset(next);
}

/** 현재 시각을 타임존 오프셋을 포함한 ISO 8601로. `Date.toISOString()`은 UTC라 오프셋이 사라진다. */
export function nowIso(): string {
  return toIsoWithOffset(new Date());
}

/** 오늘 날짜를 "YYYY-MM-DD"로. 구입장 [오늘] 버튼(F1-DM-09)에 쓴다. */
export function todayDate(): string {
  return formatTimestampAsDate(nowIso());
}

/** 기준일로부터 N년 뒤. 구입장 [2년후 오늘] 버튼(F1-DM-10)에 쓴다. */
export function addYears(date: string, years: number): string {
  const parts = date.split("-").map(Number);
  const [year, month, day] = parts;
  if (year == null || month == null || day == null) return date;
  const next = new Date(year + years, month - 1, day);
  return formatTimestampAsDate(toIsoWithOffset(next));
}

function toIsoWithOffset(date: Date): string {
  const offsetMinutes = -date.getTimezoneOffset();
  const sign = offsetMinutes >= 0 ? "+" : "-";
  const absolute = Math.abs(offsetMinutes);
  const offsetHours = String(Math.floor(absolute / 60)).padStart(2, "0");
  const offsetRest = String(absolute % 60).padStart(2, "0");

  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  const seconds = String(date.getSeconds()).padStart(2, "0");

  return `${year}-${month}-${day}T${hours}:${minutes}:${seconds}${sign}${offsetHours}:${offsetRest}`;
}
