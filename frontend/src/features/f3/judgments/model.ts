import {
  asArray,
  asBoolean,
  asNullableNumber,
  asNullableString,
  asNumber,
  asRecord,
  asString,
  DecodeError,
} from "../../../shared/decode/index.ts";
import { decodeAnchorCard, decodeCandidate } from "../model/decode.ts";
import type { AnchorCardDto, AnchorType, CandidateDto } from "../model/dto.ts";
export type ResultFilter =
  | "HAS_MATCH"
  | "HAS_STRONG"
  | "HAS_UNJUDGED"
  | "NEEDS_ATTENTION"
  | "ALL";
export const filters: { value: ResultFilter; label: string }[] = [
  { value: "HAS_MATCH", label: "연결 후보 있음" },
  { value: "HAS_STRONG", label: "최신 강함 있음" },
  { value: "HAS_UNJUDGED", label: "미판정 조건 후보 있음" },
  { value: "NEEDS_ATTENTION", label: "확인 필요" },
  { value: "ALL", label: "전체" },
];
export interface TargetIdentity {
  anchor_type: AnchorType;
  anchor_id: number;
  property_unit_id: number | null;
  display_name: string;
  assignee_id: number | null;
  assignee_name: string | null;
  trade_type: string | null;
  complex_name: string | null;
  current_conditions: string | null;
}
export interface RecentRecord {
  reason: string | null;
  record_id: number;
  record_type: string;
  created_at: string | null;
  scope: string;
  anchor_type: AnchorType;
  anchor_id: number;
  interaction_id: number | null;
}
export type CandidateEligibility =
  | "ELIGIBLE"
  | "INELIGIBLE"
  | "INSUFFICIENT_INPUT";

export interface JudgmentCandidate extends CandidateDto {
  /** 현재 조건의 적격성은 저장된 판정 등급과 별개다. 구 API의 누락은 null로 보존한다. */
  current_eligibility: CandidateEligibility | null;
  target: TargetIdentity;
  position_card: AnchorCardDto | null;
  recent_records: RecentRecord[];
}
export interface JudgmentSummary {
  total_count: number;
  judged_count: number;
  strong_count: number;
  weak_count: number;
  rejected_count: number;
  unjudged_count: number;
}
export interface JudgmentTarget {
  is_synthetic_fixture: boolean;
  anchor: TargetIdentity;
  result_id: number | null;
  run_id: number | null;
  eligibility: string;
  eligibility_reason: string | null;
  content_availability: string;
  freshness: string;
  generation: string;
  generated_at: string | null;
  meaningful_changed_at: string | null;
  summary: JudgmentSummary | null;
  representative_candidates: JudgmentCandidate[];
}
export interface JudgmentPage {
  assignees: { id: number; display_name: string }[];
  items: JudgmentTarget[];
  counts: Record<ResultFilter, number>;
  next_cursor: string | null;
  checked_at: string;
  revision: string;
}
export interface JudgmentDetail extends JudgmentTarget {
  current_result_id: number | null;
  candidates: JudgmentCandidate[];
  selected_candidate: JudgmentCandidate | null;
  next_cursor: string | null;
  anchor_card: AnchorCardDto | null;
}
export function anchorType(value: unknown, path = "anchor_type"): AnchorType {
  if (value !== "LISTING" && value !== "REQUIREMENT")
    throw new DecodeError(path, "알 수 없는 대상 종류");
  return value;
}
export function decodeIdentity(value: unknown): TargetIdentity {
  const r = asRecord(value, "target");
  return {
    anchor_type: anchorType(r.anchor_type),
    anchor_id: asNumber(r.anchor_id, "anchor_id"),
    property_unit_id: asNullableNumber(r.property_unit_id, "property_unit_id"),
    display_name: asString(r.display_name, "display_name"),
    assignee_id: asNullableNumber(r.assignee_id, "assignee_id"),
    assignee_name: asNullableString(r.assignee_name, "assignee_name"),
    trade_type: asNullableString(r.trade_type, "trade_type"),
    complex_name: asNullableString(r.complex_name, "complex_name"),
    current_conditions: asNullableString(
      r.current_conditions,
      "current_conditions",
    ),
  };
}
function decodeRecord(value: unknown): RecentRecord {
  const r = asRecord(value, "record");
  return {
    reason: asNullableString(r.reason, "reason"),
    record_id: asNumber(r.record_id, "record_id"),
    record_type: asString(r.record_type, "record_type"),
    created_at: asNullableString(r.created_at, "created_at"),
    scope: asString(r.scope, "scope"),
    anchor_type: anchorType(r.anchor_type),
    anchor_id: asNumber(r.anchor_id, "anchor_id"),
    interaction_id: asNullableNumber(r.interaction_id, "interaction_id"),
  };
}
function decodeCandidateEligibility(value: unknown): CandidateEligibility | null {
  if (value === undefined || value === null) return null;
  if (
    value === "ELIGIBLE" ||
    value === "INELIGIBLE" ||
    value === "INSUFFICIENT_INPUT"
  ) return value;
  throw new DecodeError("current_eligibility", "알 수 없는 후보 현재 적격성");
}

export function candidateEligibilityLabel(
  value: CandidateEligibility | null,
): string | null {
  if (value === "INELIGIBLE") return "현재 분석 대상 아님";
  if (value === "INSUFFICIENT_INPUT") return "현재 거래 조건 확인 필요";
  return null;
}

export function decodeJudgmentCandidate(value: unknown): JudgmentCandidate {
  const r = asRecord(value, "candidate");
  return {
    ...decodeCandidate(r),
    current_eligibility: decodeCandidateEligibility(r.current_eligibility),
    target: decodeIdentity(r.target),
    position_card:
      r.position_card == null ? null : decodeAnchorCard(r.position_card),
    recent_records: asArray(r.recent_records, "recent_records").map(
      decodeRecord,
    ),
  };
}
export function decodeTarget(value: unknown): JudgmentTarget {
  const r = asRecord(value, "target");
  let summary: JudgmentSummary | null = null;
  if (r.summary != null) {
    const s = asRecord(r.summary, "summary");
    summary = {
      total_count: asNumber(s.total_count, "total_count"),
      judged_count: asNumber(s.judged_count, "judged_count"),
      strong_count: asNumber(s.strong_count, "strong_count"),
      weak_count: asNumber(s.weak_count, "weak_count"),
      rejected_count: asNumber(s.rejected_count, "rejected_count"),
      unjudged_count: asNumber(s.unjudged_count, "unjudged_count"),
    };
  }
  return {
    is_synthetic_fixture:
      r.is_synthetic_fixture === undefined
        ? false
        : asBoolean(r.is_synthetic_fixture, "is_synthetic_fixture"),
    anchor: decodeIdentity(r.anchor),
    result_id: asNullableNumber(r.result_id, "result_id"),
    run_id: asNullableNumber(r.run_id, "run_id"),
    eligibility: asString(r.eligibility, "eligibility"),
    eligibility_reason: asNullableString(
      r.eligibility_reason,
      "eligibility_reason",
    ),
    content_availability: asString(
      r.content_availability,
      "content_availability",
    ),
    freshness: asString(r.freshness, "freshness"),
    generation: asString(r.generation, "generation"),
    generated_at: asNullableString(r.generated_at, "generated_at"),
    meaningful_changed_at: asNullableString(
      r.meaningful_changed_at,
      "meaningful_changed_at",
    ),
    summary,
    representative_candidates: asArray(
      r.representative_candidates,
      "representative_candidates",
    ).map(decodeJudgmentCandidate),
  };
}
export function decodePage(value: unknown): JudgmentPage {
  const r = asRecord(value, "page");
  const c = asRecord(r.counts, "counts");
  return {
    assignees: asArray(r.assignees, "assignees").map((value) => {
      const a = asRecord(value, "assignee");
      return {
        id: asNumber(a.id, "id"),
        display_name: asString(a.display_name, "display_name"),
      };
    }),
    items: asArray(r.items, "items").map(decodeTarget),
    counts: {
      HAS_MATCH: asNumber(c.HAS_MATCH, "HAS_MATCH"),
      HAS_STRONG: asNumber(c.HAS_STRONG, "HAS_STRONG"),
      HAS_UNJUDGED: asNumber(c.HAS_UNJUDGED, "HAS_UNJUDGED"),
      NEEDS_ATTENTION: asNumber(c.NEEDS_ATTENTION, "NEEDS_ATTENTION"),
      ALL: asNumber(c.ALL, "ALL"),
    },
    next_cursor: asNullableString(r.next_cursor, "next_cursor"),
    checked_at: asString(r.checked_at, "checked_at"),
    revision: asString(r.revision, "revision"),
  };
}
export function decodeDetail(value: unknown): JudgmentDetail {
  const r = asRecord(value, "detail");
  return {
    ...decodeTarget(r),
    current_result_id: asNullableNumber(
      r.current_result_id,
      "current_result_id",
    ),
    candidates: asArray(r.candidates, "candidates").map(
      decodeJudgmentCandidate,
    ),
    selected_candidate:
      r.selected_candidate == null
        ? null
        : decodeJudgmentCandidate(r.selected_candidate),
    next_cursor: asNullableString(r.next_cursor, "next_cursor"),
    anchor_card: r.anchor_card == null ? null : decodeAnchorCard(r.anchor_card),
  };
}
export function gradeLabel(grade: string | null): string {
  return (
    { STRONG: "강함", WEAK: "약함", REJECTED: "기각", REJECT: "기각" }[
      grade ?? ""
    ] ?? (grade == null ? "AI 미판정" : grade)
  );
}
export function dateLabel(value: string | null): string {
  if (!value) return "분석 전";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "시각 미확인"
    : new Intl.DateTimeFormat("ko-KR", {
        dateStyle: "short",
        timeStyle: "short",
      }).format(date);
}
