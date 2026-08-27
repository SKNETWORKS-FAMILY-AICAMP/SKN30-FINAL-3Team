/**
 * 인증 오류 분류.
 *
 * `shared/api`의 `ApiError`와 종류를 따로 두는 이유는 문구 규칙이 다르기 때문이다. 장부 오류는
 * 사용자가 무엇을 고쳐야 하는지 최대한 알려주는 게 맞지만, 로그인 실패 문구는 반대로 **계정이
 * 존재하는지, 비활성인지, 비밀번호만 틀렸는지를 구분해서 알려주면 안 된다**. 아이디 목록을
 * 훑는 쪽에 정보를 주기 때문이다. 그래서 자격증명 거절은 사유와 무관하게 한 문구로 모은다.
 *
 * 서버 원문 message는 사용자에게 그대로 내보내지 않는다. 추적용 request_id만 덧붙인다.
 */

export type AuthErrorKind =
  /** 네트워크에 닿지 못했다. */
  | "offline"
  /** 요청이 취소되었다. 화면에 오류로 보여주지 않는다. */
  | "canceled"
  /** 세션이 없거나 만료됐다(401). 로그인 화면으로 돌려보낼 신호다. */
  | "unauthenticated"
  /** 자격증명이나 권한이 거절됐다(403). CSRF 불일치도 여기에 들어온다. */
  | "rejected"
  /** 이 환경에 없는 인증 경로다(404). 개발 세션은 설정된 local·dev에만 등록된다. */
  | "unavailable"
  /** 서버 내부 오류(5xx). */
  | "server"
  /** 응답이 계약과 다르다. 배포 불일치일 가능성이 높다. */
  | "contract";

export interface AuthErrorOptions {
  kind: AuthErrorKind;
  message: string;
  status?: number;
  /** 서버가 준 도메인 오류 코드(api.md의 `code`). */
  code?: string;
  /** 추적용 요청 식별자(api.md의 `request_id`). */
  requestId?: string;
  cause?: unknown;
}

export class AuthError extends Error {
  readonly kind: AuthErrorKind;
  readonly status: number | undefined;
  readonly code: string | undefined;
  readonly requestId: string | undefined;

  constructor(options: AuthErrorOptions) {
    super(options.message, options.cause == null ? undefined : { cause: options.cause });
    this.name = "AuthError";
    this.kind = options.kind;
    this.status = options.status;
    this.code = options.code;
    this.requestId = options.requestId;
  }
}

export function isCanceled(error: unknown): boolean {
  return error instanceof AuthError && error.kind === "canceled";
}

/** 세션이 끊긴 상태인지. 게이트를 다시 세울지 판단하는 기준이다. */
export function isSessionLost(error: unknown): boolean {
  return error instanceof AuthError && error.kind === "unauthenticated";
}

/** 사용자에게 보여줄 문구. 계정 존재 여부를 드러내지 않는다. */
export function describeAuthError(error: unknown): string {
  if (!(error instanceof AuthError)) {
    return "알 수 없는 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.";
  }

  const base = messageFor(error.kind);
  return error.requestId == null ? base : `${base} (요청 번호 ${error.requestId})`;
}

function messageFor(kind: AuthErrorKind): string {
  switch (kind) {
    case "offline":
      return "서버에 연결하지 못했습니다. 네트워크를 확인한 뒤 다시 시도해 주세요.";
    case "canceled":
      return "요청이 취소되었습니다.";
    case "unauthenticated":
      return "로그인 정보가 올바르지 않습니다.";
    case "rejected":
      return "로그인 정보가 올바르지 않습니다.";
    case "unavailable":
      return "이 환경에서는 사용할 수 없는 로그인 방식입니다.";
    case "server":
      return "서버에서 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.";
    case "contract":
      return "서버 응답 형식이 예상과 다릅니다. 배포 버전을 확인해 주세요.";
  }
}

/** HTTP 상태 코드를 오류 종류로. */
export function kindFromStatus(status: number): AuthErrorKind {
  if (status === 401) return "unauthenticated";
  if (status === 403) return "rejected";
  if (status === 404) return "unavailable";
  // 입력 검증 실패도 자격증명 거절과 같은 문구로 모은다. 어느 필드가 문제인지 서버가 알려줘도
  // 로그인 화면에서 그대로 노출하면 아이디 존재 여부를 넘겨짚을 단서가 된다.
  if (status === 400 || status === 422) return "rejected";
  if (status >= 500) return "server";
  return "server";
}
