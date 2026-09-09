/** Explicit synthetic saved reads. Reading never creates a mock execution. */
import { ApiError } from "../../../shared/api/index.ts";
import { resultPayload } from "../mock/scenario.ts";
import { decodeRunResult } from "../model/decode.ts";
import type { AnchorType } from "../model/dto.ts";
import type { ListQuery } from "./api.ts";
import type {
  JudgmentCandidate,
  JudgmentDetail,
  JudgmentPage,
  JudgmentTarget,
  TargetIdentity,
} from "./model.ts";
const timestamp = "2026-09-09T00:00:00Z";
function identity(type: AnchorType, id: number): TargetIdentity {
  return {
    anchor_type: type,
    anchor_id: id,
    property_unit_id: type === "LISTING" ? id : null,
    display_name: `${type === "LISTING" ? "합성 매물" : "합성 손님"} #${id}`,
    assignee_id: null,
    assignee_name: null,
    trade_type: "SALE",
    complex_name: "합성 단지",
    current_conditions: "매매 · 합성 조건",
  };
}
function detail(
  type: AnchorType,
  id: number,
  selected?: number,
  cursor?: string,
): JudgmentDetail {
  const run = decodeRunResult(
    resultPayload(
      {
        runId: id,
        anchorType: type,
        anchorId: id,
        createdAt: Date.parse(timestamp),
      },
      "COMPLETED",
      { limit: 100, offset: 0 },
    ),
  );
  const candidates: JudgmentCandidate[] = run.candidates.map((c) => ({
    ...c,
    current_eligibility: null,
    evidence: c.evidence.map((e) => ({
      ...e,
      evidence_side:
        e.evidence_side === "CANDIDATE"
          ? type === "LISTING"
            ? "REQUIREMENT"
            : "LISTING"
          : type,
    })),
    target: identity(
      type === "LISTING" ? "REQUIREMENT" : "LISTING",
      c.candidate_id,
    ),
    position_card: c.selected_for_cards ? run.anchor_card : null,
    recent_records: [],
  }));
  const offset = cursor ? Number(cursor) : 0;
  const resultId = type === "LISTING" ? id : id + 1_000_000;
  return {
    is_synthetic_fixture: false,
    anchor: identity(type, id),
    result_id: resultId,
    run_id: id,
    eligibility: "ELIGIBLE",
    eligibility_reason: null,
    content_availability: "AVAILABLE",
    freshness: "CURRENT",
    generation: "IDLE",
    generated_at: timestamp,
    meaningful_changed_at: timestamp,
    summary: {
      total_count: candidates.length,
      judged_count: 5,
      strong_count: 2,
      weak_count: 2,
      rejected_count: 1,
      unjudged_count: candidates.length - 5,
    },
    representative_candidates: candidates.slice(0, 3),
    current_result_id: resultId,
    candidates: candidates.slice(offset, offset + 20),
    selected_candidate:
      candidates.find((c) => c.candidate_id === selected) ??
      candidates[offset] ??
      null,
    next_cursor: offset + 20 < candidates.length ? String(offset + 20) : null,
    anchor_card: run.anchor_card,
  };
}
function abort(signal?: AbortSignal) {
  if (signal?.aborted)
    throw new ApiError({ kind: "canceled", message: "조회 취소" });
}
export const mockJudgmentApi = {
  async target(
    type: AnchorType,
    id: number,
    signal?: AbortSignal,
  ): Promise<JudgmentTarget> {
    abort(signal);
    return detail(type, id);
  },
  async detail(
    id: number,
    query: { candidate_id?: number; cursor?: string } = {},
    signal?: AbortSignal,
  ): Promise<JudgmentDetail> {
    abort(signal);
    return detail(
      id >= 1_000_000 ? "REQUIREMENT" : "LISTING",
      id % 1_000_000,
      query.candidate_id,
      query.cursor,
    );
  },
  async list(query: ListQuery, signal?: AbortSignal): Promise<JudgmentPage> {
    abort(signal);
    const all = [detail(query.anchor_type, 2), detail(query.anchor_type, 3)];
    const scoped = all.filter(
      (t) => !query.q || t.anchor.display_name.includes(query.q),
    );
    const filtered = query.filter === "NEEDS_ATTENTION" ? [] : scoped;
    return {
      assignees: [],
      items: filtered,
      counts: {
        HAS_MATCH: scoped.length,
        HAS_STRONG: scoped.length,
        HAS_UNJUDGED: scoped.length,
        NEEDS_ATTENTION: 0,
        ALL: scoped.length,
      },
      next_cursor: null,
      checked_at: timestamp,
      revision: "synthetic-1",
    };
  },
};
