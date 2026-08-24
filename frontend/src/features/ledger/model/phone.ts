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

/**
 * 입력 중인 번호를 하이픈 표기로 맞춘다.
 *
 * 완성된 번호만 다루는 `formatPhone`과 달리 타이핑 도중에도 끊어 준다.
 * 규칙을 벗어난 값(내선, +82, 해외번호)은 그대로 둔다. 실제 장부에 그런 값이 섞여 있어
 * 형식을 강제하면 적을 자리가 없어진다.
 */
export function formatPhoneInput(value: string | null | undefined): string {
  const raw = value ?? "";
  if (/[^0-9\-\s]/.test(raw)) return raw;
  const digits = normalizePhone(raw);
  if (digits === "") return "";

  if (digits.startsWith("02")) {
    if (digits.length <= 2) return digits;
    if (digits.length <= 6) return `${digits.slice(0, 2)}-${digits.slice(2)}`;
    return `${digits.slice(0, 2)}-${digits.slice(2, 6)}-${digits.slice(6, 10)}`;
  }
  if (digits.length <= 3) return digits;
  if (digits.length <= 7) return `${digits.slice(0, 3)}-${digits.slice(3)}`;
  return `${digits.slice(0, 3)}-${digits.slice(3, 7)}-${digits.slice(7, 11)}`;
}

/**
 * 전화번호 입력칸의 다음 값.
 *
 * 지우는 중에는 형식을 다시 붙이지 않는다. 그러지 않으면 백스페이스로 하이픈을 지우는 순간
 * 다시 붙어서 지워지지 않는 것처럼 느껴진다.
 */
export function nextPhoneInput(previous: string | null | undefined, next: string | null | undefined): string {
  const before = previous ?? "";
  const after = next ?? "";
  return after.length < before.length ? after : formatPhoneInput(after);
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
