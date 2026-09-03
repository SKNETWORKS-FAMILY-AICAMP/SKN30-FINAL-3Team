/**
 * Time Keeper 일정 조회의 서버 계약.
 *
 * 경로와 필드의 정본은 `backend/src/api/time_keeper.py`와 그 응답 스키마다. 장부의 DTO를
 * 가져다 쓰지 않는다. 두 기능이 같은 인물 요약을 쓰더라도 계약을 바꾸는 주체가 다르므로,
 * 한쪽 화면 사정으로 필드가 늘거나 줄 때 다른 쪽이 조용히 끌려가지 않게 한다.
 */

/**
 * 일정의 종류. **열거형으로 좁히지 않는다.**
 *
 * 서버 어휘는 앞으로 늘어난다. 계약과 일정 테이블이 생기면 계약 체결일, 계약금·중도금·잔금
 * 지급일, 임장일, 신고 기한이 같은 목록에 붙는다. 여기서 값을 고정하면 서버가 종류를 하나
 * 추가하는 순간 화면 전체가 계약 오류로 죽는다. 아는 값만 해석하고 모르는 값은 코드를 그대로
 * 보여준다 — 장부 코드표(`features/ledger/model/codes.ts`)와 같은 방침이다.
 */
export type AgendaCategory = string;

/** 현재 서버가 실제로 내보내는 종류. 화면 문구와 정렬 우선순위를 붙일 때만 쓴다. */
export const KNOWN_AGENDA_CATEGORIES = [
  "TENANCY_EXPIRY",
  "CLIENT_TENANCY_EXPIRY",
  "REQUEST_EXPIRY",
  "MOVE_IN",
  "LISTING_RECONTACT",
  "CLIENT_RECONTACT",
  "LISTING_REVALIDATION",
] as const;

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
  privacy_consent_at: string | null;
  contacts: PartyContactDto[];
}

export interface AgendaContactDto {
  /** 세대 관계 역할(`LANDLORD`·`TENANT`). 구입장 손님 본인은 null이다. */
  role: string | null;
  is_primary: boolean;
  party: PartySummaryDto;
}

export interface AgendaItemDto {
  category: AgendaCategory;
  /** ISO 날짜(YYYY-MM-DD). */
  due_date: string;
  /** 오늘이면 0, 이미 지났으면 음수. 기준일은 서버의 `as_of`다. */
  days_until_due: number;
  unit_id: number | null;
  listing_id: number | null;
  complex_name: string | null;
  building_number: string | null;
  unit_number: string | null;
  tenancy_status: string | null;
  requirement_id: number | null;
  demand_type: string | null;
  requirement_status: string | null;
  assigned_user_id: number | null;
  last_contact_at: string | null;
  contacts: AgendaContactDto[];
}

/** 창 안에 실제로 존재하는 종류와 건수. 0건인 종류는 서버가 아예 싣지 않는다. */
export interface AgendaCategorySummaryDto {
  category: AgendaCategory;
  /** 종류별 상한을 적용하기 전의 참값. `items`에 실린 건수보다 클 수 있다. */
  total: number;
}

export interface AgendaPageDto {
  items: AgendaItemDto[];
  categories: AgendaCategorySummaryDto[];
  total: number;
  limit: number;
  offset: number;
  as_of: string;
  within_days: number;
  overdue_days: number;
  per_category_limit: number;
}

/**
 * 브리핑 창이 한 번에 받아 올 건수.
 *
 * 실제로 분량을 정하는 것은 서버의 종류별 상한이다. 이 값은 그 상한을 적용한 결과가 잘리지
 * 않을 만큼만 넉넉하면 된다. 종류가 늘어도 한 종류가 지면을 독차지하지 않는다.
 */
export const BRIEFING_LIMIT = 50;
