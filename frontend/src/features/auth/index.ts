/**
 * 인증 기능 모듈의 공개 진입점.
 *
 * 다른 기능은 이 파일이 내보내는 것만 쓴다. 내부 파일을 깊은 경로로 가져가지 않는다.
 * 그래야 로그인 방식이 개발 세션에서 자격증명 방식으로 바뀔 때 화면 쪽 코드가 따라 바뀌지 않는다.
 */

export { AuthProvider, currentUser, useAuth } from "./AuthContext.tsx";
export type { AnonymousReason, AuthSession, AuthState } from "./AuthContext.tsx";
export { AuthGate } from "./AuthGate.tsx";
export { LoginScreen } from "./LoginScreen.tsx";

export { AuthError, describeAuthError, isSessionLost } from "./model/authError.ts";
export type { AuthErrorKind } from "./model/authError.ts";
export { decodeAuthUser, decodeSessionPayload } from "./model/user.ts";
export type { AuthUser, SessionPayload, UserRole } from "./model/user.ts";
