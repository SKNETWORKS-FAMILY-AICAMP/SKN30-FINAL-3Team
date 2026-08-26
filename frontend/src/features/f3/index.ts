/**
 * F3 교차 판정 기능의 공개 진입점.
 *
 * 다른 기능과 화면은 이 파일이 내보내는 것만 쓴다. DTO, decoder와 HTTP 경로는 내부 구현이다.
 */

export {
  createRun,
  getRunResult,
  getRunStatus,
  sendNotInterested,
  DEFAULT_CANDIDATE_LIMIT,
  MAX_CANDIDATE_LIMIT,
} from "./api/f3Api.ts";
export type { RunAnchor, NotInterestedInput, CandidateSummary } from "./api/f3Api.ts";

export {
  DEFAULT_FEEDBACK_REASON,
  FEEDBACK_REASON_CHOICES,
  GRADE_ORDER,
  collapsedGrades,
  describeCriteria,
  describePanelState,
  hiddenGrades,
  isTerminal,
  toCandidateView,
  toGradeLabel,
  toPanelState,
} from "./model/viewModel.ts";
export type {
  CandidateView,
  GradeLabel,
  PanelState,
  ParentContext,
} from "./model/viewModel.ts";

export { useCrossJudgment } from "./hooks/useCrossJudgment.ts";
export type { CrossJudgment, CrossJudgmentInput } from "./hooks/useCrossJudgment.ts";

export type { AnchorType, FeedbackReason, FeedbackField } from "./model/dto.ts";
