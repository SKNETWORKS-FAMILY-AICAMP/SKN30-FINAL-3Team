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
  /**
   * 사용자에게 그대로 보여도 되는 문구.
   *
   * 화면 코드가 직접 만든 오류에만 붙인다. 무엇을 고쳐야 하는지 아는 자리에서 쓴 문장이라
   * 일반 문구로 덮으면 "입력값을 확인해 주세요"만 남는다.
   *
   * 응답에서 만든 오류에는 붙이지 않는다. 서버 원문에는 개인정보, 토큰, 내부 구현이
   * 섞일 수 있어 분류나 도메인 코드로만 안내한다. 이 필드를 명시적으로 두는 이유가 그것이다.
   * `status`가 없다는 사실만으로 "화면이 만든 오류"라고 볼 수 없다. mock 전송처럼
   * 응답을 흉내 내면서 `status`를 싣지 않는 자리가 있다.
   */
  userMessage?: string;
  cause?: unknown;
}

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number | undefined;
  readonly code: string | undefined;
  readonly requestId: string | undefined;
  readonly userMessage: string | undefined;

  constructor(options: ApiErrorOptions) {
    super(options.message, options.cause == null ? undefined : { cause: options.cause });
    this.name = "ApiError";
    this.kind = options.kind;
    this.status = options.status;
    this.code = options.code;
    this.requestId = options.requestId;
    this.userMessage = options.userMessage;
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
  if (status >= 400) return "contract";
  return "server";
}

/**
 * 오류 응답 본문에서 공통 envelope를 읽는다.
 *
 * multipart 요청도 오류 응답은 JSON API와 같은 계약을 사용한다. 전송 방식마다 이 파싱을
 * 다시 만들면 `status`, `code`, `request_id` 중 일부가 조용히 사라지므로 응답 변환만 이 순수
 * 진입점에서 공유한다. 서버 `message`는 진단용 `ApiError.message`에만 보관하고, 사용자 문구는
 * 각 기능이 `kind`와 허용한 `code`로 결정한다(ADR-004).
 */
export async function apiErrorFromResponse(response: Response): Promise<ApiError> {
  const kind = kindFromStatus(response.status);
  let code: string | undefined;
  let requestId: string | undefined;
  let message = `요청이 실패했습니다 (HTTP ${response.status}).`;

  try {
    const body: unknown = await response.json();
    if (typeof body === "object" && body !== null && !Array.isArray(body)) {
      const record = body as Record<string, unknown>;
      if (typeof record["code"] === "string") code = record["code"];
      if (typeof record["request_id"] === "string") requestId = record["request_id"];
      if (typeof record["message"] === "string") message = record["message"];
    }
  } catch {
    // 오류 응답이 JSON이 아니어도 상태 코드 기반 분류는 유지한다.
  }

  return new ApiError({ kind, message, status: response.status, code, requestId });
}
