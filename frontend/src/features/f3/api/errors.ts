/**
 * F3 오류 문구.
 *
 * 오류의 **분류**는 `shared/api`가 소유하고, 여기서는 F3 화면이 보여줄 **문구**만 정한다.
 * ADR-004가 "오류는 분류만 공유하고 사용자 문구는 각 기능이 소유한다"로 정한 경계다.
 *
 * 장부 문구를 가져다 쓰지 않는다. 같은 분류라도 두 화면이 사용자에게 할 말이 다르기 때문이다.
 *   - 404: 장부는 "다른 사용자가 삭제했을 수 있습니다"라고 안내한다. 판정은 사용자가 지우는
 *     대상이 아니고, 계약상 다른 사무소 소유일 때도 404다. 다음 행동은 결과를 다시 부르는 것이다.
 *   - 오프라인: 장부는 변경을 브라우저에 보관하고 복구 시 재전송한다(F1-GR-35). 피드백에는 그
 *     보관 큐가 없다. 지키지 못할 약속을 하지 않는다.
 */

// 오류 분류만 필요하므로 배럴(`shared/api`)이 아니라 순수 진입점을 쓴다(ADR-004). 배럴은
// `httpClient`를 함께 내보내고 그쪽이 `import.meta.env`를 읽는 설정 모듈에 의존한다. 문구 변환은
// 순수 함수라 브라우저 번들러 없이 테스트할 수 있어야 한다.
import { ApiError } from "../../../shared/api/errors.ts";
import type { ApiErrorKind } from "../../../shared/api/errors.ts";

/**
 * 관심없음 피드백 실패를 사용자 문구로.
 *
 * 개인정보나 토큰이 섞일 수 있는 서버 원문을 그대로 노출하지 않는다. 추적이 필요한
 * `request_id`만 덧붙인다.
 */
export function describeFeedbackError(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return "알 수 없는 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.";
  }
  const base = messageFor(error.kind);
  return error.requestId == null ? base : `${base} (요청 번호 ${error.requestId})`;
}

function messageFor(kind: ApiErrorKind): string {
  switch (kind) {
    case "offline":
      return "네트워크에 연결하지 못했습니다. 연결된 뒤 다시 시도해 주세요.";
    case "canceled":
      return "요청이 취소되었습니다.";
    case "unauthorized":
      return "로그인이 필요합니다. 다시 로그인한 뒤 시도해 주세요.";
    case "forbidden":
      return "이 작업을 수행할 권한이 없습니다.";
    case "notFound":
      return "이 판정을 더 이상 찾을 수 없습니다. 결과를 새로 불러온 뒤 다시 시도해 주세요.";
    case "conflict":
      return "이미 처리된 피드백입니다. 결과를 새로 불러와 확인해 주세요.";
    case "validation":
      return "피드백 사유를 확인해 주세요.";
    case "server":
      return "서버에서 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.";
    case "contract":
      return "서버 응답 형식이 예상과 다릅니다. 배포 버전을 확인해 주세요.";
  }
}
