/**
 * HTTP 전송의 공개 진입점.
 *
 * 기능 모듈은 이 파일이 내보내는 것만 쓴다. 여기 있는 것은 어느 기능에나 같은 뜻인
 * 전송 계층뿐이며, 도메인 오류 문구와 DTO 검증기는 각 기능이 소유한다.
 *
 * `shared/api`의 진입점은 둘이다. 이 배럴은 `httpClient`를 거쳐 `import.meta.env`를 읽는 설정
 * 모듈에 의존하므로, **오류 분류만 필요하면 순수한 `./errors.ts`를 가져온다**(ADR-004).
 * 아래에서 오류를 함께 내보내는 것은 이미 전송을 쓰는 쪽이 import을 늘리지 않게 하는 편의다.
 */

export { request, expectNoContent } from "./httpClient.ts";
export type { QueryValue, RequestOptions } from "./httpClient.ts";

export { ApiError, isCanceled, kindFromStatus } from "./errors.ts";
export type { ApiErrorKind, ApiErrorOptions } from "./errors.ts";

// CSRF 원문 보관소. 세션을 발급·폐기하는 features/auth가 이 값을 채우고 비운다.
// 보관소가 둘이면 인증이 받은 토큰을 쓰기 요청이 못 보고 모든 저장이 403이 되므로 여기 하나뿐이다.
export { canMutate, clearCsrfToken, getCsrfToken, setCsrfToken } from "./session.ts";
