/**
 * 서버 전송 모델(DTO).
 *
 * 정본은 백엔드 `backend/src/api/schemas/property_ledger.py`와
 * project-wiki `contracts/api.md`의 "F1 장부 계약"이다. 이 파일은 그 계약을 옮긴 것이며
 * 임의로 바꾸지 않는다. 계약이 바뀌면 이 파일과 `decode.ts`를 함께 고친다.
 *
 * 계약에서 확인된 전제
 *
 * 1. 식별자는 정수다 (`id: int`).
 * 2. 금액은 원 단위 정수이고 억·만 표시 변환은 클라이언트가 한다.
 * 3. 목록 응답 봉투는 `items`, `total`, `limit`, `offset`이다.
 * 4. `brokerage_id`는 세션에서만 도출하며 주고받지 않는다.
 * 5. 매물장 목록 행에는 인물과 상담 로그가 **없다**. 상세와 별도 엔드포인트에서 가져온다.
 * 6. `limit`은 최대 500이다. 전량 로드는 불가능하며 페이징이 필수다.
 */

/** 오류 응답 본문. */
export interface ApiErrorDto {
  code: string;
  message: string;
  request_id: string;
}

/** 목록 응답 공통 봉투. `total`은 현재 필터 조건의 전체 건수다(F1-GR-04). */
export interface PageDto<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

/** 서버가 허용하는 한 페이지 최대 크기. `MAX_PAGE_SIZE`와 같다. */
export const MAX_PAGE_SIZE = 500;

/** 비어 있는 값을 뜻하는 예약값. 다른 값과 함께 선택할 수 있다(F1-GR-41). */
export const EMPTY_VALUE = "__EMPTY__";

export interface ComplexSummaryDto {
  id: number;
  name: string;
  property_type: string;
  road_address: string | null;
  /** 삭제 요청에 실어 보낼 낙관적 잠금 값. 세대 목록에 실려 오는 요약에는 없을 수 있다. */
  row_version: number;
}

export interface PropertyComplexCreateDto {
  name: string;
  property_type?: string;
  road_address: string | null;
  memo: string | null;
}

export interface PartyContactDto {
  id: number;
  contact_method: string;
  contact_value: string;
  contact_label: string | null;
  is_primary: boolean;
  contactability_status: string;
}

export interface PartySummaryDto {
  id: number;
  party_type: string;
  name: string;
  alternate_name: string | null;
  /** 개인정보 활용 동의 시각. null이면 미동의이며 구입장 저장이 거절된다(F1-DM-16). */
  privacy_consent_at: string | null;
  contacts: PartyContactDto[];
}

export interface UnitPartyRelationDto {
  role: string;
  role_index: number;
  is_primary: boolean;
  is_co_owner: boolean;
  valid_from: string | null;
  party: PartySummaryDto;
}

/** 매물 건. 세대에 매물이 없으면 null이다(F1-GR-01). */
export interface PropertyListingDto {
  id: number;
  unit_id: number;
  client_party_id: number | null;
  received_at: string | null;
  status: string;
  is_sale_available: boolean;
  sale_price: number | null;
  is_jeonse_available: boolean;
  jeonse_deposit_amount: number | null;
  is_monthly_rent_available: boolean;
  monthly_rent_deposit_amount: number | null;
  monthly_rent_amount: number | null;
  /** 사용자 입력 원문. 파싱값과 병존한다(F1-DM-11). */
  price_raw_text: string | null;
  handover_condition: string | null;
  assigned_user_id: number | null;
  memo: string | null;
  custom_fields: Record<string, unknown>;
  row_version: number;
}

/**
 * 매물장 그리드 한 행.
 *
 * 주의: 임대인·임차인·상담 로그는 이 응답에 없다.
 * 인물은 `GET /property-units/{id}`, 상담 로그는 `GET /client-interactions`로 따로 가져온다.
 */
export interface PropertyUnitRowDto {
  id: number;
  complex: ComplexSummaryDto;
  building_number: string | null;
  unit_number: string;
  floor_number: string | null;
  orientation: string | null;
  unit_type: string | null;
  pyeong: number | null;
  exclusive_area_sqm: number | null;
  supply_area_sqm: number | null;
  tenancy_status: string | null;
  current_deposit_amount: number | null;
  current_monthly_rent_amount: number | null;
  loan_amount: number | null;
  tenancy_expiry_date: string | null;
  tenancy_raw_text: string | null;
  is_expanded: boolean | null;
  built_in_features: string | null;
  facility_condition: string | null;
  lifecycle_status: string;
  assigned_user_id: number | null;
  memo: string | null;
  custom_fields: Record<string, unknown>;
  last_contact_at: string | null;
  row_version: number;
  current_listing: PropertyListingDto | null;
  /** 가장 최근 상담 로그 본문. 목록의 로그 열을 채운다. */
  latest_interaction_content: string | null;
}

export interface PropertyUnitDetailDto {
  unit: PropertyUnitRowDto;
  listings: PropertyListingDto[];
  parties: UnitPartyRelationDto[];
}

/** 구입장 한 행. 매물장과 달리 인물과 연락처가 목록 응답에 포함된다. */
export interface PropertyRequirementRowDto {
  id: number;
  party: PartySummaryDto;
  received_at: string | null;
  demand_type: string;
  desired_pyeongs: number[] | null;
  min_area_sqm: number | null;
  max_area_sqm: number | null;
  area_requirement_raw_text: string | null;
  min_budget_amount: number | null;
  max_budget_amount: number | null;
  budget_raw_text: string | null;
  desired_move_in_date: string | null;
  move_in_date_raw_text: string | null;
  request_expiry_date: string | null;
  current_tenancy_expiry_date: string | null;
  co_broker_party_id: number | null;
  classification: string | null;
  workflow_stage: string | null;
  status: string;
  assigned_user_id: number | null;
  memo: string | null;
  custom_fields: Record<string, unknown>;
  last_contact_at: string | null;
  row_version: number;
}

export interface RequirementComplexDto {
  complex: ComplexSummaryDto;
  preference_order: number | null;
}

export interface PropertyRequirementDetailDto {
  requirement: PropertyRequirementRowDto;
  desired_complexes: RequirementComplexDto[];
}

export interface ClientInteractionDto {
  id: number;
  interaction_at: string | null;
  interaction_channel: string;
  communication_direction: string | null;
  interaction_result: string | null;
  counterparty_role: string | null;
  counterparty_index: number | null;
  interaction_content: string;
  party_id: number | null;
  unit_id: number | null;
  listing_id: number | null;
  requirement_id: number | null;
  source_type: string;
  approval_status: string;
  created_by: number | null;
  created_at: string | null;
}

/**
 * 값 목록 필터(F1-GR-38) 응답.
 * 한 요청에 한 컬럼만 조회한다.
 */
export interface ColumnValuesDto {
  column: string;
  items: Array<{ value: string; count: number }>;
}

/* ------------------------------------------------------------------ */
/* 쓰기 요청 본문                                                       */
/* ------------------------------------------------------------------ */

export interface PropertyUnitCreateDto {
  complex_id: number;
  unit_number: string;
  building_number: string | null;
  floor_number: string | null;
  orientation: string | null;
  unit_type: string | null;
  pyeong: number | null;
  tenancy_status: string | null;
  current_deposit_amount: number | null;
  current_monthly_rent_amount: number | null;
  loan_amount: number | null;
  tenancy_expiry_date: string | null;
  tenancy_raw_text: string | null;
  is_expanded: boolean | null;
  built_in_features: string | null;
  facility_condition: string | null;
  assigned_user_id: number | null;
  memo: string | null;
  custom_fields: Record<string, unknown>;
}

/** 부분 수정. `row_version`이 필수이며 값이 다르면 409로 거절된다. */
export interface PropertyUnitUpdateDto extends Partial<Omit<PropertyUnitCreateDto, "complex_id">> {
  row_version: number;
  lifecycle_status?: string | null;
}

export interface PropertyListingCreateDto {
  received_at: string | null;
  is_sale_available: boolean;
  sale_price: number | null;
  is_jeonse_available: boolean;
  jeonse_deposit_amount: number | null;
  is_monthly_rent_available: boolean;
  monthly_rent_deposit_amount: number | null;
  monthly_rent_amount: number | null;
  price_raw_text: string | null;
  handover_condition: string | null;
  memo: string | null;
  custom_fields: Record<string, unknown>;
}

export interface PropertyListingUpdateDto extends Partial<PropertyListingCreateDto> {
  row_version: number;
}

export interface PropertyRequirementCreateDto {
  party_id: number;
  demand_type: string;
  received_at: string | null;
  desired_pyeongs: number[] | null;
  desired_complex_ids: number[];
  area_requirement_raw_text: string | null;
  min_budget_amount: number | null;
  max_budget_amount: number | null;
  budget_raw_text: string | null;
  desired_move_in_date: string | null;
  move_in_date_raw_text: string | null;
  request_expiry_date: string | null;
  classification: string | null;
  workflow_stage: string | null;
  status: string | null;
  assigned_user_id: number | null;
  memo: string | null;
  custom_fields: Record<string, unknown>;
}

export interface PropertyRequirementUpdateDto
  extends Partial<Omit<PropertyRequirementCreateDto, "party_id">> {
  row_version: number;
}

export interface ClientInteractionCreateDto {
  interaction_content: string;
  unit_id?: number | null;
  requirement_id?: number | null;
  party_id?: number | null;
}
