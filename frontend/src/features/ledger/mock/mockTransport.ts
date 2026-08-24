/**
 * 백엔드 없이 화면을 완성하기 위한 메모리 transport.
 *
 * 실제 서버가 하는 일(필터·페이징·값 목록 집계·낙관적 잠금)을 같은 자리에서 흉내 낸다.
 * 화면이 "서버가 해 주는 일"에 의존하도록 만들어 두어야 진짜 API로 바꿔도 가정이 어긋나지 않는다.
 * 특히 `limit` 상한과 페이징을 그대로 재현해, 전량 로드를 전제한 코드가 생기지 않게 한다.
 */

import { APP_ENV } from "../../../config/env.ts";
import { LedgerApiError } from "../api/errors.ts";
import type { LedgerTransport, ListQuery } from "../api/transport.ts";
import { EMPTY_VALUE, MAX_PAGE_SIZE } from "../model/dto.ts";
import type {
  ClientInteractionDto,
  ColumnValuesDto,
  ComplexSummaryDto,
  PageDto,
  PropertyListingDto,
  PropertyRequirementRowDto,
  PropertyUnitDetailDto,
  PropertyUnitRowDto,
} from "../model/dto.ts";
import {
  MOCK_COMPLEXES,
  createRequirementRowDtos,
  createUnitRowDtos,
  interactionFor,
  relationsFor,
} from "./fixtures.ts";

interface MockState {
  complexes: ComplexSummaryDto[];
  units: PropertyUnitRowDto[];
  requirements: PropertyRequirementRowDto[];
  interactions: ClientInteractionDto[];
  nextId: number;
}

/** 실제 API를 쓰는 빌드에서도 이 모듈이 번들에 남을 수 있으므로 시드 생성을 지연시킨다. */
let stateRef: MockState | null = null;

function getState(): MockState {
  if (stateRef == null) {
    const units = createUnitRowDtos(APP_ENV.mockRowCount);
    stateRef = {
      complexes: [...MOCK_COMPLEXES],
      units,
      requirements: createRequirementRowDtos(24),
      interactions: units.slice(0, 400).map((unit, index) => interactionFor(index, unit.id, null)),
      nextId: 1_000_000,
    };
  }
  return stateRef;
}

function nextId(): number {
  const state = getState();
  state.nextId += 1;
  return state.nextId;
}

async function delay(signal?: AbortSignal): Promise<void> {
  const ms = APP_ENV.mockLatencyMs;
  if (ms <= 0) return;
  await new Promise<void>((resolve, reject) => {
    const onAbort = () => {
      clearTimeout(timer);
      reject(new LedgerApiError({ kind: "canceled", message: "요청이 취소되었습니다." }));
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    if (signal?.aborted) {
      onAbort();
      return;
    }
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

/** 필터 값 하나가 행의 값과 맞는지. `__EMPTY__`는 빈 값을 뜻한다(F1-GR-41). */
function matchesFilterValue(rowValue: unknown, accepted: readonly string[]): boolean {
  if (accepted.length === 0) return true;
  const text = rowValue == null || rowValue === "" ? EMPTY_VALUE : String(rowValue);
  return accepted.includes(text);
}

function unitFieldValue(row: PropertyUnitRowDto, column: string): unknown {
  switch (column) {
    case "complex_id":
      return row.complex.id;
    case "building_number":
      return row.building_number;
    case "unit_number":
      return row.unit_number;
    case "floor_number":
      return row.floor_number;
    case "orientation":
      return row.orientation;
    case "tenancy_status":
      return row.tenancy_status;
    case "lifecycle_status":
      return row.lifecycle_status;
    case "unit_type":
      return row.unit_type;
    case "assigned_user_id":
      return row.assigned_user_id;
    case "listing_status":
      return row.current_listing?.status ?? null;
    case "handover_condition":
      return row.current_listing?.handover_condition ?? null;
    default:
      return null;
  }
}

function requirementFieldValue(row: PropertyRequirementRowDto, column: string): unknown {
  switch (column) {
    case "demand_type":
      return row.demand_type;
    case "status":
      return row.status;
    case "classification":
      return row.classification;
    case "workflow_stage":
      return row.workflow_stage;
    case "assigned_user_id":
      return row.assigned_user_id;
    default:
      return null;
  }
}

function filterUnits(query: ListQuery): PropertyUnitRowDto[] {
  const filters = query.filters ?? {};
  return getState().units.filter((row) =>
    Object.entries(filters).every(([column, accepted]) =>
      accepted == null || accepted.length === 0
        ? true
        : matchesFilterValue(unitFieldValue(row, column), accepted),
    ),
  );
}

function filterRequirements(query: ListQuery): PropertyRequirementRowDto[] {
  const filters = query.filters ?? {};
  return getState().requirements.filter((row) =>
    Object.entries(filters).every(([column, accepted]) =>
      accepted == null || accepted.length === 0
        ? true
        : matchesFilterValue(requirementFieldValue(row, column), accepted),
    ),
  );
}

/** 서버와 같은 상한을 적용한다. 이걸 재현하지 않으면 전량 로드를 전제한 화면이 만들어진다. */
function paginate<T>(items: T[], query: ListQuery): PageDto<T> {
  const offset = Math.max(0, query.offset ?? 0);
  const limit = Math.min(query.limit ?? 100, MAX_PAGE_SIZE);
  return { items: items.slice(offset, offset + limit), total: items.length, limit, offset };
}

/** 동·호 오름차순. 그리드 기본 정렬(F1-GR-20). */
function byBuildingAndUnit(left: PropertyUnitRowDto, right: PropertyUnitRowDto): number {
  const building = Number(left.building_number ?? 0) - Number(right.building_number ?? 0);
  if (building !== 0) return building;
  return Number(left.unit_number ?? 0) - Number(right.unit_number ?? 0);
}

function detailFor(unit: PropertyUnitRowDto): PropertyUnitDetailDto {
  return {
    unit,
    listings: unit.current_listing == null ? [] : [unit.current_listing],
    parties: relationsFor(unit.id),
  };
}

function requireUnit(unitId: number): PropertyUnitRowDto {
  const unit = getState().units.find((row) => row.id === unitId);
  if (unit == null) {
    throw new LedgerApiError({ kind: "notFound", message: "대상 세대를 찾지 못했습니다.", status: 404 });
  }
  return unit;
}

function assertVersion(current: number, incoming: number | undefined): void {
  // 실제 서버도 같은 규칙으로 409를 돌려주어야 한다(F1-GR-26).
  if (incoming != null && incoming !== current) {
    throw new LedgerApiError({
      kind: "conflict",
      message: "다른 사용자가 먼저 저장했습니다.",
      status: 409,
      code: "ROW_VERSION_CONFLICT",
    });
  }
}

function columnValues(values: unknown[], column: string): ColumnValuesDto {
  const counts = new Map<string, number>();
  for (const value of values) {
    const key = value == null || value === "" ? EMPTY_VALUE : String(value);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return {
    column,
    items: [...counts.entries()]
      .map(([value, count]) => ({ value, count }))
      .sort((left, right) => {
        if (left.value === EMPTY_VALUE) return -1;
        if (right.value === EMPTY_VALUE) return 1;
        return left.value.localeCompare(right.value, "ko-KR", { numeric: true });
      }),
  };
}

export const mockTransport: LedgerTransport = {
  async listComplexes(query, signal) {
    await delay(signal);
    const state = getState();
    const limit = Math.min(query.limit ?? 100, MAX_PAGE_SIZE);
    const offset = query.offset ?? 0;
    return {
      items: structuredClone(state.complexes.slice(offset, offset + limit)),
      total: state.complexes.length,
      limit,
      offset,
    };
  },

  async createComplex(payload, signal) {
    await delay(signal);
    const state = getState();
    const name = payload.name.trim();
    if (name === "") {
      throw new LedgerApiError({ kind: "validation", message: "단지명을 입력해 주세요." });
    }
    if (state.complexes.some((entry) => entry.name.toLowerCase() === name.toLowerCase())) {
      throw new LedgerApiError({ kind: "validation", message: `이미 등록된 단지입니다: ${name}` });
    }
    const created: ComplexSummaryDto = {
      id: nextId(),
      name,
      property_type: payload.property_type ?? "APARTMENT",
      road_address: payload.road_address,
      row_version: 1,
    };
    state.complexes.push(created);
    return structuredClone(created);
  },

  async deleteComplex(complexId, rowVersion, signal) {
    await delay(signal);
    const state = getState();
    const found = state.complexes.find((entry) => entry.id === complexId);
    if (found == null) {
      throw new LedgerApiError({ kind: "notFound", message: "단지를 찾지 못했습니다.", status: 404 });
    }
    assertVersion(found.row_version, rowVersion);
    if (state.units.some((unit) => unit.complex.id === complexId)) {
      throw new LedgerApiError({
        kind: "validation",
        message: "이 단지에 등록된 세대가 있어 삭제할 수 없습니다.",
        status: 422,
      });
    }
    state.complexes = state.complexes.filter((entry) => entry.id !== complexId);
  },

  async listPropertyUnits(query, signal) {
    await delay(signal);
    return paginate(filterUnits(query).sort(byBuildingAndUnit), query);
  },

  async getPropertyUnit(unitId, signal) {
    await delay(signal);
    return structuredClone(detailFor(requireUnit(unitId)));
  },

  async createPropertyUnit(payload, signal) {
    await delay(signal);
    const state = getState();
    const complex =
      MOCK_COMPLEXES.find((entry) => entry.id === payload.complex_id) ?? MOCK_COMPLEXES[0];
    if (complex == null) {
      throw new LedgerApiError({ kind: "validation", message: "단지를 찾지 못했습니다.", status: 422 });
    }

    const created: PropertyUnitRowDto = {
      id: nextId(),
      complex,
      building_number: payload.building_number,
      unit_number: payload.unit_number,
      floor_number: payload.floor_number,
      orientation: payload.orientation,
      unit_type: payload.unit_type,
      pyeong: payload.pyeong,
      exclusive_area_sqm: null,
      supply_area_sqm: null,
      tenancy_status: payload.tenancy_status,
      current_deposit_amount: payload.current_deposit_amount,
      current_monthly_rent_amount: payload.current_monthly_rent_amount,
      loan_amount: payload.loan_amount,
      tenancy_expiry_date: payload.tenancy_expiry_date,
      tenancy_raw_text: payload.tenancy_raw_text,
      is_expanded: payload.is_expanded,
      built_in_features: payload.built_in_features,
      facility_condition: payload.facility_condition,
      lifecycle_status: "NORMAL",
      assigned_user_id: payload.assigned_user_id,
      memo: payload.memo,
      custom_fields: payload.custom_fields,
      last_contact_at: null,
      row_version: 1,
      current_listing: null,
      latest_interaction_content: null,
    };
    // 새 행은 그리드 최상단에 보이도록 앞에 넣는다(F1-GR-30).
    state.units.unshift(created);
    return structuredClone(detailFor(created));
  },

  async updatePropertyUnit(unitId, payload, signal) {
    await delay(signal);
    const unit = requireUnit(unitId);
    assertVersion(unit.row_version, payload.row_version);

    const complexId = unit.complex.id;
    Object.assign(unit, {
      building_number: payload.building_number ?? unit.building_number,
      unit_number: payload.unit_number ?? unit.unit_number,
      floor_number: payload.floor_number ?? unit.floor_number,
      orientation: payload.orientation ?? unit.orientation,
      unit_type: payload.unit_type ?? unit.unit_type,
      pyeong: payload.pyeong ?? unit.pyeong,
      current_deposit_amount: payload.current_deposit_amount ?? unit.current_deposit_amount,
      current_monthly_rent_amount:
        payload.current_monthly_rent_amount ?? unit.current_monthly_rent_amount,
      loan_amount: payload.loan_amount ?? unit.loan_amount,
      tenancy_expiry_date: payload.tenancy_expiry_date ?? unit.tenancy_expiry_date,
      tenancy_raw_text: payload.tenancy_raw_text ?? unit.tenancy_raw_text,
      built_in_features: payload.built_in_features ?? unit.built_in_features,
      facility_condition: payload.facility_condition ?? unit.facility_condition,
      lifecycle_status: payload.lifecycle_status ?? unit.lifecycle_status,
      assigned_user_id: payload.assigned_user_id ?? unit.assigned_user_id,
      memo: payload.memo ?? unit.memo,
      custom_fields: payload.custom_fields ?? unit.custom_fields,
      row_version: unit.row_version + 1,
    });
    unit.complex = MOCK_COMPLEXES.find((entry) => entry.id === complexId) ?? unit.complex;
    return structuredClone(detailFor(unit));
  },

  async deletePropertyUnit(unitId, rowVersion, signal) {
    await delay(signal);
    const state = getState();
    const unit = requireUnit(unitId);
    assertVersion(unit.row_version, rowVersion);
    // 서버는 소프트 삭제하지만 목록에서 사라진다는 결과는 같다.
    state.units = state.units.filter((row) => row.id !== unitId);
  },

  async createPropertyListing(unitId, payload, signal) {
    await delay(signal);
    const unit = requireUnit(unitId);
    const created: PropertyListingDto = {
      id: nextId(),
      unit_id: unitId,
      client_party_id: null,
      received_at: payload.received_at,
      status: "RECEIVED",
      is_sale_available: payload.is_sale_available,
      sale_price: payload.sale_price,
      is_jeonse_available: payload.is_jeonse_available,
      jeonse_deposit_amount: payload.jeonse_deposit_amount,
      is_monthly_rent_available: payload.is_monthly_rent_available,
      monthly_rent_deposit_amount: payload.monthly_rent_deposit_amount,
      monthly_rent_amount: payload.monthly_rent_amount,
      price_raw_text: payload.price_raw_text,
      handover_condition: payload.handover_condition,
      assigned_user_id: unit.assigned_user_id,
      memo: payload.memo,
      custom_fields: payload.custom_fields,
      row_version: 1,
    };
    unit.current_listing = created;
    return structuredClone(created);
  },

  async updatePropertyListing(listingId, payload, signal) {
    await delay(signal);
    const unit = getState().units.find((row) => row.current_listing?.id === listingId);
    const listing = unit?.current_listing;
    if (listing == null) {
      throw new LedgerApiError({ kind: "notFound", message: "대상 매물을 찾지 못했습니다.", status: 404 });
    }
    assertVersion(listing.row_version, payload.row_version);
    Object.assign(listing, {
      received_at: payload.received_at ?? listing.received_at,
      is_sale_available: payload.is_sale_available ?? listing.is_sale_available,
      sale_price: payload.sale_price ?? listing.sale_price,
      is_jeonse_available: payload.is_jeonse_available ?? listing.is_jeonse_available,
      jeonse_deposit_amount: payload.jeonse_deposit_amount ?? listing.jeonse_deposit_amount,
      is_monthly_rent_available:
        payload.is_monthly_rent_available ?? listing.is_monthly_rent_available,
      monthly_rent_deposit_amount:
        payload.monthly_rent_deposit_amount ?? listing.monthly_rent_deposit_amount,
      monthly_rent_amount: payload.monthly_rent_amount ?? listing.monthly_rent_amount,
      price_raw_text: payload.price_raw_text ?? listing.price_raw_text,
      handover_condition: payload.handover_condition ?? listing.handover_condition,
      row_version: listing.row_version + 1,
    });
    return structuredClone(listing);
  },

  async listRequirements(query, signal) {
    await delay(signal);
    // 정렬 기준은 최종접촉일이다. 접수일과 분리되어 있다(F1-DM-07).
    const filtered = filterRequirements(query).sort((left, right) =>
      String(right.last_contact_at ?? "").localeCompare(String(left.last_contact_at ?? "")),
    );
    return paginate(filtered, query);
  },

  async getRequirement(requirementId, signal) {
    await delay(signal);
    const requirement = getState().requirements.find((row) => row.id === requirementId);
    if (requirement == null) {
      throw new LedgerApiError({ kind: "notFound", message: "대상 손님을 찾지 못했습니다.", status: 404 });
    }
    const complex = MOCK_COMPLEXES[requirementId % MOCK_COMPLEXES.length] ?? MOCK_COMPLEXES[0];
    return structuredClone({
      requirement,
      desired_complexes: complex == null ? [] : [{ complex, preference_order: 1 }],
    });
  },

  async createRequirement(payload, signal) {
    await delay(signal);
    const state = getState();
    const created: PropertyRequirementRowDto = {
      id: nextId(),
      party: {
        id: payload.party_id,
        party_type: "INDIVIDUAL",
        name: "신규 손님",
        alternate_name: null,
        privacy_consent_at: new Date().toISOString(),
        contacts: [],
      },
      received_at: payload.received_at,
      demand_type: payload.demand_type,
      desired_pyeongs: payload.desired_pyeongs,
      min_area_sqm: null,
      max_area_sqm: null,
      area_requirement_raw_text: payload.area_requirement_raw_text,
      min_budget_amount: payload.min_budget_amount,
      max_budget_amount: payload.max_budget_amount,
      budget_raw_text: payload.budget_raw_text,
      desired_move_in_date: payload.desired_move_in_date,
      move_in_date_raw_text: payload.move_in_date_raw_text,
      request_expiry_date: payload.request_expiry_date,
      current_tenancy_expiry_date: null,
      co_broker_party_id: null,
      classification: payload.classification,
      workflow_stage: payload.workflow_stage,
      status: payload.status ?? "ACTIVE",
      assigned_user_id: payload.assigned_user_id,
      memo: payload.memo,
      custom_fields: payload.custom_fields,
      last_contact_at: new Date().toISOString(),
      row_version: 1,
    };
    state.requirements.unshift(created);
    return structuredClone({ requirement: created, desired_complexes: [] });
  },

  async updateRequirement(requirementId, payload, signal) {
    await delay(signal);
    const requirement = getState().requirements.find((row) => row.id === requirementId);
    if (requirement == null) {
      throw new LedgerApiError({ kind: "notFound", message: "대상 손님을 찾지 못했습니다.", status: 404 });
    }
    assertVersion(requirement.row_version, payload.row_version);
    Object.assign(requirement, {
      received_at: payload.received_at ?? requirement.received_at,
      demand_type: payload.demand_type ?? requirement.demand_type,
      desired_pyeongs: payload.desired_pyeongs ?? requirement.desired_pyeongs,
      area_requirement_raw_text:
        payload.area_requirement_raw_text ?? requirement.area_requirement_raw_text,
      min_budget_amount: payload.min_budget_amount ?? requirement.min_budget_amount,
      max_budget_amount: payload.max_budget_amount ?? requirement.max_budget_amount,
      budget_raw_text: payload.budget_raw_text ?? requirement.budget_raw_text,
      desired_move_in_date: payload.desired_move_in_date ?? requirement.desired_move_in_date,
      request_expiry_date: payload.request_expiry_date ?? requirement.request_expiry_date,
      classification: payload.classification ?? requirement.classification,
      workflow_stage: payload.workflow_stage ?? requirement.workflow_stage,
      status: payload.status ?? requirement.status,
      memo: payload.memo ?? requirement.memo,
      custom_fields: payload.custom_fields ?? requirement.custom_fields,
      row_version: requirement.row_version + 1,
    });
    return structuredClone({ requirement, desired_complexes: [] });
  },

  async deleteRequirement(requirementId, rowVersion, signal) {
    await delay(signal);
    const state = getState();
    const requirement = state.requirements.find((row) => row.id === requirementId);
    if (requirement == null) {
      throw new LedgerApiError({ kind: "notFound", message: "대상 손님을 찾지 못했습니다.", status: 404 });
    }
    assertVersion(requirement.row_version, rowVersion);
    state.requirements = state.requirements.filter((row) => row.id !== requirementId);
  },

  async listClientInteractions(scope, signal) {
    await delay(signal);
    // 범위 없는 전체 조회는 제공하지 않는다.
    if (scope.unitId == null && scope.requirementId == null && scope.partyId == null) {
      throw new LedgerApiError({
        kind: "validation",
        message: "조회 범위를 지정해야 합니다.",
        status: 422,
      });
    }
    const items = getState().interactions.filter(
      (row) =>
        (scope.unitId != null && row.unit_id === scope.unitId) ||
        (scope.requirementId != null && row.requirement_id === scope.requirementId) ||
        (scope.partyId != null && row.party_id === scope.partyId),
    );
    return { items: structuredClone(items), total: items.length, limit: items.length, offset: 0 };
  },

  async createClientInteraction(payload, signal) {
    await delay(signal);
    const created: ClientInteractionDto = {
      id: nextId(),
      interaction_at: new Date().toISOString(),
      interaction_channel: "CALL",
      communication_direction: null,
      interaction_result: null,
      counterparty_role: null,
      counterparty_index: null,
      interaction_content: payload.interaction_content,
      party_id: payload.party_id ?? null,
      unit_id: payload.unit_id ?? null,
      listing_id: null,
      requirement_id: payload.requirement_id ?? null,
      source_type: "HUMAN",
      approval_status: "NOT_REQUIRED",
      created_by: null,
      created_at: new Date().toISOString(),
    };
    // 상담 로그는 추가 전용이다. 기존 로그를 고치지 않고 새 항목만 쌓는다.
    getState().interactions.unshift(created);
    return structuredClone(created);
  },

  async listUnitColumnValues(column, query, signal) {
    await delay(signal);
    return columnValues(
      filterUnits(query).map((row) => unitFieldValue(row, column)),
      column,
    );
  },

  async listRequirementColumnValues(column, query, signal) {
    await delay(signal);
    return columnValues(
      filterRequirements(query).map((row) => requirementFieldValue(row, column)),
      column,
    );
  },
};
