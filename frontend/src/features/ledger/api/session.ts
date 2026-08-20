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
 *   `GET /auth/me`도 같은 필드로 새 토큰을 발급해 준다. 서버는 해시만 보관해 원본을 다시 줄 수
 *   없으므로, 세션 확인 시점에 토큰을 교체하는 방식이다.
 *
 * 그래서 토큰은 모듈 메모리에만 둔다. 개인정보 정책이 인증정보·토큰의 저장소 기록을 금지하므로
 * localStorage나 sessionStorage에 넣지 않는다. 로그에도 남기지 않는다.
 * 새로고침으로 메모리가 비어도 AuthContext가 `/auth/me`를 호출해 다시 채운다.
 *
 * 알려진 한계: 같은 세션을 여러 탭에서 열면 나중에 연 탭이 앞선 탭의 토큰을 무효화한다.
 * 앞선 탭은 쓰기에서 403을 받고, 새로고침하면 정상으로 돌아온다.
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
