/**
 * F3 응답 런타임 검증.
 *
 * HTTP 200과 계약 준수는 별개다. 필수 필드가 없거나 형태가 다르면 정상 결과로 그리지 않고
 * 계약 오류로 올려보낸다. 배포 불일치를 조용히 삼키면 화면이 빈 판정을 사실처럼 보여준다.
 *
 * 반대로 **서버가 계약상 열어둔 값은 좁히지 않는다.** `status`와 `failure_code`는 서버가 고정
 * 열거형으로 검증하지 않으므로 문자열로 받고, 아는 값만 화면에서 해석한다. 여기서 열거형으로
 * 막으면 Backend가 상태를 하나 추가할 때 화면 전체가 계약 오류로 죽는다.
 */

import {
  DecodeError,
  asArray,
  asBoolean,
  asJsonObject,
  asNullableNumber,
  asNullableString,
  asNumber,
  asRecord,
  asString,
} from "../../../shared/decode/index.ts";
import type {
  AnchorCardDto,
  AnchorType,
  CandidateDto,
  CandidateSelectionDto,
  EvidenceDto,
  FeedbackDto,
  FeedbackReason,
  FeedbackTarget,
  RunDto,
  RunResultDto,
  RunStatusDto,
} from "./dto.ts";

const ANCHOR_TYPES: readonly string[] = ["LISTING", "REQUIREMENT"];
const FEEDBACK_TARGETS: readonly string[] = ["POSITION_ANALYSIS", "MATCH_CANDIDATE"];
const FEEDBACK_REASONS: readonly string[] = [
  "CONDITION_MISMATCH",
  "ALREADY_CONTACTED",
  "WRONG_JUDGMENT",
  "OTHER",
];

function asAnchorType(value: unknown, path: string): AnchorType {
  const text = asString(value, path);
  if (!ANCHOR_TYPES.includes(text)) {
    throw new DecodeError(path, `앵커 종류가 계약에 없는 값입니다: ${text}`);
  }
  return text as AnchorType;
}

/** JSONB 후보. 서버가 `null`을 보낼 수 있어 빈 객체로 접지 않고 구분해 둔다. */
function asNullableJsonObject(value: unknown, path: string): Record<string, unknown> | null {
  if (value === null || value === undefined) return null;
  return asRecord(value, path);
}

function decodeEvidence(value: unknown, path: string): EvidenceDto {
  const item = asRecord(value, path);
  return {
    field_name: asNullableString(item["field_name"], `${path}.field_name`),
    evidence_type: asString(item["evidence_type"], `${path}.evidence_type`),
    interaction_id: asNullableNumber(item["interaction_id"], `${path}.interaction_id`),
    quote_text: asNullableString(item["quote_text"], `${path}.quote_text`),
    quote_start_offset: asNullableNumber(item["quote_start_offset"], `${path}.quote_start_offset`),
    quote_end_offset: asNullableNumber(item["quote_end_offset"], `${path}.quote_end_offset`),
    note: asNullableString(item["note"], `${path}.note`),
    evidence_side: asNullableString(item["evidence_side"], `${path}.evidence_side`),
  };
}

function decodeEvidenceList(value: unknown, path: string): EvidenceDto[] {
  if (value === null || value === undefined) return [];
  return asArray(value, path).map((item, index) => decodeEvidence(item, `${path}[${index}]`));
}

/** 실행 정보. 상태 조회와 결과 조회가 같은 필드를 싣는다. */
function decodeRunFields(item: Record<string, unknown>, path: string) {
  return {
    run_id: asNumber(item["run_id"], `${path}.run_id`),
    status: asString(item["status"], `${path}.status`),
    anchor_type: asAnchorType(item["anchor_type"], `${path}.anchor_type`),
    anchor_id: asNumber(item["anchor_id"], `${path}.anchor_id`),
    input_data_version: asNumber(item["input_data_version"], `${path}.input_data_version`),
    created_at: asNullableString(item["created_at"], `${path}.created_at`),
  };
}

function decodeFailureFields(item: Record<string, unknown>, path: string) {
  return {
    started_at: asNullableString(item["started_at"], `${path}.started_at`),
    completed_at: asNullableString(item["completed_at"], `${path}.completed_at`),
    failure_code: asNullableString(item["failure_code"], `${path}.failure_code`),
    failure_message: asNullableString(item["failure_message"], `${path}.failure_message`),
  };
}

export function decodeRun(value: unknown, path = "run"): RunDto {
  const item = asRecord(value, path);
  return {
    ...decodeRunFields(item, path),
    run_group_id: asString(item["run_group_id"], `${path}.run_group_id`),
  };
}

export function decodeRunStatus(value: unknown, path = "run"): RunStatusDto {
  const item = asRecord(value, path);
  return { ...decodeRunFields(item, path), ...decodeFailureFields(item, path) };
}

export function decodeAnchorCard(value: unknown, path = "anchor_card"): AnchorCardDto {
  const item = asRecord(value, path);
  return {
    position_analysis_id: asNumber(item["position_analysis_id"], `${path}.position_analysis_id`),
    negotiation_side: asString(item["negotiation_side"], `${path}.negotiation_side`),
    target_label: asNullableString(item["target_label"], `${path}.target_label`),
    generated_at: asNullableString(item["generated_at"], `${path}.generated_at`),
    // 구조를 계약하지 않은 공개 객체. 통째로 보존하고 화면이 필요한 항목만 읽는다.
    analysis: asJsonObject(item["analysis"], `${path}.analysis`),
    evidence: decodeEvidenceList(item["evidence"], `${path}.evidence`),
  };
}

export function decodeCandidate(value: unknown, path = "candidate"): CandidateDto {
  const item = asRecord(value, path);
  return {
    candidate_id: asNumber(item["candidate_id"], `${path}.candidate_id`),
    rank: asNumber(item["rank"], `${path}.rank`),
    selected_for_cards: asBoolean(item["selected_for_cards"], `${path}.selected_for_cards`),
    // NUMERIC 컬럼이라 서버가 문자열로 보낸다. 표시 전용이므로 숫자로 바꾸지 않는다.
    sql_score: asNullableString(item["sql_score"], `${path}.sql_score`),
    price_amount: asNullableNumber(item["price_amount"], `${path}.price_amount`),
    monthly_amount: asNullableNumber(item["monthly_amount"], `${path}.monthly_amount`),
    received_at: asNullableString(item["received_at"], `${path}.received_at`),
    match_grade: asNullableString(item["match_grade"], `${path}.match_grade`),
    evaluation_basis: asNullableString(item["evaluation_basis"], `${path}.evaluation_basis`),
    primary_obstacle: asNullableString(item["primary_obstacle"], `${path}.primary_obstacle`),
    possible_concession: asNullableString(
      item["possible_concession"],
      `${path}.possible_concession`,
    ),
    recommended_action: asNullableJsonObject(
      item["recommended_action"],
      `${path}.recommended_action`,
    ),
    exclusion_reason: asNullableString(item["exclusion_reason"], `${path}.exclusion_reason`),
    evidence: decodeEvidenceList(item["evidence"], `${path}.evidence`),
  };
}

function decodeCandidateSelection(value: unknown, path: string): CandidateSelectionDto {
  const item = asRecord(value, path);
  return {
    criteria: asNullableJsonObject(item["criteria"], `${path}.criteria`),
    total_count: asNumber(item["total_count"], `${path}.total_count`),
    carded_count: asNumber(item["carded_count"], `${path}.carded_count`),
    remaining_count: asNumber(item["remaining_count"], `${path}.remaining_count`),
  };
}

export function decodeRunResult(value: unknown, path = "response"): RunResultDto {
  const item = asRecord(value, path);
  const anchorCard = item["anchor_card"];
  return {
    ...decodeRunFields(item, path),
    ...decodeFailureFields(item, path),
    anchor_card:
      anchorCard === null || anchorCard === undefined
        ? null
        : decodeAnchorCard(anchorCard, `${path}.anchor_card`),
    candidate_selection: decodeCandidateSelection(
      item["candidate_selection"],
      `${path}.candidate_selection`,
    ),
    candidates: asArray(item["candidates"], `${path}.candidates`).map((entry, index) =>
      decodeCandidate(entry, `${path}.candidates[${index}]`),
    ),
    candidates_total: asNumber(item["candidates_total"], `${path}.candidates_total`),
    limit: asNumber(item["limit"], `${path}.limit`),
    offset: asNumber(item["offset"], `${path}.offset`),
  };
}

export function decodeFeedback(value: unknown, path = "feedback"): FeedbackDto {
  const item = asRecord(value, path);
  const target = asString(item["target"], `${path}.target`);
  if (!FEEDBACK_TARGETS.includes(target)) {
    throw new DecodeError(`${path}.target`, `피드백 대상이 계약에 없는 값입니다: ${target}`);
  }
  const reason = asString(item["reason"], `${path}.reason`);
  if (!FEEDBACK_REASONS.includes(reason)) {
    throw new DecodeError(`${path}.reason`, `피드백 사유가 계약에 없는 값입니다: ${reason}`);
  }
  return {
    feedback_id: asNumber(item["feedback_id"], `${path}.feedback_id`),
    target: target as FeedbackTarget,
    target_id: asNumber(item["target_id"], `${path}.target_id`),
    feedback_type: asString(item["feedback_type"], `${path}.feedback_type`),
    reason: reason as FeedbackReason,
    field_name: asNullableString(item["field_name"], `${path}.field_name`),
    created_at: asNullableString(item["created_at"], `${path}.created_at`),
  };
}
