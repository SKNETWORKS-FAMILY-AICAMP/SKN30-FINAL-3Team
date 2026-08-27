/**
 * 장부 오류 문구.
 *
 * 오류의 **분류**는 `shared/api`가 소유하고, 여기서는 장부 화면이 보여줄 **문구**만 정한다.
 * 요구사항이 상태별로 다른 화면을 지정하기 때문이다.
 *   - 불러오기 실패는 입력을 건드리지 않고 재시도를 제공한다(F1-GR 로드 오류 화면).
 *   - 저장 충돌은 롤백하고 해당 셀을 표시한다(F1-GR-26).
 *   - 연결 단절은 브라우저에 보관하고 복구 시 재전송한다(F1-GR-35).
 *   - 권한 부족은 재시도할 대상이 아니다.
 *
 * 같은 분류라도 기능마다 사용자에게 할 말이 다르므로 문구를 공통 영역에 올리지 않는다.
 * 예를 들어 인증은 계정 존재 여부를 드러내지 않으려고 사유를 뭉뚱그린다.
 */

import { ApiError } from "../../../shared/api/index.ts";
import type { ApiErrorKind } from "../../../shared/api/index.ts";

/**
 * 사용자에게 보여줄 문구.
 *
 * 개인정보나 토큰이 섞일 수 있는 서버 원문을 그대로 노출하지 않는다.
 * 추적이 필요한 `request_id`만 덧붙인다.
 */
export function describeForUser(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return "알 수 없는 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.";
  }

  const base = messageForCode(error.code) ?? localValidationMessage(error) ?? messageFor(error.kind);
  return error.requestId == null ? base : `${base} (요청 번호 ${error.requestId})`;
}

/**
 * 화면이 직접 만든 저장 전 검증 오류.
 *
 * 서버 원문은 개인정보나 토큰이 섞일 수 있어 감추지만, 이 문구는 화면 코드가 쓴 것이고
 * 무엇을 고쳐야 하는지 이미 알고 있다. 일반 문구로 덮으면 "입력값을 확인해 주세요"만 남아
 * 어느 칸을 봐야 하는지 알 수 없다.
 *
 * 응답에서 온 오류는 `status`를 갖는다. 그것으로 화면이 만든 오류와 구분한다.
 */
function localValidationMessage(error: ApiError): string | null {
  if (error.kind !== "validation" || error.status != null) return null;
  const message = error.message.trim();
  return message === "" ? null : message;
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

function messageFor(kind: ApiErrorKind): string {
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
