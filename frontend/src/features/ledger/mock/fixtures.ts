/**
 * 모의 데이터.
 *
 * 화면 행이 아니라 **실제 계약과 같은 DTO**를 만든다.
 * 그래야 mock과 실제 API가 같은 경로(검증 → 매퍼 → 훅 → 화면)를 지나고,
 * 백엔드 연결이 transport 교체 한 번으로 끝난다.
 *
 * 값 표현도 계약과 같게 맞춘다. 금액은 원 단위 정수, 날짜는 ISO 8601, 식별자는 정수다.
 * 이름과 연락처는 전부 합성값이며 실제 번호와 겹치지 않도록 `010-0000-XXXX` 대역만 쓴다.
 */

import type {
  ClientInteractionDto,
  ComplexSummaryDto,
  PartySummaryDto,
  PropertyListingDto,
  PropertyRequirementRowDto,
  PropertyUnitRowDto,
  UnitPartyRelationDto,
} from "../model/dto.ts";

const EOK = 100_000_000;
const MAN = 10_000;

export const MOCK_COMPLEXES: ComplexSummaryDto[] = [
  { id: 1, name: "래미안 원베일리", property_type: "APARTMENT", road_address: "서울 서초구 신반포로 275" },
  { id: 2, name: "아크로리버파크", property_type: "APARTMENT", road_address: "서울 서초구 신반포로 15길" },
  { id: 3, name: "반포자이", property_type: "APARTMENT", road_address: "서울 서초구 신반포로 270" },
  { id: 4, name: "래미안 퍼스티지", property_type: "APARTMENT", road_address: "서울 서초구 반포대로 275" },
];

/**
 * 담당자 이름 조회표.
 *
 * 계약에 사용자 목록 엔드포인트가 없어 응답에는 `assigned_user_id`만 온다.
 * 실제 API에서는 이름을 채울 수 없으므로 mock에서만 쓰는 보조 자료다.
 */
export const MOCK_USERS: Array<{ id: number; display_name: string }> = [
  { id: 1, display_name: "김이순" },
  { id: 2, display_name: "실장" },
  { id: 3, display_name: "박소장" },
];

const PERSON_NAMES = ["김가나", "이다라", "박마바", "최사아", "정자차", "강카타", "조파하", "윤가다"];
const ORIENTATIONS = ["SOUTH", "SOUTH_EAST", "SOUTH_WEST", "EAST"];
const LIFECYCLE = ["NORMAL", "NORMAL", "LISTED", "IN_PROGRESS"];
const BUYER_ALIASES = ["인천사모님", "414동 세입자", "30억이하 엄마", "김손님"];
const DEMAND_TYPES = ["BUY", "JEONSE", "MONTHLY_RENT", "SELL"];
const WORKFLOW_STAGES = ["매물 탐색", "조건 확인", "방문 일정"];

function pick<T>(list: readonly T[], index: number): T {
  const value = list[index % list.length];
  if (value === undefined) throw new Error("빈 목록에서 값을 고를 수 없습니다.");
  return value;
}

/** 가운데 자리를 0000으로 고정해 실제 번호와 겹치지 않게 한다. */
function phoneFor(index: number): string {
  return `010-0000-${String(index % 10000).padStart(4, "0")}`;
}

function isoDate(year: number, month: number, day: number): string {
  return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

function isoTimestamp(year: number, month: number, day: number): string {
  return `${isoDate(year, month, day)}T10:30:00+09:00`;
}

function contactsFor(index: number, consented: boolean) {
  return [
    {
      id: 10_000 + index,
      contact_method: "PHONE",
      contact_value: phoneFor(index),
      contact_label: null,
      is_primary: true,
      contactability_status: consented ? "CONSENTED" : "UNKNOWN",
    },
  ];
}

function partyFor(index: number, name: string): PartySummaryDto {
  const consented = index % 4 !== 3;
  return {
    id: 1_000 + index,
    party_type: "INDIVIDUAL",
    name,
    alternate_name: null,
    privacy_consent_at: consented ? isoTimestamp(2026, 7, (index % 27) + 1) : null,
    contacts: contactsFor(index, consented),
  };
}

/** 세대에 연결된 인물. 상세 응답에만 실린다. */
export function relationsFor(index: number): UnitPartyRelationDto[] {
  const relations: UnitPartyRelationDto[] = [];
  if (index % 11 !== 0) {
    const isCoOwned = index % 13 === 0;
    relations.push({
      role: "OWNER",
      role_index: 1,
      is_primary: true,
      is_co_owner: isCoOwned,
      valid_from: null,
      party: partyFor(index, pick(PERSON_NAMES, index)),
    });
    // 공동명의 세대. 그리드에서는 한 행으로 접어 표시한다(F1-GR-06).
    if (isCoOwned) {
      relations.push({
        role: "OWNER",
        role_index: 2,
        is_primary: false,
        is_co_owner: true,
        valid_from: null,
        party: partyFor(index + 5_000, pick(PERSON_NAMES, index + 4)),
      });
    }
  }
  if (index % 3 === 0) {
    relations.push({
      role: "TENANT",
      role_index: 1,
      is_primary: true,
      is_co_owner: false,
      valid_from: null,
      party: partyFor(index + 9_000, pick(PERSON_NAMES, index + 3)),
    });
  }
  return relations;
}

function listingFor(index: number, unitId: number): PropertyListingDto | null {
  // F1-GR-01: 매물이 아닌 세대도 행으로 존재한다. 매물 칸이 빈 행이 다수인 것이 정상이다.
  const kind = index % 4;
  if (kind === 0) return null;

  const isSale = kind === 1;
  const isJeonse = kind === 2;
  const isMonthly = kind === 3;

  return {
    id: 20_000 + index,
    unit_id: unitId,
    client_party_id: null,
    received_at: isoDate(2026, (index % 12) + 1, (index % 27) + 1),
    status: "RECEIVED",
    is_sale_available: isSale,
    sale_price: isSale ? (24 + (index % 9)) * EOK + (index % 10) * 1000 * MAN : null,
    is_jeonse_available: isJeonse,
    jeonse_deposit_amount: isJeonse ? (12 + (index % 8)) * EOK : null,
    is_monthly_rent_available: isMonthly,
    monthly_rent_deposit_amount: isMonthly ? (5 + (index % 5)) * EOK : null,
    monthly_rent_amount: isMonthly ? (240 + (index % 8) * 20) * MAN : null,
    price_raw_text: null,
    handover_condition: index % 3 === 0 ? "즉시" : "협의",
    assigned_user_id: pick(MOCK_USERS, index).id,
    memo: null,
    custom_fields: {},
    row_version: 1,
  };
}

export function createUnitRowDtos(count: number): PropertyUnitRowDto[] {
  if (!Number.isInteger(count) || count < 0) {
    throw new TypeError("createUnitRowDtos에는 0 이상의 행 수를 전달해야 합니다.");
  }

  return Array.from({ length: count }, (_unused, index): PropertyUnitRowDto => {
    const complex = pick(MOCK_COMPLEXES, index);
    const unitId = index + 1;
    /*
     * 동·호는 단지 안에서 유일해야 한다.
     * 실제 스키마의 uq_property_unit_location이 (단지, 동, 호) 중복을 막는다.
     */
    const ordinalInComplex = Math.floor(index / MOCK_COMPLEXES.length);

    return {
      id: unitId,
      complex,
      building_number: String(101 + Math.floor(ordinalInComplex / 84)),
      unit_number: String(201 + (ordinalInComplex % 84)),
      floor_number: `${2 + (index % 30)}/35`,
      orientation: pick(ORIENTATIONS, index),
      unit_type: "J1",
      pyeong: pick([24, 33, 42, 50], index),
      exclusive_area_sqm: null,
      supply_area_sqm: null,
      tenancy_status: null,
      current_deposit_amount: index % 3 === 0 ? (5 + (index % 5)) * EOK : null,
      current_monthly_rent_amount: index % 3 === 0 ? (240 + (index % 8) * 20) * MAN : null,
      loan_amount: index % 7 === 0 ? (2 + (index % 4)) * EOK : null,
      tenancy_expiry_date:
        index % 5 === 0 ? null : isoDate(2026 + (index % 2), (index % 12) + 1, (index % 27) + 1),
      tenancy_raw_text: null,
      is_expanded: index % 9 === 0,
      built_in_features: index % 5 === 0 ? "붙박이장" : null,
      facility_condition: index % 4 === 0 ? "확인 필요" : "일반",
      lifecycle_status: pick(LIFECYCLE, index),
      assigned_user_id: pick(MOCK_USERS, index).id,
      memo: index % 6 === 0 ? "일정 협의 필요" : null,
      custom_fields: { spec: `${3 + (index % 2)}실 2욕실`, brokerage_name: "" },
      last_contact_at: index % 7 === 0 ? null : isoTimestamp(2026, 8, (index % 12) + 1),
      row_version: 1,
      current_listing: listingFor(index, unitId),
    };
  });
}

export function createRequirementRowDtos(count: number): PropertyRequirementRowDto[] {
  if (!Number.isInteger(count) || count < 0) {
    throw new TypeError("createRequirementRowDtos에는 0 이상의 행 수를 전달해야 합니다.");
  }

  return Array.from({ length: count }, (_unused, index): PropertyRequirementRowDto => {
    const demandType = pick(DEMAND_TYPES, index);
    // F1-DM-11: 실사용 원문을 그대로 남긴다. 파싱값은 검색·매칭용으로 함께 둔다.
    const budgetRawText =
      demandType === "BUY"
        ? `${24 + (index % 8)}억선`
        : demandType === "JEONSE"
          ? `${10 + (index % 5)}억 이하`
          : "협의";

    return {
      id: index + 1,
      party: {
        ...partyFor(index + 70_000, pick(BUYER_ALIASES, index)),
        alternate_name: pick(BUYER_ALIASES, index),
      },
      received_at: isoDate(2026, 8, (index % 12) + 1),
      demand_type: demandType,
      // F1-DM-12: 희망 평형 복수 입력
      desired_pyeongs: index % 3 === 2 ? [25, 33] : [pick([25, 33, 42], index)],
      min_area_sqm: null,
      max_area_sqm: null,
      area_requirement_raw_text: index % 3 === 2 ? "25 33평" : null,
      min_budget_amount: null,
      max_budget_amount:
        demandType === "BUY"
          ? (24 + (index % 8)) * EOK
          : demandType === "JEONSE"
            ? (10 + (index % 5)) * EOK
            : null,
      budget_raw_text: budgetRawText,
      desired_move_in_date: isoDate(2026, (index % 5) + 8, 15),
      move_in_date_raw_text: index % 4 === 0 ? "1월중" : null,
      request_expiry_date: index % 4 === 0 ? isoDate(2026, (index % 5) + 8, 28) : null,
      current_tenancy_expiry_date: null,
      co_broker_party_id: null,
      classification: index % 2 === 0 ? "실거주" : "투자",
      workflow_stage: pick(WORKFLOW_STAGES, index),
      status: index % 5 === 0 ? "COMPLETED" : "ACTIVE",
      assigned_user_id: pick(MOCK_USERS, index).id,
      memo: index % 6 === 0 ? "후속 연락 필요" : null,
      custom_fields: { brokerage_name: index % 3 === 0 ? "대송" : "", background: "" },
      last_contact_at: isoTimestamp(2026, 8, (index % 12) + 1),
      row_version: 1,
    };
  });
}

export function interactionFor(index: number, unitId: number | null, requirementId: number | null): ClientInteractionDto {
  return {
    id: 30_000 + index,
    interaction_at: isoTimestamp(2026, 8, (index % 12) + 1),
    interaction_channel: "CALL",
    communication_direction: null,
    interaction_result: null,
    counterparty_role: null,
    counterparty_index: null,
    interaction_content:
      index % 4 === 0 ? "매물 의사 없음 · 6개월 후 재확인" : "상담 조건을 확인하고 후속 연락 예정",
    party_id: null,
    unit_id: unitId,
    listing_id: null,
    requirement_id: requirementId,
    source_type: "HUMAN",
    approval_status: "NOT_REQUIRED",
    created_by: null,
    created_at: isoTimestamp(2026, 8, (index % 12) + 1),
  };
}
