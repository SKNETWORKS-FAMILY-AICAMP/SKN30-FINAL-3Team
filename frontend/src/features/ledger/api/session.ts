/**
 * 세션과 CSRF 토큰 보관.
 *
 * 백엔드 구현(`backend/src/api/authentication.py`) 기준 사실:
 *
 * - 세션은 `brokerage_session` HttpOnly Cookie로 전달된다. JavaScript는 읽을 수 없고 읽을 필요도 없다.
 *   `fetch`에 `credentials: "include"`만 주면 브라우저가 알아서 실어 보낸다.
 * - CSRF 토큰은 **응답 본문**으로만 내려온다. `POST /auth/development-session`의 `csrf_token` 필드다.
 *   상태 변경 요청은 이 값을 `X-CSRF-Token` 헤더로 되돌려 보내야 한다.
 *
 * 그래서 토큰은 모듈 메모리에만 둔다. 개인정보 정책이 인증정보·토큰의 저장소 기록을 금지하므로
 * localStorage나 sessionStorage에 넣지 않는다. 로그에도 남기지 않는다.
 *
 * 알려진 공백(백엔드 확인 필요):
 * `GET /auth/me`는 CSRF 토큰을 돌려주지 않는다. 따라서 새로고침하면 세션 쿠키는 살아 있는데
 * 메모리의 토큰만 사라져 모든 쓰기 요청이 403이 된다. `/auth/me` 응답에 토큰을 포함하거나
 * 별도 발급 경로가 필요하다. project-wiki open-questions에 등록되어 있다.
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
