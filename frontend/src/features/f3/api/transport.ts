/**
 * F3 데이터 출처 경계.
 *
 * 훅과 화면은 이 인터페이스만 알고 실제 HTTP인지 mock인지 모른다. 그래야 Worker가 꺼진
 * 환경에서도 완료 화면을 확인할 수 있고, 확인한 화면이 실서버로 바꿔도 같은 가정 위에서 돈다.
 */

import type { FeedbackDto, RunDto, RunResultDto, RunStatusDto } from "../model/dto.ts";
import type { AnchorType, FeedbackField, FeedbackReason } from "../model/dto.ts";

export interface RunAnchor {
  anchorType: AnchorType;
  anchorId: number;
}

export interface CandidatePage {
  limit?: number;
  offset?: number;
}

export interface NotInterestedInput {
  targetId: number;
  reason: FeedbackReason;
  fieldName?: FeedbackField;
}

export interface F3Transport {
  /** 실행을 적재하거나 같은 입력의 활성 실행 식별자를 받는다. 응답은 202다. */
  createRun(anchor: RunAnchor, signal?: AbortSignal): Promise<RunDto>;
  /** polling용 상태 조회. */
  getRunStatus(runId: number, signal?: AbortSignal): Promise<RunStatusDto>;
  /** 현재 저장된 안전 단계까지의 결과. */
  getRunResult(runId: number, page?: CandidatePage, signal?: AbortSignal): Promise<RunResultDto>;
  /** 관심없음 피드백. */
  sendNotInterested(input: NotInterestedInput, signal?: AbortSignal): Promise<FeedbackDto>;
}
