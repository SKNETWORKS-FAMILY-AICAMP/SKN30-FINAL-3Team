/**
 * 금액 표기 변환 (F1-GR-01 대응 요구 F1-GR-09).
 *
 *   저장: 원 단위 정수 (DB BIGINT)
 *   표시: 억·만 단위 문자열  예) 2150000000 → "21.5억"
 *
 * F1-DM-11에 따라 사용자가 입력한 원문("28억선", "1~2억")은 파싱값과 별도로 보존해야 한다.
 * 이 파일은 숫자 변환만 담당하고 원문 보존은 매퍼가 `*_raw_text` 컬럼으로 처리한다.
 */

const EOK = 100_000_000;
const MAN = 10_000;
const CHEON = 1_000;

/** 금액 문자열을 나누는 구분자. "9억/380만"처럼 두 값이 한 칸에 들어온 경우를 자른다. */
const PAIR_SEPARATOR = /[/·]/;

/** 숫자 + 단위 토큰. 단위가 없으면 기본 단위로 해석한다. */
const AMOUNT_TOKEN = /(-?[\d,]+(?:\.\d+)?)\s*(억|만|천)?/g;

export type DefaultUnit = "won" | "man" | "eok";

const UNIT_MULTIPLIER: Record<string, number> = {
  억: EOK,
  만: MAN,
  천: CHEON,
};

const DEFAULT_UNIT_MULTIPLIER: Record<DefaultUnit, number> = {
  won: 1,
  man: MAN,
  eok: EOK,
};

/**
 * 표시용 금액 문자열을 원 단위 정수로 파싱한다.
 *
 * - "28.8억"        → 2_880_000_000
 * - "12억 8,000만"  → 1_280_000_000   (토큰을 합산한다)
 * - "28억선"        → 2_800_000_000   (꼬리말은 무시하고 원문은 매퍼가 보존한다)
 * - "9억/380만"     → 900_000_000     (첫 구간만 본다. 쌍은 parseMoneyPair를 쓴다)
 * - "협의", ""      → null
 *
 * 숫자를 하나도 찾지 못하면 null을 반환한다. 0과 null은 구분된다.
 */
export function parseMoney(input: string | null | undefined, defaultUnit: DefaultUnit = "won"): number | null {
  if (input == null) return null;
  const head = String(input).split(PAIR_SEPARATOR)[0] ?? "";
  const text = head.trim();
  if (text === "") return null;

  let total = 0;
  let matched = false;

  AMOUNT_TOKEN.lastIndex = 0;
  for (const match of text.matchAll(AMOUNT_TOKEN)) {
    const rawNumber = match[1];
    if (rawNumber == null) continue;
    const value = Number(rawNumber.replace(/,/g, ""));
    if (!Number.isFinite(value)) continue;
    const unit = match[2];
    const multiplier = unit != null ? (UNIT_MULTIPLIER[unit] ?? 1) : DEFAULT_UNIT_MULTIPLIER[defaultUnit];
    total += value * multiplier;
    matched = true;
  }

  if (!matched) return null;
  return Math.round(total);
}

/**
 * 원 단위 정수를 억·만 표기로 변환한다.
 *
 * - 2_150_000_000 → "21.5억"
 * - 1_500_000_000 → "15억"
 * - 3_800_000     → "380만"
 * - 0             → "0원"
 * - null          → ""
 *
 * 억 단위는 소수점 4자리까지 쓴다. 1억 = 10,000만이므로 만 단위 값은 손실 없이 왕복한다.
 */
export function formatMoney(amount: number | null | undefined): string {
  if (amount == null || !Number.isFinite(amount)) return "";
  if (amount === 0) return "0원";

  const sign = amount < 0 ? "-" : "";
  const absolute = Math.abs(amount);

  if (absolute >= EOK) return `${sign}${trimDecimals(absolute / EOK, 4)}억`;
  if (absolute >= MAN) return `${sign}${trimDecimals(absolute / MAN, 4)}만`;
  return `${sign}${absolute.toLocaleString("ko-KR")}원`;
}

function trimDecimals(value: number, maxDecimals: number): string {
  const fixed = value.toFixed(maxDecimals);
  return fixed.replace(/\.?0+$/, "");
}

/**
 * 월세 조건처럼 "보증금 / 차임"이 한 칸에 들어오는 값을 분해한다.
 * 구분자가 없으면 앞의 값만 채우고 뒤는 null로 둔다.
 */
export function parseMoneyPair(
  input: string | null | undefined,
): { first: number | null; second: number | null } {
  if (input == null) return { first: null, second: null };
  const [head, tail] = String(input).split(PAIR_SEPARATOR);
  return {
    first: parseMoney(head),
    second: tail == null ? null : parseMoney(tail),
  };
}

/** 보증금과 차임을 그리드 「보증금 / 차임」 열 표기로 합친다. 값이 없는 쪽은 생략한다. */
export function formatMoneyPair(first: number | null | undefined, second: number | null | undefined): string {
  const parts = [formatMoney(first), formatMoney(second)].filter((part) => part !== "");
  return parts.join(" / ");
}
