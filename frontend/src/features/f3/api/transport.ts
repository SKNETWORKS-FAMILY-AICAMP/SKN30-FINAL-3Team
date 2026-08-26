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

/**
 * 후보를 화면에 표시하기 위한 장부 요약.
 *
 * **임시 우회다.** 결과 응답이 `candidate_id`와 금액·접수일만 주고 사람이 식별할 제목을 주지
 * 않아, LISTING 앵커의 후보를 그리려면 장부를 따로 읽어야 한다. Backend가 후보 응답에
 * `desired_complex_names`와 `desired_pyeongs`를 실어주면 이 타입과 호출부를 제거한다.
 *
 * 인물은 읽지 않는다. 후보 목록은 부동산·조건 값만 보여주고, 문자 작성 시점에 F1이 최신
 * 연락처와 동의를 다시 조회한다.
 */
export interface CandidateSummary {
  requirementId: number;
  demandType: string;
  desiredComplexNames: string[];
  desiredPyeongs: number[];
  maxBudgetAmount: number | null;
  budgetRawText: string | null;
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
  /** 후보 제목용 장부 요약. 임시 우회이며 실패해도 판정 표시를 막지 않는다. */
  fetchCandidateSummary(requirementId: number, signal?: AbortSignal): Promise<CandidateSummary>;
}
