/**
 * 실제 백엔드를 호출하는 transport.
 *
 * 경로와 요청·응답 형태의 정본은 project-wiki `contracts/api.md`의 "F1 장부 계약"과
 * `backend/src/api/property_ledger.py`다. 화면과 훅은 경로를 알지 못하므로
 * 계약이 바뀌어도 변경이 이 파일 밖으로 번지지 않는다.
 */

import {
  decodeClientInteraction,
  decodeComplexSummary,
  decodeColumnValues,
  decodeListing,
  decodePage,
  decodePropertyUnitDetail,
  decodePropertyUnitRow,
  decodeRequirementDetail,
  decodeRequirementRow,
} from "../model/decode.ts";
import { expectNoContent, request } from "./httpClient.ts";
import type { QueryValue } from "./httpClient.ts";
import type { ColumnFilters, LedgerTransport, ListQuery } from "./transport.ts";

const PATHS = {
  complexes: "/property-complexes",
  units: "/property-units",
  unitColumnValues: "/property-units/column-values",
  listings: "/property-listings",
  requirements: "/property-requirements",
  requirementColumnValues: "/property-requirements/column-values",
  interactions: "/client-interactions",
} as const;

/** 같은 키를 반복해 보내면 서버가 OR로 결합한다. 빈 값은 필터로 취급되지 않는다. */
function toQuery(query: ListQuery, extra: Record<string, QueryValue> = {}): Record<string, QueryValue> {
  const params: Record<string, QueryValue> = { ...extra };
  const filters: ColumnFilters = query.filters ?? {};
  for (const [key, values] of Object.entries(filters)) {
    if (values != null && values.length > 0) params[key] = [...values];
  }
  if (query.limit != null) params["limit"] = query.limit;
  if (query.offset != null) params["offset"] = query.offset;
  return params;
}

export const httpTransport: LedgerTransport = {
  async listComplexes(query, signal) {
    return request(PATHS.complexes, {
      query: toQuery(query),
      signal,
      decode: (value) => decodePage(value, (entry, path) => decodeComplexSummary(entry, path)),
    });
  },

  async createComplex(payload, signal) {
    return request(PATHS.complexes, {
      method: "POST",
      body: payload,
      signal,
      decode: (value) => decodeComplexSummary(value),
    });
  },

  async deleteComplex(complexId, rowVersion, signal) {
    return request(`${PATHS.complexes}/${complexId}`, {
      method: "DELETE",
      query: { row_version: rowVersion },
      signal,
      decode: expectNoContent,
    });
  },

  async listPropertyUnits(query, signal) {
    return request(PATHS.units, {
      query: toQuery(query),
      signal,
      decode: (value) => decodePage(value, decodePropertyUnitRow),
    });
  },

  async getPropertyUnit(unitId, signal) {
    return request(`${PATHS.units}/${unitId}`, {
      signal,
      decode: (value) => decodePropertyUnitDetail(value),
    });
  },

  async createPropertyUnit(payload, signal) {
    return request(PATHS.units, {
      method: "POST",
      body: payload,
      signal,
      decode: (value) => decodePropertyUnitDetail(value),
    });
  },

  async updatePropertyUnit(unitId, payload, signal) {
    return request(`${PATHS.units}/${unitId}`, {
      method: "PATCH",
      body: payload,
      signal,
      decode: (value) => decodePropertyUnitDetail(value),
    });
  },

  async deletePropertyUnit(unitId, rowVersion, signal) {
    return request(`${PATHS.units}/${unitId}`, {
      method: "DELETE",
      query: { row_version: rowVersion },
      signal,
      decode: expectNoContent,
    });
  },

  async createPropertyListing(unitId, payload, signal) {
    return request(`${PATHS.units}/${unitId}/listings`, {
      method: "POST",
      body: payload,
      signal,
      decode: (value) => decodeListing(value),
    });
  },

  async updatePropertyListing(listingId, payload, signal) {
    return request(`${PATHS.listings}/${listingId}`, {
      method: "PATCH",
      body: payload,
      signal,
      decode: (value) => decodeListing(value),
    });
  },

  async listRequirements(query, signal) {
    return request(PATHS.requirements, {
      query: toQuery(query),
      signal,
      decode: (value) => decodePage(value, decodeRequirementRow),
    });
  },

  async getRequirement(requirementId, signal) {
    return request(`${PATHS.requirements}/${requirementId}`, {
      signal,
      decode: (value) => decodeRequirementDetail(value),
    });
  },

  async createRequirement(payload, signal) {
    return request(PATHS.requirements, {
      method: "POST",
      body: payload,
      signal,
      decode: (value) => decodeRequirementDetail(value),
    });
  },

  async updateRequirement(requirementId, payload, signal) {
    return request(`${PATHS.requirements}/${requirementId}`, {
      method: "PATCH",
      body: payload,
      signal,
      decode: (value) => decodeRequirementDetail(value),
    });
  },

  async deleteRequirement(requirementId, rowVersion, signal) {
    return request(`${PATHS.requirements}/${requirementId}`, {
      method: "DELETE",
      query: { row_version: rowVersion },
      signal,
      decode: expectNoContent,
    });
  },

  async listClientInteractions(scope, signal) {
    // 범위를 지정하지 않은 전체 조회는 제공되지 않는다. 식별자가 없으면 422다.
    return request(PATHS.interactions, {
      query: {
        unit_id: scope.unitId,
        requirement_id: scope.requirementId,
        party_id: scope.partyId,
        limit: scope.limit,
      },
      signal,
      decode: (value) => decodePage(value, decodeClientInteraction),
    });
  },

  async createClientInteraction(payload, signal) {
    return request(PATHS.interactions, {
      method: "POST",
      body: payload,
      signal,
      decode: (value) => decodeClientInteraction(value),
    });
  },

  async listUnitColumnValues(column, query, signal) {
    return request(PATHS.unitColumnValues, {
      query: toQuery(query, { column }),
      signal,
      decode: (value) => decodeColumnValues(value),
    });
  },

  async listRequirementColumnValues(column, query, signal) {
    return request(PATHS.requirementColumnValues, {
      query: toQuery(query, { column }),
      signal,
      decode: (value) => decodeColumnValues(value),
    });
  },
};
