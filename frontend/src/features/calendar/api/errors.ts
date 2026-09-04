/**
 * 캘린더 오류 문구.
 *
 * `ledger/api/errors.ts`와 같은 방침이다 — 분류는 `shared/api`가 소유하고, 여기서는 캘린더
 * 화면이 보여줄 문구만 정한다. 서버 원문은 그대로 노출하지 않는다.
 */

import { ApiError } from "../../../shared/api/errors.ts";
import type { ApiErrorKind } from "../../../shared/api/errors.ts";

export function describeForUser(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return "알 수 없는 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.";
  }
  const base = error.userMessage ?? messageFor(error.kind);
  return error.requestId == null ? base : `${base} (요청 번호 ${error.requestId})`;
}

function messageFor(kind: ApiErrorKind): string {
  switch (kind) {
    case "offline":
      return "네트워크에 연결하지 못했습니다.";
    case "canceled":
      return "요청이 취소되었습니다.";
    case "unauthorized":
      return "로그인이 필요합니다. 다시 로그인한 뒤 시도해 주세요.";
    case "forbidden":
      return "이 작업을 수행할 권한이 없습니다.";
    case "notFound":
      return "대상 일정을 찾지 못했습니다. 다른 사용자가 삭제했을 수 있습니다.";
    case "conflict":
      return "다른 사용자가 먼저 저장했습니다. 목록을 새로고침한 뒤 다시 시도해 주세요.";
    case "validation":
      return "입력값을 확인해 주세요.";
    case "server":
      return "서버에서 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.";
    case "contract":
      return "서버 응답 형식이 예상과 다릅니다. 배포 버전을 확인해 주세요.";
  }
}
