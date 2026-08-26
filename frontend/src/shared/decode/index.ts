/**
 * 서버 응답 런타임 검증의 기본 도구.
 *
 * ADR-002: "API 응답, URL 파라미터, 사용자 입력과 브라우저 저장소 데이터는 런타임에서 별도로
 * 검증한다." 타입 선언은 컴파일 시점 약속일 뿐이라 실제 응답을 보장하지 않는다.
 *
 * 검증 라이브러리를 새로 추가하지 않았다. 필요한 형태가 좁고 고정되어 있어 표준 문법만으로
 * 충분하며 번들 비용과 교체 비용을 지불할 이유가 없다.
 *
 * 여기에는 어느 기능에나 같은 뜻인 원시 검증기만 둔다. DTO 하나하나를 읽는 도메인 검증기는
 * 그 계약을 소유한 기능이 갖는다.
 *
 * `shared/api`와 따로 두는 이유는 이 모듈이 **순수**하기 때문이다. HTTP 경계는 `import.meta.env`를
 * 읽는 설정 모듈에 의존하지만 검증기는 아무것에도 의존하지 않는다. 한 배럴로 묶으면 값 하나를
 * 검사하려는 쪽이 브라우저 번들러 없이는 못 도는 코드까지 함께 끌어온다.
 */

export class DecodeError extends Error {
  readonly path: string;

  constructor(path: string, message: string) {
    super(`${path}: ${message}`);
    this.name = "DecodeError";
    this.path = path;
  }
}

export function asRecord(value: unknown, path: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new DecodeError(path, `객체를 기대했지만 ${describe(value)}를 받았습니다.`);
  }
  return value as Record<string, unknown>;
}

export function asString(value: unknown, path: string): string {
  if (typeof value !== "string") {
    throw new DecodeError(path, `문자열을 기대했지만 ${describe(value)}를 받았습니다.`);
  }
  return value;
}

export function asNullableString(value: unknown, path: string): string | null {
  if (value === null || value === undefined) return null;
  return asString(value, path);
}

export function asNumber(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new DecodeError(path, `숫자를 기대했지만 ${describe(value)}를 받았습니다.`);
  }
  return value;
}

export function asNullableNumber(value: unknown, path: string): number | null {
  if (value === null || value === undefined) return null;
  return asNumber(value, path);
}

/**
 * NUMERIC 컬럼(평형, 면적).
 *
 * 백엔드가 Python `Decimal`로 선언한 값이다. Pydantic은 JSON 직렬화에서 Decimal을
 * 문자열로 내보낼 수 있어 `33.00`이 아니라 `"33.00"`으로 도착할 수 있다.
 * 어느 쪽이든 받아 숫자로 좁힌다. 여기서 흡수하지 않으면 화면 전체가 깨진다.
 */
export function asNullableDecimal(value: unknown, path: string): number | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  throw new DecodeError(path, `숫자 또는 숫자 문자열을 기대했지만 ${describe(value)}를 받았습니다.`);
}

export function asBoolean(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") {
    throw new DecodeError(path, `boolean을 기대했지만 ${describe(value)}를 받았습니다.`);
  }
  return value;
}

export function asNullableBoolean(value: unknown, path: string): boolean | null {
  if (value === null || value === undefined) return null;
  return asBoolean(value, path);
}

export function asArray(value: unknown, path: string): unknown[] {
  if (!Array.isArray(value)) {
    throw new DecodeError(path, `배열을 기대했지만 ${describe(value)}를 받았습니다.`);
  }
  return value;
}

/** JSONB 컬럼. 내용 구조는 계약하지 않고 통째로 보존한다. */
export function asJsonObject(value: unknown, path: string): Record<string, unknown> {
  if (value === null || value === undefined) return {};
  return asRecord(value, path);
}

export function describe(value: unknown): string {
  if (value === null) return "null";
  if (Array.isArray(value)) return "배열";
  return typeof value;
}
