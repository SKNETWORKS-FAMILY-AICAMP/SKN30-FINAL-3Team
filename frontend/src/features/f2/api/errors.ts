/**
 * F2 오류 문구.
 *
 * HTTP 오류의 분류와 envelope 파싱은 `shared/api`가 소유하고, 음성 분석 화면에 보여줄 안전한
 * 문구는 F2가 소유한다(ADR-004). 서버 `message`는 개인정보나 Provider 세부 정보를 포함할 수
 * 있으므로 사용자에게 그대로 표시하지 않는다.
 */

import { ApiError, isCanceled } from "../../../shared/api/errors.ts";
import type { ApiErrorKind } from "../../../shared/api/errors.ts";

export function isF2Canceled(error: unknown): boolean {
  return isCanceled(error);
}

export function describeF2Error(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return "음성메모 분석을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.";
  }

  const base = messageForCode(error.code) ?? messageForKind(error.kind);
  return error.requestId == null ? base : `${base} (요청 번호 ${error.requestId})`;
}

function messageForCode(code: string | undefined): string | null {
  switch (code) {
    case "VALIDATION_FAILED":
      return "음성 파일과 입력 조건을 확인한 뒤 다시 분석해 주세요.";
    case "PRIVACY_CONSENT_REQUIRED":
      return "개인정보 주의 문구를 확인한 뒤 다시 분석해 주세요.";
    case "F2_PROCESSING_FAILED":
      return "음성메모를 처리하지 못했습니다. 원본 파일을 유지한 채 다시 분석할 수 있습니다.";
    case "F2_UNAVAILABLE":
      return "음성 분석 서비스를 현재 사용할 수 없습니다. 잠시 후 다시 분석해 주세요.";
    default:
      return null;
  }
}

function messageForKind(kind: ApiErrorKind): string {
  switch (kind) {
    case "offline":
      return "네트워크에 연결하지 못했습니다. 연결을 확인한 뒤 다시 분석해 주세요.";
    case "canceled":
      return "음성메모 분석이 취소되었습니다.";
    case "unauthorized":
      return "로그인 세션이 만료되었습니다. 다시 로그인한 뒤 분석해 주세요.";
    case "forbidden":
      return "분석 권한을 확인할 수 없습니다. 화면을 새로고침한 뒤 다시 시도해 주세요.";
    case "notFound":
      return "음성 분석 경로를 찾을 수 없습니다. 배포 상태를 확인해 주세요.";
    case "conflict":
      return "분석 요청 상태가 변경되었습니다. 다시 시도해 주세요.";
    case "validation":
      return "음성 파일과 입력 조건을 확인한 뒤 다시 분석해 주세요.";
    case "server":
      return "음성메모 분석 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.";
    case "contract":
      return "음성 분석 응답 형식이 예상과 다릅니다. 배포 상태를 확인해 주세요.";
  }
}
