/**
 * 전송 DTO를 화면 모델로.
 *
 * 서버 필드를 화면 전체로 퍼뜨리지 않는다. 이름, 단위, null 의미와 한국어 표기를 여기서 한 번
 * 바꾸고, 패널은 그 결과만 그린다. 계약이 바뀌면 이 파일과 `decode.ts`만 따라 바뀐다.
 *
 * 금액과 평형 표기는 `shared/format`을 재사용한다. 억·만 변환 규칙이 화면마다 다르면 같은
 * 값이 매물장과 F3 패널에서 다르게 보인다.
 */

import { formatMoney, formatPyeongList } from "../../../shared/format/index.ts";
import type { CandidateSummary } from "../api/f3Api.ts";
import type {
  AnchorType,
  CandidateDto,
  FeedbackReason,
  RunResultDto,
  RunStatus,
} from "./dto.ts";

/**
 * 패널 화면 상태.
 *
 * 서로 독립된 `loading`, `success`, `error` boolean을 늘리지 않는다. 불가능한 조합을 타입에서
 * 지우면 "로딩이면서 실패"를 화면이 그릴 방법이 없어진다.
 */
export type PanelState =
  /** 저장 전이거나 매물 건이 없어 판정 대상이 아니다. */
  | "unavailable"
  /** 실행 생성 요청 중. */
  | "queueing"
  /** 접수 완료, Worker 대기. */
  | "queued"
  /** Worker가 선점했다. */
  | "running"
  /** 앵커 포지션 카드 저장 완료. */
  | "anchor-ready"
  /** 결정적 SQL 후보 스냅샷 완료. */
  | "candidates-ready"
  /** 후보 카드 생성·재사용 중. */
  | "carding"
  /** 전체 후보 중개 판정 중. */
  | "judging"
  /** 완료. 후보가 있다. */
  | "ready"
  /** 완료. 후보가 0건이다. */
  | "empty"
  /** 실행 중 입력이 바뀌어 결과를 반영하지 않았다. */
  | "superseded"
  /** 영구 실패이거나 HTTP 실패다. */
  | "failed"
  /** 장기 대기로 자동 polling을 멈췄다. 실패가 아니다. */
  | "paused";

/** 더 기다려도 상태가 바뀌지 않는 종료 상태. polling을 멈출 기준이다. */
const TERMINAL_STATUSES: readonly string[] = [
  "COMPLETED",
  "FAILED_TERMINAL",
  "SUPERSEDED",
  "CANCELLED",
];

export function isTerminal(status: RunStatus): boolean {
  return TERMINAL_STATUSES.includes(status);
}

/**
 * 실행 상태를 화면 상태로.
 *
 * 모르는 상태는 실패가 아니라 진행 중으로 다룬다. Backend가 상태를 하나 추가했을 때 화면이
 * 멀쩡한 실행을 실패로 보여주는 것보다, 진행 중으로 두고 다음 polling을 기다리는 편이 낫다.
 */
export function toPanelState(status: RunStatus, candidateCount: number): PanelState {
  switch (status) {
    case "QUEUED":
      return "queued";
    case "RUNNING":
      return "running";
    case "ANCHOR_READY":
      return "anchor-ready";
    case "CANDIDATES_READY":
      return "candidates-ready";
    case "CANDIDATE_CARDS_READY":
      return "carding";
    case "JUDGING":
      return "judging";
    case "COMPLETED":
      return candidateCount > 0 ? "ready" : "empty";
    case "SUPERSEDED":
      return "superseded";
    case "FAILED_TERMINAL":
      return "failed";
    default:
      return "running";
  }
}

/**
 * 진행 안내 문구.
 *
 * `QUEUED`·`RUNNING`은 Worker가 작업을 잡았는지를 나타내는 실행 제어 상태이고 `ANCHOR_READY`
 * 이후가 실제 업무 진행이다. 둘을 같은 진행률 축에 두지 않는다.
 */
export function describePanelState(state: PanelState): string {
  switch (state) {
    case "unavailable":
      return "현 매물 없음 · 판정 대상 아님";
    case "queueing":
      return "판정을 요청하는 중입니다.";
    case "queued":
      return "판정 대기 중입니다.";
    case "running":
      return "판정을 시작했습니다.";
    case "anchor-ready":
      return "기준 세대를 확인했습니다.";
    case "candidates-ready":
      return "조건에 맞는 후보를 찾았습니다.";
    case "carding":
      return "후보를 분석하는 중입니다.";
    case "judging":
      return "후보별 근거를 판정하는 중입니다.";
    case "ready":
      return "판정을 완료했습니다.";
    case "empty":
      return "조건에 맞는 후보가 없습니다.";
    case "superseded":
      return "판정 중 내용이 바뀌어 결과를 반영하지 않았습니다.";
    case "failed":
      return "판정에 실패했습니다.";
    case "paused":
      return "처리가 예상보다 길어지고 있습니다.";
  }
}

export type GradeLabel = "강함" | "약함" | "기각";

/** 등급 표시 순서. 패널의 그룹 순서와 같다. */
export const GRADE_ORDER: readonly GradeLabel[] = ["강함", "약함", "기각"];

/**
 * 판정 등급.
 *
 * 계약값은 `STRONG`·`WEAK`·`REJECTED`뿐이다. `HIGH`, `LOW`, `EXCLUDED`나 한국어 표기는 계약값이
 * 아니므로 받지 않는다. `null`은 판정 실패가 아니라 아직 판정하지 않았다는 뜻이다.
 */
export function toGradeLabel(matchGrade: string | null): GradeLabel | null {
  switch (matchGrade) {
    case "STRONG":
      return "강함";
    case "WEAK":
      return "약함";
    case "REJECTED":
      return "기각";
    default:
      return null;
  }
}

/**
 * 부모 화면별 기각 노출.
 *
 * 세대 상세는 기각을 숨기고 강함·약함만 보여준다. 손님 상세는 기각을 접어서 보여준다.
 * 같은 결과라도 중개사가 보는 맥락이 달라 요구사항이 노출을 다르게 정했다.
 */
export type ParentContext = "unit-detail" | "buyer-detail";

export function hiddenGrades(parent: ParentContext): GradeLabel[] {
  return parent === "unit-detail" ? ["기각"] : [];
}

export function collapsedGrades(parent: ParentContext): GradeLabel[] {
  return parent === "buyer-detail" ? ["기각"] : [];
}

/**
 * 관심없음 사유 선택지.
 *
 * 화면 문구와 계약값을 여기서 한 번 잇는다. 패널이 한국어 문자열을 그대로 보내면 서버가 422로
 * 거절하고, 매핑을 화면에 두면 사유가 늘어날 때 두 곳을 고쳐야 한다.
 *
 * 자유 메모는 없다. 서버가 `detail`을 받지 않으므로 입력란을 두면 사용자가 쓴 글이 조용히
 * 버려진다. 상담 원문과 이름이 흘러 들어갈 자리를 만들지 않으려는 계약이다.
 */
export const FEEDBACK_REASON_CHOICES: readonly { label: string; value: FeedbackReason }[] = [
  { label: "조건 안 맞음", value: "CONDITION_MISMATCH" },
  { label: "이미 연락함", value: "ALREADY_CONTACTED" },
  { label: "판정이 틀림", value: "WRONG_JUDGMENT" },
  { label: "기타", value: "OTHER" },
];

/** 사유 선택의 초기값. 목록 첫 항목을 인덱스로 꺼내면 `undefined` 가능성이 따라붙는다. */
export const DEFAULT_FEEDBACK_REASON: FeedbackReason = "CONDITION_MISMATCH";

/** 화면이 그리는 후보 한 건. */
export interface CandidateView {
  /** 앵커 반대편 장부 ID. React key와 요약 조회에 쓴다. */
  candidateId: number;
  /** 표시용 순위. 정렬에 쓰지 않는다. */
  rank: number;
  /** 판정된 후보만 등급을 갖는다. */
  grade: GradeLabel | null;
  /** false면 카드화되지 않은 SQL 후보다. 판정 실패와 구분해 표시한다. */
  judged: boolean;
  title: string;
  summary: string;
  budget: string;
  receivedAt: string;
  evaluationBasis: string | null;
  blocker: string | null;
  concession: string | null;
  exclusionReason: string | null;
  /**
   * 추천 행동 한 문장.
   *
   * `recommended_action`은 공개 schema가 고정되지 않은 객체다. 화면이 쓰는 `message`만 방어적으로
   * 읽고 나머지는 그리지 않는다. 등급에서 문구를 지어내지 않는다. 그것은 AI가 하지 않은 말을
   * AI 판정처럼 보여주는 것이다.
   */
  recommendedAction: string | null;
  /**
   * 관심없음 피드백 대상 ID.
   *
   * 결과 응답이 `match_candidate_evaluation.id`를 주지 않는 동안에는 항상 `null`이고 화면은
   * 버튼을 비활성화한다. `candidateId`로 대신하지 않는다.
   */
  feedbackTargetId: number | null;
}

/**
 * 후보 DTO를 화면 모델로.
 *
 * `summaries`는 임시 우회로 장부에서 따로 읽은 요약이다. 아직 도착하지 않았거나 조회에
 * 실패했으면 제목만 대체 문구가 되고 나머지 판정 내용은 그대로 보여준다. 제목 하나 때문에
 * 판정 결과를 감추지 않는다.
 */
export function toCandidateView(
  dto: CandidateDto,
  summary: CandidateSummary | undefined,
  anchorType: AnchorType,
): CandidateView {
  return {
    candidateId: dto.candidate_id,
    rank: dto.rank,
    grade: toGradeLabel(dto.match_grade),
    judged: dto.selected_for_cards && dto.match_grade != null,
    title: summary == null ? fallbackTitle(dto.candidate_id, anchorType) : summarizeTitle(summary),
    summary: summary == null ? "" : formatPyeongList(summary.desiredPyeongs),
    budget: formatMoney(dto.price_amount),
    receivedAt: dto.received_at ?? "",
    evaluationBasis: dto.evaluation_basis,
    blocker: dto.primary_obstacle,
    concession: dto.possible_concession,
    exclusionReason: dto.exclusion_reason,
    recommendedAction: readActionMessage(dto.recommended_action),
    feedbackTargetId: null,
  };
}

/**
 * 제목을 못 채웠을 때의 대체 표기.
 *
 * 후보는 앵커 반대편 장부의 행이다. 매물 앵커의 후보는 구입장이고 손님 앵커의 후보는 매물이다.
 * 한쪽 표기를 양쪽에 쓰면 손님 상세에서 매물을 "구입장"이라고 부르게 된다.
 */
function fallbackTitle(candidateId: number, anchorType: AnchorType): string {
  return anchorType === "LISTING" ? `구입장 #${candidateId}` : `매물 #${candidateId}`;
}

/** 희망 단지가 없는 손님은 단지를 가리지 않는다. 빈 제목 대신 그 사실을 보여준다. */
function summarizeTitle(summary: CandidateSummary): string {
  if (summary.desiredComplexNames.length === 0) return "희망 단지 없음";
  return summary.desiredComplexNames.join(" · ");
}

/** 공개 schema가 고정되지 않은 객체에서 화면이 쓰는 한 필드만 꺼낸다. */
function readActionMessage(action: Record<string, unknown> | null): string | null {
  if (action == null) return null;
  const message = action["message"];
  return typeof message === "string" && message.trim() !== "" ? message : null;
}

/** 후보 0건일 때 보여줄 실제 조회 조건. 왜 비었는지 설명하지 못하면 화면이 고장으로 읽힌다. */
export function describeCriteria(result: RunResultDto): string[] {
  const criteria = result.candidate_selection.criteria;
  if (criteria == null) return [];

  const lines: string[] = [];
  const ceiling = criteria["price_ceiling_amount"];
  const floor = criteria["price_floor_amount"];
  const demandTypes = criteria["demand_types"];
  const pyeong = criteria["anchor_pyeong"];

  if (typeof floor === "number") lines.push(`예산 하한 ${formatMoney(floor)} 이상`);
  if (typeof ceiling === "number") lines.push(`가격 상한 ${formatMoney(ceiling)} 이하`);
  if (Array.isArray(demandTypes) && demandTypes.length > 0) {
    lines.push(`거래 구분 ${demandTypes.join(", ")}`);
  }
  if (typeof pyeong === "string") lines.push(`기준 평형 ${pyeong}평`);
  return lines;
}
