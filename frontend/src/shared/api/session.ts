/**
 * 세션과 CSRF 토큰 보관.
 *
 * 백엔드 구현(`backend/src/api/authentication.py`) 기준 사실:
 *
 * - 세션은 `brokerage_session` HttpOnly Cookie로 전달된다. JavaScript는 읽을 수 없고 읽을 필요도 없다.
 *   `fetch`에 `credentials: "include"`만 주면 브라우저가 알아서 실어 보낸다.
 * - CSRF 원문은 세션과 별개의 HttpOnly Cookie(`brokerage_csrf`)에도 실려 온다. HttpOnly라 JavaScript가
 *   Cookie를 직접 읽을 수 없으므로, 화면이 쓸 값은 **응답 본문**의 `csrf_token` 필드로 받는다.
 *   `POST /auth/development-session`과 `GET /auth/me`가 모두 이 필드를 싣는다.
 *   상태 변경 요청은 이 값을 `X-CSRF-Token` 헤더로 되돌려 보내야 한다.
 *
 *   `GET /auth/me`는 브라우저가 보낸 CSRF Cookie를 세션의 DB 해시와 비교한 뒤 **같은 원문을 그대로**
 *   돌려준다. 토큰을 새로 만들거나 서버 해시를 바꾸지 않으므로, 새로고침과 여러 탭이 서로의 토큰을
 *   무효화하지 않는다. Cookie가 없거나 해시와 다르면 403 `INVALID_CSRF_TOKEN`으로 거절한다.
 *
 * 그래서 토큰은 모듈 메모리에만 둔다. 개인정보 정책이 인증정보·토큰의 저장소 기록을 금지하므로
 * localStorage나 sessionStorage에 넣지 않는다. 로그에도 남기지 않는다.
 * 새로고침으로 메모리가 비어도 AuthContext가 `/auth/me`를 호출해 다시 채운다.
 */

let csrfToken: string | null = null;

export function getCsrfToken(): string | null {
  return csrfToken;
}

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

export function clearCsrfToken(): void {
  csrfToken = null;
}

/** 상태 변경 요청을 보낼 수 있는 상태인지. false면 쓰기 시도 전에 세션을 다시 확보해야 한다. */
export function canMutate(): boolean {
  return csrfToken != null && csrfToken !== "";
}
