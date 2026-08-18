/**
 * 연락처 정규화와 표시.
 *
 * `party_contact`는 원본(`contact_value`)과 정규화 값(`normalized_contact_value`)을 함께 두고,
 * 중복 방지 UNIQUE 인덱스는 정규화 값을 쓴다. 정규화 규칙의 정본은 백엔드이며
 * 프론트는 문자 대상 중복 제거처럼 화면 안에서 끝나는 판정에만 이 함수를 쓴다.
 *
 * 개인정보 정책상 연락처는 URL, 로그, 분석 도구에 넣지 않는다.
 * 화면 밖으로 나갈 수 있는 문자열에는 `maskPhone`을 쓴다.
 */

/** 숫자만 남긴다. 화면 안 중복 판정용. 저장 값의 정본은 백엔드가 정한다. */
export function normalizePhone(value: string | null | undefined): string {
  if (value == null) return "";
  return String(value).replace(/\D/g, "");
}

/**
 * 숫자열을 하이픈 표기로. 규칙에 맞지 않으면 원본을 그대로 돌려준다.
 * 실사용 장부에는 내선·해외번호처럼 규칙을 벗어난 값이 섞여 있어 임의로 버리지 않는다.
 */
export function formatPhone(value: string | null | undefined): string {
  if (value == null || value === "") return "";
  const digits = normalizePhone(value);

  if (digits.length === 11 && digits.startsWith("01")) {
    return `${digits.slice(0, 3)}-${digits.slice(3, 7)}-${digits.slice(7)}`;
  }
  if (digits.length === 10 && digits.startsWith("02")) {
    return `${digits.slice(0, 2)}-${digits.slice(2, 6)}-${digits.slice(6)}`;
  }
  if (digits.length === 10) {
    return `${digits.slice(0, 3)}-${digits.slice(3, 6)}-${digits.slice(6)}`;
  }
  return String(value);
}

/** 로그·오류 메시지에 넣어도 되는 형태로 가린다. "010-0000-9009" → "010-****-9009" */
export function maskPhone(value: string | null | undefined): string {
  const digits = normalizePhone(value);
  if (digits.length < 7) return "***";
  return `${digits.slice(0, 3)}-****-${digits.slice(-4)}`;
}

/** 두 연락처가 같은 번호인지. 문자 대상 중복 제거(F1-MS)에 쓴다. */
export function isSamePhone(left: string | null | undefined, right: string | null | undefined): boolean {
  const a = normalizePhone(left);
  const b = normalizePhone(right);
  return a !== "" && a === b;
}
