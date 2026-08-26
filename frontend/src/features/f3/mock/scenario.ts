/**
 * 가짜 실행이 단계마다 내놓는 응답 본문.
 *
 * 전송(지연·취소·저장소)과 분리한 순수 모듈이다. 설정도 시계도 읽지 않고 경과 시간만 받는다.
 * 그래야 브라우저 없이 단계 전환을 테스트할 수 있고, mock이 계약에서 어긋나는지 화면을 띄우기
 * 전에 잡을 수 있다.
 *
 * 여기서 만드는 것은 서버가 보낼 법한 **원시 JSON**이다. 화면 모델이 아니다. 호출부가 실제
 * decoder에 통과시켜야 mock도 계약 검증을 함께 받는다.
 */

import type { AnchorType } from "../model/dto.ts";
import type { CandidateSummary } from "../api/transport.ts";

/**
 * 단계 전환 시각(ms).
 *
 * 실제 실행은 모델 호출 때문에 이보다 오래 걸린다. 여기서는 사람이 각 단계를 눈으로 확인할
 * 만큼만 벌려 둔다. 훅의 polling 간격(1→2→4초)과 맞물려 모든 단계가 최소 한 번은 그려진다.
 */
export const STAGES: readonly { at: number; status: string }[] = [
  { at: 0, status: "QUEUED" },
  { at: 1_200, status: "RUNNING" },
  { at: 2_800, status: "ANCHOR_READY" },
  { at: 4_600, status: "CANDIDATES_READY" },
  { at: 6_400, status: "CANDIDATE_CARDS_READY" },
  { at: 8_200, status: "JUDGING" },
  { at: 10_500, status: "COMPLETED" },
];

/** 서버가 카드화하는 상위 후보 수. 나머지는 등급 없이 목록에만 남는다. */
export const CARD_LIMIT = 15;
/** 페이지네이션이 실제로 보이도록 기본 페이지(20)보다 많게 만든다. */
export const TOTAL_CANDIDATES = 23;

const COMPLETED_AT = 10_500;
const STARTED_AT = 1_200;

const COMPLEX_NAMES = [
  "래미안 원베일리",
  "아크로리버파크",
  "반포자이",
  "헬리오시티",
  "파크리오",
] as const;

export interface MockRun {
  runId: number;
  anchorType: AnchorType;
  anchorId: number;
  createdAt: number;
}

export interface PageRequest {
  limit: number;
  offset: number;
}

/** 경과 시간으로 현재 단계를 정한다. */
export function statusAt(elapsedMs: number): string {
  let current = STAGES[0]?.status ?? "QUEUED";
  for (const stage of STAGES) {
    if (elapsedMs >= stage.at) current = stage.status;
  }
  return current;
}

function stageIndexOf(status: string): number {
  return STAGES.findIndex((stage) => stage.status === status);
}

export function reached(status: string, target: string): boolean {
  return stageIndexOf(status) >= stageIndexOf(target);
}

function isoAt(epochMs: number): string {
  return new Date(epochMs).toISOString();
}

/** 등급은 순위대로 나눈다. 카드화 밖 후보는 판정이 없다. */
export function gradeFor(rank: number): string | null {
  if (rank > CARD_LIMIT) return null;
  if (rank <= 4) return "STRONG";
  if (rank <= 10) return "WEAK";
  return "REJECTED";
}

export function candidateEntry(
  run: MockRun,
  index: number,
  judged: boolean,
): Record<string, unknown> {
  const rank = index + 1;
  const candidateId = run.runId * 100 + rank;
  const grade = judged ? gradeFor(rank) : null;
  const isListingAnchor = run.anchorType === "LISTING";

  const base: Record<string, unknown> = {
    candidate_id: candidateId,
    rank,
    selected_for_cards: rank <= CARD_LIMIT,
    sql_score: (1 - index * 0.031).toFixed(4),
    price_amount: 2_500_000_000 + ((index * 7) % 12) * 100_000_000,
    monthly_amount: null,
    received_at: `2026-0${(index % 8) + 1}-1${index % 10}`,
    match_grade: grade,
    evaluation_basis: null,
    primary_obstacle: null,
    possible_concession: null,
    recommended_action: null,
    exclusion_reason: null,
    evidence: [],
  };

  if (grade == null) return base;

  const subject = isListingAnchor ? "손님" : "매물";
  return {
    ...base,
    evaluation_basis:
      grade === "STRONG"
        ? "예산과 희망 평형이 모두 맞고 최근 상담에서 즉시 검토 의사를 밝혔다."
        : grade === "WEAK"
          ? "가격은 맞지만 이사 시점이 두 달 이상 벌어져 있다."
          : "최대 예산이 기준 가격을 넘어 현재 조건으로는 성사되지 않는다.",
    primary_obstacle: grade === "STRONG" ? null : grade === "WEAK" ? "입주 시점 차이" : "예산 초과",
    possible_concession:
      grade === "REJECTED" ? null : "계약일을 2~3주 조정하면 검토 가능하다고 했다.",
    recommended_action:
      grade === "REJECTED"
        ? null
        : { channel: "CALL", message: `${subject}에게 먼저 연락해 조건 조정 여지를 확인한다.` },
    exclusion_reason: grade === "REJECTED" ? "최대 예산이 기준 가격보다 낮다." : null,
    evidence: [
      {
        field_name: "price",
        evidence_type: "QUOTE",
        interaction_id: 40_000 + candidateId,
        quote_text: "예산은 최대 29억까지 생각하고 있습니다.",
        quote_start_offset: 0,
        quote_end_offset: 24,
        note: null,
        evidence_side: isListingAnchor ? "CANDIDATE" : "ANCHOR",
      },
    ],
  };
}

function anchorCardPayload(run: MockRun): Record<string, unknown> {
  const isListingAnchor = run.anchorType === "LISTING";
  return {
    position_analysis_id: run.runId * 10,
    negotiation_side: run.anchorType,
    target_label: isListingAnchor ? "래미안 원베일리 101동 203호" : `구입장 #${run.anchorId}`,
    generated_at: isoAt(run.createdAt + 2_800),
    analysis: {
      intent: { value: "SELL_INTENT", note: "가격 조정 여지를 먼저 물어왔다." },
      urgency: { value: "NORMAL" },
      contactability: { status: "GOOD", note: "최근 2주 내 통화가 이어졌다." },
      timing: { constraints: ["10월 이후 입주 희망"], hard_deadline: null },
      flexible: [{ description: "입주일 2~3주 조정" }],
      inflexible: [{ description: "28억 미만 불가" }],
    },
    evidence: [
      {
        field_name: "urgency",
        evidence_type: "QUOTE",
        interaction_id: 40_001,
        quote_text: "급하진 않은데 좋은 조건이면 바로 진행하고 싶어요.",
        quote_start_offset: 0,
        quote_end_offset: 27,
        note: null,
      },
    ],
  };
}

export function runPayload(run: MockRun, status: string): Record<string, unknown> {
  return {
    run_id: run.runId,
    run_group_id: "018f7c9e-0f2f-7c1e-9a3b-2f7c9e0f2f7c",
    status,
    anchor_type: run.anchorType,
    anchor_id: run.anchorId,
    input_data_version: 1,
    created_at: isoAt(run.createdAt),
  };
}

/** 중간 단계는 `completed_at`을 채우지 않는다. 완료에서만 채운다. */
function timestamps(run: MockRun, status: string): Record<string, unknown> {
  return {
    started_at: reached(status, "RUNNING") ? isoAt(run.createdAt + STARTED_AT) : null,
    completed_at: status === "COMPLETED" ? isoAt(run.createdAt + COMPLETED_AT) : null,
    failure_code: null,
    failure_message: null,
  };
}

export function statusPayload(run: MockRun, status: string): Record<string, unknown> {
  return { ...runPayload(run, status), ...timestamps(run, status) };
}

export function resultPayload(
  run: MockRun,
  status: string,
  page: PageRequest,
): Record<string, unknown> {
  const hasCandidates = reached(status, "CANDIDATES_READY");
  const judged = status === "COMPLETED";
  const all = hasCandidates
    ? Array.from({ length: TOTAL_CANDIDATES }, (_, index) => candidateEntry(run, index, judged))
    : [];

  return {
    ...runPayload(run, status),
    ...timestamps(run, status),
    // 앵커 카드가 저장된 뒤에만 공개한다. 그 전에는 완료를 가장하지 않는다.
    anchor_card: reached(status, "ANCHOR_READY") ? anchorCardPayload(run) : null,
    candidate_selection: {
      criteria: hasCandidates
        ? {
            candidate_side: run.anchorType === "LISTING" ? "REQUIREMENT" : "LISTING",
            price_kind: "SALE",
            price_amount: 2_880_000_000,
            price_floor_amount: 2_592_000_000,
            price_ceiling_amount: 3_168_000_000,
            anchor_pyeong: "33",
            demand_types: ["SALE"],
            active_statuses: ["ACTIVE"],
            as_of: "2026-08-26",
          }
        : null,
      total_count: all.length,
      carded_count: hasCandidates ? CARD_LIMIT : 0,
      remaining_count: hasCandidates ? Math.max(0, all.length - CARD_LIMIT) : 0,
    },
    candidates: all.slice(page.offset, page.offset + page.limit),
    candidates_total: all.length,
    limit: page.limit,
    offset: page.offset,
  };
}

export function summaryFor(requirementId: number): CandidateSummary {
  const seed = requirementId % 7;
  return {
    requirementId,
    demandType: "SALE",
    // 일부는 희망 단지가 없다. 단지를 가리지 않는 손님도 정상이며 화면이 그 사실을 그린다.
    desiredComplexNames: seed === 0 ? [] : [COMPLEX_NAMES[seed % COMPLEX_NAMES.length] as string],
    desiredPyeongs: seed % 3 === 0 ? [33] : [25, 33],
    maxBudgetAmount: 2_600_000_000 + seed * 100_000_000,
    budgetRawText: null,
  };
}
