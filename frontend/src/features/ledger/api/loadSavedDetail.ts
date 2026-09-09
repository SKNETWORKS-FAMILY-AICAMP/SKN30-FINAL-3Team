/** Open a saved result even when it is outside the currently loaded grid page. */
import { ApiError } from "../../../shared/api/index.ts";
import { ledgerTransport } from "./ledgerTransport.ts";
import { toBuyerRow } from "../model/buyerMapper.ts";
import { applyUnitDetail, toPropertyRow } from "../model/propertyMapper.ts";
import type { BuyerRow, PropertyRow } from "../model/row.ts";

export async function loadSavedProperty(id: number, signal?: AbortSignal, listingId?: number): Promise<PropertyRow> {
  const detail = await ledgerTransport.getPropertyUnit(id, signal);
  const listing = listingId == null ? detail.unit.current_listing : detail.listings.find(item => item.id === listingId);
  if (listingId != null && listing == null) throw new ApiError({ kind: "notFound", message: "매물 건을 찾을 수 없습니다." });
  return applyUnitDetail(toPropertyRow({ ...detail.unit, current_listing: listing ?? null }), detail);
}

export async function loadSavedBuyer(id: number, signal?: AbortSignal): Promise<BuyerRow> {
  const detail = await ledgerTransport.getRequirement(id, signal);
  const primary = detail.desired_complexes[0];
  return {
    ...toBuyerRow(detail.requirement),
    complexId: primary?.complex.id ?? null,
    complex: primary?.complex.name ?? "",
  };
}

/** Exact original consultation in an authorized ledger scope; never substitutes the latest log. */
export async function loadSavedInteraction(scope: { unitId?: number; requirementId?: number }, interactionId: number, signal?: AbortSignal) {
  const page = await ledgerTransport.listClientInteractions({ ...scope, interactionId, limit: 1 }, signal);
  const record = page.items.find(item => item.id === interactionId);
  if (record == null) throw new ApiError({ kind: "notFound", message: "상담 원본을 찾을 수 없습니다." });
  return record;
}
