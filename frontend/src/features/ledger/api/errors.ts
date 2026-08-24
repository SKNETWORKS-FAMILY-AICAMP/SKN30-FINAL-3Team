/**
 * API 오류 분류.
 *
 * 화면은 "실패"를 한 덩어리로 다루면 안 된다. 요구사항이 상태별로 다른 화면을 지정한다.
 *   - 불러오기 실패는 입력을 건드리지 않고 재시도를 제공한다(F1-GR 로드 오류 화면).
 *   - 저장 충돌은 롤백하고 해당 셀을 표시한다(F1-GR-26).
 *   - 연결 단절은 브라우저에 보관하고 복구 시 재전송한다(F1-GR-35).
 *   - 권한 부족은 재시도할 대상이 아니다.
 *
 * 그래서 전송 실패, JSON 파싱 실패, 계약 위반, 도메인 오류를 서로 다른 종류로 구분한다.
 */

export type LedgerErrorKind =
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
  /** row_version 충돌(409). 다른 사용자가 먼저 저장했다. */
  | "conflict"
  /** 입력값이 서버 검증을 통과하지 못했다(422 등). */
  | "validation"
  /** 서버 내부 오류(5xx). */
  | "server"
  /** 응답이 계약과 다르다. 배포 불일치일 가능성이 높다. */
  | "contract";

export interface LedgerApiErrorOptions {
  kind: LedgerErrorKind;
  message: string;
  status?: number;
  /** 서버가 준 도메인 오류 코드(api.md의 `code`). */
  code?: string;
  /** 추적용 요청 식별자(api.md의 `request_id`). */
  requestId?: string;
  cause?: unknown;
}

export class LedgerApiError extends Error {
  readonly kind: LedgerErrorKind;
  readonly status: number | undefined;
  readonly code: string | undefined;
  readonly requestId: string | undefined;

  constructor(options: LedgerApiErrorOptions) {
    super(options.message, options.cause == null ? undefined : { cause: options.cause });
    this.name = "LedgerApiError";
    this.kind = options.kind;
    this.status = options.status;
    this.code = options.code;
    this.requestId = options.requestId;
  }
}

export function isCanceled(error: unknown): boolean {
  return error instanceof LedgerApiError && error.kind === "canceled";
}

/**
 * 사용자에게 보여줄 문구.
 *
 * 개인정보나 토큰이 섞일 수 있는 서버 원문을 그대로 노출하지 않는다.
 * 추적이 필요한 `request_id`만 덧붙인다.
 */
export function describeForUser(error: unknown): string {
  if (!(error instanceof LedgerApiError)) {
    return "알 수 없는 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.";
  }

  const base = messageForCode(error.code) ?? messageFor(error.kind);
  return error.requestId == null ? base : `${base} (요청 번호 ${error.requestId})`;
}

/**
 * 서버가 코드로 구분해 준 사유는 그대로 안내한다.
 * 코드가 없으면 상태 코드에서 유추한 일반 문구로 떨어진다.
 */
function messageForCode(code: string | undefined): string | null {
  switch (code) {
    case "COMPLEX_HAS_UNITS":
      return "이 단지에 등록된 세대가 남아 있어 삭제할 수 없습니다. 세대를 먼저 정리해 주세요.";
    case "PRIVACY_CONSENT_REQUIRED":
      return "개인정보 활용 동의가 없어 저장할 수 없습니다.";
    default:
      return null;
  }
}

function messageFor(kind: LedgerErrorKind): string {
  switch (kind) {
    case "offline":
      return "네트워크에 연결하지 못했습니다. 변경 내용은 브라우저에 보관됩니다.";
    case "canceled":
      return "요청이 취소되었습니다.";
    case "unauthorized":
      return "로그인이 필요합니다. 다시 로그인한 뒤 시도해 주세요.";
    case "forbidden":
      return "이 작업을 수행할 권한이 없습니다.";
    case "notFound":
      return "대상을 찾지 못했습니다. 다른 사용자가 삭제했을 수 있습니다.";
    case "conflict":
      return "다른 사용자가 먼저 저장했습니다. 최신 내용을 불러온 뒤 다시 시도해 주세요.";
    case "validation":
      return "입력값을 확인해 주세요.";
    case "server":
      return "서버에서 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.";
    case "contract":
      return "서버 응답 형식이 예상과 다릅니다. 배포 버전을 확인해 주세요.";
  }
}

/** HTTP 상태 코드를 오류 종류로. */
export function kindFromStatus(status: number): LedgerErrorKind {
  if (status === 401) return "unauthorized";
  if (status === 403) return "forbidden";
  if (status === 404) return "notFound";
  if (status === 409) return "conflict";
  if (status === 400 || status === 422) return "validation";
  if (status >= 500) return "server";
  return "server";
}
