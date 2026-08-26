/**
 * HTTP 경계의 오류 분류.
 *
 * 화면은 "실패"를 한 덩어리로 다루면 안 된다. 전송 실패, JSON 파싱 실패, 계약 위반과 도메인
 * 오류는 사용자에게 서로 다른 다음 행동을 요구한다. 그래서 여기서는 **분류만** 정한다.
 *
 * 사용자에게 보여줄 문구는 기능마다 다르므로 여기 두지 않는다. 같은 409라도 장부는 "다른
 * 사용자가 먼저 저장했습니다"라고 안내해야 하고, 인증은 계정 존재 여부를 드러내지 않으려고
 * 사유를 뭉뚱그려야 한다. 분류를 공유하고 문구는 각 기능이 소유한다.
 */

export type ApiErrorKind =
  /** 네트워크에 닿지 못했다. 오프라인 처리 대상. */
  | "offline"
  /** 요청이 취소되었다. 화면에 오류로 보여주지 않는다. */
  | "canceled"
  /** 세션이 없거나 만료됐다(401). */
  | "unauthorized"
  /** 권한이 부족하다(403). CSRF 토큰 불일치도 여기에 들어온다. */
  | "forbidden"
  /** 대상이 없다(404). */
  | "notFound"
  /** 낙관적 잠금 충돌(409). 다른 사용자가 먼저 저장했다. */
  | "conflict"
  /** 입력값이 서버 검증을 통과하지 못했다(422 등). */
  | "validation"
  /** 서버 내부 오류(5xx). */
  | "server"
  /** 응답이 계약과 다르다. 배포 불일치일 가능성이 높다. */
  | "contract";

export interface ApiErrorOptions {
  kind: ApiErrorKind;
  message: string;
  status?: number;
  /** 서버가 준 도메인 오류 코드(api.md의 `code`). */
  code?: string;
  /** 추적용 요청 식별자(api.md의 `request_id`). */
  requestId?: string;
  cause?: unknown;
}

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number | undefined;
  readonly code: string | undefined;
  readonly requestId: string | undefined;

  constructor(options: ApiErrorOptions) {
    super(options.message, options.cause == null ? undefined : { cause: options.cause });
    this.name = "ApiError";
    this.kind = options.kind;
    this.status = options.status;
    this.code = options.code;
    this.requestId = options.requestId;
  }
}

export function isCanceled(error: unknown): boolean {
  return error instanceof ApiError && error.kind === "canceled";
}

/** HTTP 상태 코드를 오류 종류로. */
export function kindFromStatus(status: number): ApiErrorKind {
  if (status === 401) return "unauthorized";
  if (status === 403) return "forbidden";
  if (status === 404) return "notFound";
  if (status === 409) return "conflict";
  if (status === 400 || status === 422) return "validation";
  if (status >= 500) return "server";
  return "server";
}
