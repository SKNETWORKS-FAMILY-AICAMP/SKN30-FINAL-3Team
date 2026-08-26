/**
 * F3 교차 판정의 공개 HTTP DTO.
 *
 * 정본은 project-wiki `contracts/api.md`의 "F3 실행 계약"과 `backend/src/api/schemas/f3_runs.py`다.
 * 서버 필드 이름을 그대로 쓰고 화면 표현으로 바꾸지 않는다. 변환은 `viewModel.ts`가 맡는다.
 *
 * DB 테이블이나 Backend–AI 계약(`f3-ai.md`)의 타입을 여기에 복제하지 않는다. 그 계약은 이
 * HTTP 경로로 노출되지 않으며, 화면이 아는 것은 아래 공개 응답뿐이다.
 */

export type AnchorType = "LISTING" | "REQUIREMENT";

/**
 * 실행 상태.
 *
 * 서버가 고정 열거형으로 검증하지 않으므로(`api.md`) 문자열로 받는다. 아는 값만 화면 상태로
 * 옮기고 모르는 값은 진행 중으로 다룬다. 새 상태가 추가돼도 화면이 깨지지 않게 하기 위해서다.
 */
export type RunStatus = string;

/** 공개 실패 코드. allowlist 밖의 내부 실패는 서버가 `EXECUTION_FAILED`로 일반화한다. */
export type FailureCode = "LEASE_EXPIRED_MAX_ATTEMPTS" | "INPUT_SUPERSEDED" | "EXECUTION_FAILED";

export interface RunCreateRequestDto {
  anchor_type: AnchorType;
  anchor_id: number;
}

/** `POST /f3/runs`의 202 응답. 같은 입력의 활성 실행이면 기존 실행이 그대로 온다. */
export interface RunDto {
  run_id: number;
  run_group_id: string;
  status: RunStatus;
  anchor_type: AnchorType;
  anchor_id: number;
  /** 앵커가 된 매물 또는 구입장의 `row_version`. */
  input_data_version: number;
  created_at: string | null;
}

/** `GET /f3/runs/{run_id}`. polling용 상태 조회. */
export interface RunStatusDto {
  run_id: number;
  status: RunStatus;
  anchor_type: AnchorType;
  anchor_id: number;
  input_data_version: number;
  created_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  failure_code: string | null;
  failure_message: string | null;
}

/** 카드 또는 후보 판정의 공개 근거. */
export interface EvidenceDto {
  field_name: string | null;
  evidence_type: string;
  /** 원본 상담 로그. 단건 조회 경로가 아직 없어 현재 화면 이동에는 쓰지 않는다. */
  interaction_id: number | null;
  quote_text: string | null;
  quote_start_offset: number | null;
  quote_end_offset: number | null;
  note: string | null;
  /** 후보 판정 근거에만 있다. 카드 근거에서는 null이다. */
  evidence_side: string | null;
}

/**
 * 앵커 포지션 카드.
 *
 * `analysis`는 서버 schema가 `dict[str, Any]`라 구조를 계약하지 않는다. 통째로 보존하고
 * 화면이 필요한 항목만 방어적으로 읽는다.
 */
export interface AnchorCardDto {
  position_analysis_id: number;
  negotiation_side: string;
  target_label: string | null;
  generated_at: string | null;
  analysis: Record<string, unknown>;
  evidence: EvidenceDto[];
}

/**
 * 후보 1건.
 *
 * `candidate_id`는 앵커 반대편 장부 ID다. LISTING 앵커면 `property_requirement.id`,
 * REQUIREMENT 앵커면 `property_listing.id`다.
 *
 * `rank`를 정렬 키로 쓰지 않는다. 서버는 판정된 후보에 판정 순위를, 판정 전 후보에 SQL 순위를
 * 담고 페이지는 SQL 순서로 자른다. 다시 정렬하면 페이지 경계와 어긋난다. 배열 순서를 그대로
 * 신뢰하고 `rank`는 표시용으로만 쓴다.
 */
export interface CandidateDto {
  candidate_id: number;
  rank: number;
  /** false면 카드화·판정되지 않은 SQL 후보다. 판정 실패가 아니다. */
  selected_for_cards: boolean;
  sql_score: string | null;
  price_amount: number | null;
  monthly_amount: number | null;
  received_at: string | null;
  /**
   * 저장된 중개 판정의 식별자. 관심없음 피드백의 `target_id`다.
   *
   * 판정 전 후보와 카드화되지 않은 후보는 `null`이다. 장부 `candidate_id`로 대신하지 않는다.
   * 두 값은 다른 테이블의 식별자라 바꿔 넣으면 서버 검증은 통과하고 엉뚱한 판정 행에 저장된다.
   */
  judgment_id: number | null;
  match_grade: string | null;
  evaluation_basis: string | null;
  primary_obstacle: string | null;
  possible_concession: string | null;
  recommended_action: Record<string, unknown> | null;
  exclusion_reason: string | null;
  evidence: EvidenceDto[];
}

/** 실제 적용한 후보 조회 조건과 건수. 후보가 0건이어도 조건은 채워진다. */
export interface CandidateSelectionDto {
  criteria: Record<string, unknown> | null;
  total_count: number;
  carded_count: number;
  remaining_count: number;
}

/** `GET /f3/runs/{run_id}/result`. 진행 중이면 마지막으로 저장된 단계까지만 온다. */
export interface RunResultDto {
  run_id: number;
  status: RunStatus;
  anchor_type: AnchorType;
  anchor_id: number;
  input_data_version: number;
  created_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  failure_code: string | null;
  failure_message: string | null;
  anchor_card: AnchorCardDto | null;
  candidate_selection: CandidateSelectionDto;
  candidates: CandidateDto[];
  candidates_total: number;
  limit: number;
  offset: number;
}

export type FeedbackTarget = "POSITION_ANALYSIS" | "MATCH_CANDIDATE";

export type FeedbackReason =
  | "CONDITION_MISMATCH"
  | "ALREADY_CONTACTED"
  | "WRONG_JUDGMENT"
  | "OTHER";

/** 서버가 받는 필드명. 화면이 임의 문자열을 보내면 422다. */
export type FeedbackField =
  | "negotiation_intent"
  | "urgency"
  | "preferred_timing"
  | "flexible_conditions"
  | "inflexible_conditions"
  | "contactability_status"
  | "price"
  | "match_grade"
  | "evaluation_basis"
  | "primary_obstacle"
  | "possible_concession"
  | "recommended_action"
  | "exclusion_reason";

/**
 * 관심없음 피드백 요청.
 *
 * 서버가 `extra="forbid"`라 아래 네 필드 외에는 422다. 자유 메모, 원래 값, 정정값, 작성자와
 * 사무소 ID를 보내는 입력란이 없다. `feedback_type`도 서버가 `NOT_INTERESTED`로 고정한다.
 */
export interface FeedbackCreateRequestDto {
  target: FeedbackTarget;
  target_id: number;
  reason: FeedbackReason;
  field_name?: FeedbackField;
}

export interface FeedbackDto {
  feedback_id: number;
  target: FeedbackTarget;
  target_id: number;
  feedback_type: string;
  reason: FeedbackReason;
  field_name: string | null;
  created_at: string | null;
}
