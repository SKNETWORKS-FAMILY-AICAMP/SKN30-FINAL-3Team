/** Open a saved result even when it is outside the currently loaded grid page. */
import { ledgerTransport } from "./ledgerTransport.ts";
import { toBuyerRow } from "../model/buyerMapper.ts";
import { applyUnitDetail, toPropertyRow } from "../model/propertyMapper.ts";
import type { BuyerRow, PropertyRow } from "../model/row.ts";

export async function loadSavedProperty(id: number, signal?: AbortSignal): Promise<PropertyRow> {
  const detail = await ledgerTransport.getPropertyUnit(id, signal);
  return applyUnitDetail(toPropertyRow(detail.unit), detail);
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
