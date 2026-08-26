/**
 * HTTP 경계의 공개 진입점.
 *
 * 기능 모듈은 이 파일이 내보내는 것만 쓴다. 여기 있는 것은 어느 기능에나 같은 뜻인
 * 전송 계층뿐이며, 도메인 오류 문구와 DTO 검증기는 각 기능이 소유한다.
 */

export { request, expectNoContent } from "./httpClient.ts";
export type { QueryValue, RequestOptions } from "./httpClient.ts";

export { ApiError, isCanceled, kindFromStatus } from "./errors.ts";
export type { ApiErrorKind, ApiErrorOptions } from "./errors.ts";

// CSRF 원문 보관소. 세션을 발급·폐기하는 features/auth가 이 값을 채우고 비운다.
// 보관소가 둘이면 인증이 받은 토큰을 쓰기 요청이 못 보고 모든 저장이 403이 되므로 여기 하나뿐이다.
export { canMutate, clearCsrfToken, getCsrfToken, setCsrfToken } from "./session.ts";
