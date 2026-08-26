/**
 * F3 교차 판정 기능의 공개 진입점.
 *
 * 다른 기능과 화면은 이 파일이 내보내는 것만 쓴다. DTO, decoder, HTTP 경로와 mock은 내부
 * 구현이며 어떤 transport를 쓰는지도 밖에서 보이지 않는다.
 *
 * 실제로 밖에서 쓰는 것만 내보낸다. 쓸 사람이 없는 이름을 미리 열어 두면 그것도 계약이 되어
 * 내부를 고칠 때마다 딸려 온다. 필요해지면 그때 넓힌다.
 */

import { f3Transport } from "./api/f3Transport.ts";
import type { NotInterestedInput } from "./api/transport.ts";
import type { FeedbackDto } from "./model/dto.ts";

/** 관심없음 피드백. `target_id`는 `match_candidate_evaluation.id`이며 장부 ID가 아니다. */
export function sendNotInterested(
  input: NotInterestedInput,
  signal?: AbortSignal,
): Promise<FeedbackDto> {
  return f3Transport.sendNotInterested(input, signal);
}

export type { NotInterestedInput } from "./api/transport.ts";

export {
  DEFAULT_FEEDBACK_REASON,
  FEEDBACK_REASON_CHOICES,
  GRADE_ORDER,
  collapsedGrades,
  describePanelState,
  hiddenGrades,
} from "./model/viewModel.ts";
export type { CandidateView, GradeLabel, PanelState, ParentContext } from "./model/viewModel.ts";

export { resetCrossJudgmentCache, useCrossJudgment } from "./hooks/useCrossJudgment.ts";
export type { CrossJudgment, CrossJudgmentInput } from "./hooks/useCrossJudgment.ts";

export type { AnchorType, FeedbackField, FeedbackReason } from "./model/dto.ts";
