/**
 * 평형 변환.
 *
 *   property_unit.pyeong              NUMERIC(6,2)   단일 값   → "33평"
 *   property_requirement.desired_pyeongs NUMERIC[]   복수 값   → "25 33평"  (F1-DM-12)
 *
 * 구입장은 희망 평형을 복수로 입력하므로 배열 형태를 별도로 다룬다.
 * 파싱하지 못한 원문은 `area_requirement_raw_text`로 보존한다(F1-DM-11).
 */

const PYEONG_NUMBER = /-?\d+(?:\.\d+)?/g;

/** "33평" → 33, "33" → 33, "" → null */
export function parsePyeong(input: string | null | undefined): number | null {
  const values = parsePyeongList(input);
  return values[0] ?? null;
}

/** 33 → "33평", 33.5 → "33.5평", null → "" */
export function formatPyeong(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "";
  return `${trimTrailingZeros(value)}평`;
}

/**
 * "25 33평" → [25, 33], "18, 21" → [18, 21], "" → []
 * 구분자는 공백·쉼표·물결·슬래시를 모두 허용한다. 실사용 입력이 일정하지 않다.
 */
export function parsePyeongList(input: string | null | undefined): number[] {
  if (input == null) return [];
  const text = String(input).trim();
  if (text === "") return [];

  PYEONG_NUMBER.lastIndex = 0;
  const values: number[] = [];
  for (const match of text.matchAll(PYEONG_NUMBER)) {
    const value = Number(match[0]);
    if (Number.isFinite(value)) values.push(value);
  }
  return values;
}

/** [25, 33] → "25 33평", [33] → "33평", [] → "" */
export function formatPyeongList(values: readonly number[] | null | undefined): string {
  if (values == null || values.length === 0) return "";
  return `${values.map(trimTrailingZeros).join(" ")}평`;
}

function trimTrailingZeros(value: number): string {
  return String(Number(value.toFixed(2)));
}
