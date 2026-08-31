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

// 오류 분류만 필요하므로 배럴이 아니라 순수 진입점을 쓴다(ADR-004). 배럴은 `import.meta.env`를
// 읽는 설정 모듈에 닿아 있고, 이 파일은 순수해야 Node 테스트에 넣을 수 있다.
import { ApiError } from "../../../shared/api/errors.ts";
import type { ApiErrorKind } from "../../../shared/api/errors.ts";

/**
 * row_version 없이 삭제를 시도한 경우. 두 장부가 같은 안내를 쓴다.
 *
 * 서버에 보내기 전 화면이 스스로 막는 자리라 사용자에게 그대로 보여준다.
 */
export const DELETE_WITHOUT_VERSION =
  "row_version이 없어 삭제할 수 없습니다. 목록을 새로 불러온 뒤 다시 시도해 주세요.";

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

  /*
   * `userMessage`는 화면 코드가 "이 문장은 사용자에게 보여도 된다"고 표시한 오류에만 있다.
   * 응답에서 만든 오류에는 붙지 않으므로 서버 원문이 이 경로로 새지 않는다.
   */
  const base = messageForCode(error.code) ?? error.userMessage ?? messageFor(error.kind);
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
