/**
 * 세션 사용자 모델.
 *
 * 서버 DTO(`backend/src/api/schemas/authentication.py`의 `CurrentUserResponse`)를 화면 모델로
 * 바꾸는 경계다. snake_case 전송 이름을 화면까지 끌고 가지 않는다.
 *
 * 응답은 외부 입력이므로 타입 단언으로 통과시키지 않고 여기서 실제로 검사한다. 배포 불일치로
 * 형태가 달라지면 화면 곳곳에서 undefined로 터지는 대신 이 지점에서 계약 오류로 드러나야 한다.
 */

import { AuthError } from "./authError.ts";

/** 백엔드 `UserRole`. 권한 분기의 정본은 서버이고 화면은 표시와 비활성화에만 쓴다. */
export type UserRole = "OWNER" | "STAFF" | "READ_ONLY";

export interface AuthUser {
  readonly id: number;
  readonly brokerageId: number;
  /** 로그인 아이디. 화면에는 기본으로 노출하지 않는다. */
  readonly loginId: string;
  readonly displayName: string;
  readonly role: UserRole;
}

/** 세션 확인·발급 응답. CSRF 원문은 저장하지 않고 호출부가 메모리 보관소로 넘긴다. */
export interface SessionPayload {
  readonly user: AuthUser;
  readonly csrfToken: string;
}

export function decodeSessionPayload(value: unknown): SessionPayload {
  const record = asRecord(value, "세션 응답");
  return {
    user: decodeAuthUser(record["user"]),
    csrfToken: readString(record, "csrf_token"),
  };
}

export function decodeAuthUser(value: unknown): AuthUser {
  const record = asRecord(value, "사용자");
  return {
    id: readInteger(record, "id"),
    brokerageId: readInteger(record, "brokerage_id"),
    loginId: readString(record, "login_id"),
    displayName: readString(record, "display_name"),
    role: readRole(record["role"]),
  };
}

/**
 * 모르는 역할 문자열은 가장 낮은 권한으로 떨어뜨린다.
 *
 * 서버가 역할을 추가했을 때 화면이 열거형 검사로 로그인 자체를 막아버리면 배포 순서만으로
 * 사용자가 잠긴다. 반대로 모르는 값을 관리자급으로 취급하면 권한이 새어나간다. 그래서 통과시키되
 * 읽기 전용으로 본다. 실제 권한 판정은 어차피 서버가 한다.
 */
function readRole(value: unknown): UserRole {
  return value === "OWNER" || value === "STAFF" || value === "READ_ONLY" ? value : "READ_ONLY";
}

function asRecord(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new AuthError({ kind: "contract", message: `${label} 응답이 객체가 아닙니다.` });
  }
  return value as Record<string, unknown>;
}

function readString(record: Record<string, unknown>, key: string): string {
  const value = record[key];
  if (typeof value !== "string" || value === "") {
    throw new AuthError({ kind: "contract", message: `응답에 ${key} 문자열이 없습니다.` });
  }
  return value;
}

function readInteger(record: Record<string, unknown>, key: string): number {
  const value = record[key];
  if (typeof value !== "number" || !Number.isInteger(value)) {
    throw new AuthError({ kind: "contract", message: `응답에 ${key} 정수가 없습니다.` });
  }
  return value;
}
