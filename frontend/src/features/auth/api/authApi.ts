/**
 * 인증 HTTP 경계.
 *
 * 인증 요청은 장부와 같은 API 기본 경로를 쓰지만 전송 규칙이 조금 다르다. 장부 요청은 이미
 * 세션이 있다는 전제로 실패를 오류로 다루는 반면, 여기서는 401이 정상적인 결과값(=아직 로그인
 * 안 함)이다. 그래서 장부 transport를 빌려 쓰지 않고 이 모듈이 자기 요청을 직접 다룬다.
 *
 * CSRF 원문 보관소는 `features/ledger`의 공개 진입점을 통해 공유한다. 인증이 발급한 토큰을
 * 장부 쓰기가 그대로 써야 하므로 보관소가 둘이면 모든 저장이 403이 된다.
 */

import { APP_ENV } from "../../../config/env.ts";
import { clearCsrfToken, getCsrfToken, setCsrfToken } from "../../ledger/index.ts";
import { AuthError, kindFromStatus } from "../model/authError.ts";
import { decodeSessionPayload } from "../model/user.ts";
import type { AuthUser } from "../model/user.ts";

const API_BASE = APP_ENV.apiBaseUrl.replace(/\/$/, "");

/**
 * 현재 세션 확인.
 *
 * 새로고침하면 메모리의 CSRF 원문이 사라진다. `/auth/me`가 브라우저의 CSRF Cookie를 세션 해시와
 * 대조한 뒤 같은 원문을 돌려주므로, 이 호출 하나로 메모리를 다시 채운다. 서버 토큰을 회전시키지
 * 않으니 여러 탭이 서로를 무효화하지 않는다.
 */
export async function fetchCurrentUser(signal?: AbortSignal): Promise<AuthUser> {
  const payload = decodeSessionPayload(await request("/auth/me", { method: "GET", signal }));
  setCsrfToken(payload.csrfToken);
  return payload.user;
}

/**
 * 개발 세션 발급.
 *
 * 이 경로는 백엔드가 local 환경에서만 등록한다(`api/authentication.py`의 development_router).
 * 다른 환경에서는 404가 돌아오고 `unavailable`로 분류된다. 실제 아이디·비밀번호 로그인 계약은
 * 아직 정해지지 않았다(contracts/api.md).
 */
export async function createDevelopmentSession(): Promise<AuthUser> {
  const payload = decodeSessionPayload(
    await request("/auth/development-session", { method: "POST" }),
  );
  setCsrfToken(payload.csrfToken);
  return payload.user;
}

/**
 * 세션 폐기.
 *
 * 서버가 실패해도 브라우저 메모리의 토큰은 반드시 지운다. 공용 PC 전제(F1-SE-11)에서
 * 로그아웃을 눌렀는데 토큰이 남아 있는 상태가 가장 나쁘다.
 */
export async function deleteSession(): Promise<void> {
  try {
    await request("/auth/session", { method: "DELETE", expectBody: false });
  } finally {
    clearCsrfToken();
  }
}

interface RequestOptions {
  method: "GET" | "POST" | "DELETE";
  signal?: AbortSignal | undefined;
  /** 본문을 해석할지. 204로 끝나는 요청은 false. */
  expectBody?: boolean;
}

/**
 * 응답 본문을 `unknown`으로 돌려준다. 형태를 믿는 일은 호출부의 decode가 맡는다.
 * 본문을 기대하지 않는 요청은 `undefined`다.
 */
async function request(path: string, options: RequestOptions): Promise<unknown> {
  const headers: Record<string, string> = { Accept: "application/json" };

  // 상태를 바꾸는 요청만 CSRF 토큰을 싣는다. 아직 토큰이 없으면 헤더를 비우고 보낸다.
  // 세션 발급은 원래 토큰이 없는 상태에서 호출되므로 여기서 막으면 안 된다.
  if (options.method !== "GET") {
    const token = getCsrfToken();
    if (token != null && token !== "") headers["X-CSRF-Token"] = token;
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method: options.method,
      headers,
      // 세션·CSRF는 HttpOnly Cookie로 오간다. 이게 없으면 모든 요청이 401이다.
      credentials: "include",
      signal: options.signal ?? null,
    });
  } catch (cause) {
    if (isAbortError(cause)) {
      throw new AuthError({ kind: "canceled", message: "요청이 취소되었습니다.", cause });
    }
    throw new AuthError({ kind: "offline", message: "네트워크 요청에 실패했습니다.", cause });
  }

  if (!response.ok) throw await toAuthError(response);
  if (options.expectBody === false) return undefined;

  const text = await response.text();
  if (text.trim() === "") {
    throw new AuthError({ kind: "contract", message: "세션 응답 본문이 비어 있습니다." });
  }

  try {
    return JSON.parse(text) as unknown;
  } catch (cause) {
    throw new AuthError({
      kind: "contract",
      message: "응답을 JSON으로 해석하지 못했습니다.",
      status: response.status,
      cause,
    });
  }
}

function isAbortError(cause: unknown): boolean {
  return cause instanceof DOMException && cause.name === "AbortError";
}

/**
 * 오류 응답에서 code와 request_id만 건져낸다.
 *
 * 서버 message는 옮기지 않는다. 인증 실패 문구는 `describeAuthError`가 한 벌로 통일해야
 * 계정 존재 여부가 문구 차이로 새지 않는다.
 */
async function toAuthError(response: Response): Promise<AuthError> {
  const kind = kindFromStatus(response.status);
  let code: string | undefined;
  let requestId: string | undefined;

  try {
    const body: unknown = await response.json();
    if (typeof body === "object" && body !== null) {
      const record = body as Record<string, unknown>;
      if (typeof record["code"] === "string") code = record["code"];
      if (typeof record["request_id"] === "string") requestId = record["request_id"];
    }
  } catch {
    // 오류 응답이 JSON이 아닐 수 있다. 상태 코드 기반 분류만 사용한다.
  }

  return new AuthError({
    kind,
    message: `인증 요청이 실패했습니다 (HTTP ${response.status}).`,
    status: response.status,
    code,
    requestId,
  });
}
