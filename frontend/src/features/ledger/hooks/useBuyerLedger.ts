/**
 * 구입장 훅.
 *
 * 알려진 제약: 구입장 생성은 `party_id`를 필수로 요구하는데 계약에 **인물 생성 엔드포인트가 없다**.
 * 따라서 기존 인물이 연결되지 않은 신규 손님은 실제 API로 저장할 수 없다.
 * 여기서는 저장을 조용히 실패시키지 않고 사용자에게 보이는 오류로 명시한다.
 */

import { useCallback, useMemo } from "react";
import { LedgerApiError } from "../api/errors.ts";
import { ledgerTransport } from "../api/ledgerTransport.ts";
import type { ListQuery } from "../api/transport.ts";
import {
  createBuyerDraftRow,
  toBuyerRow,
  toRequirementCreatePayload,
  toRequirementUpdatePayload,
} from "../model/buyerMapper.ts";
import { newInteractionContent } from "../model/propertyMapper.ts";
import type { BuyerRow } from "../model/row.ts";
import type { LedgerCollection } from "./useLedgerCollection.ts";
import { toApiError, useLedgerCollection } from "./useLedgerCollection.ts";

export interface BuyerLedger extends LedgerCollection<BuyerRow> {
  loadDetail: (row: BuyerRow) => Promise<BuyerRow>;
  saveRow: (row: BuyerRow) => Promise<BuyerRow>;
  discardRow: (row: BuyerRow) => void;
}

export function useBuyerLedger(
  query: ListQuery,
  options: { enabled?: boolean; userName?: (userId: number | null) => string } = {},
): BuyerLedger {
  const userName = options.userName;

  const toRow = useCallback(
    (dto: Parameters<typeof toBuyerRow>[0]) =>
      toBuyerRow(dto, { assigneeName: userName?.(dto.assigned_user_id) ?? "" }),
    [userName],
  );

  const stableQuery = useMemo(
    () => query,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [JSON.stringify(query)],
  );

  const collection = useLedgerCollection(
    (listQuery, signal) => ledgerTransport.listRequirements(listQuery, signal),
    toRow,
    createBuyerDraftRow,
    stableQuery,
    { localDraftPrefix: "BUYER-DRAFT-", enabled: options.enabled ?? true },
  );

  const { patchRow, removeRow } = collection;

  /** 희망 단지와 상담 로그는 목록 응답에 없다. 상세를 열 때 채운다. */
  const loadDetail = useCallback(
    async (row: BuyerRow): Promise<BuyerRow> => {
      if (row.serverId == null) return row;
      const [detail, interactions] = await Promise.all([
        ledgerTransport.getRequirement(row.serverId),
        ledgerTransport.listClientInteractions({ requirementId: row.serverId, limit: 1 }),
      ]);
      const primary = detail.desired_complexes[0];
      const next: BuyerRow = {
        ...row,
        complexId: primary?.complex.id ?? null,
        complex: primary?.complex.name ?? "",
        content: interactions.items[0]?.interaction_content ?? "",
      };
      patchRow(row.id, () => next);
      return next;
    },
    [patchRow],
  );

  const saveRow = useCallback(
    async (row: BuyerRow): Promise<BuyerRow> => {
      patchRow(row.id, (current) => ({ ...current, sync: { status: "saving" } }));

      try {
        let requirementId: number;

        if (row.serverId == null) {
          const create = toRequirementCreatePayload(row);
          if (create == null) {
            throw new LedgerApiError({
              kind: "validation",
              message:
                row.partyId == null
                  ? "손님(인물)을 먼저 등록해야 저장할 수 있습니다. 인물 등록 API가 아직 없습니다."
                  : "거래 구분을 확인해 주세요.",
            });
          }
          const detail = await ledgerTransport.createRequirement(create);
          requirementId = detail.requirement.id;
        } else {
          const update = toRequirementUpdatePayload(row);
          if (update == null) throw new Error("row_version이 없어 저장할 수 없습니다.");
          const detail = await ledgerTransport.updateRequirement(row.serverId, update);
          requirementId = detail.requirement.id;
        }

        const newLog = newInteractionContent(row.content, "");
        if (newLog != null) {
          await ledgerTransport.createClientInteraction({
            interaction_content: newLog,
            requirement_id: requirementId,
          });
        }

        const refreshed = await ledgerTransport.getRequirement(requirementId);
        const primary = refreshed.desired_complexes[0];
        const saved: BuyerRow = {
          ...toRow(refreshed.requirement),
          id: row.id,
          complexId: primary?.complex.id ?? row.complexId,
          complex: primary?.complex.name ?? row.complex,
          content: row.content,
        };
        patchRow(row.id, () => saved);
        return saved;
      } catch (error: unknown) {
        const apiError = toApiError(error);
        patchRow(row.id, (current) => ({
          ...current,
          sync:
            apiError.kind === "conflict"
              ? { status: "conflict", reason: apiError.message }
              : { status: "failed", reason: apiError.message },
        }));
        throw apiError;
      }
    },
    [patchRow, toRow],
  );

  const discardRow = useCallback(
    (row: BuyerRow) => {
      if (row.serverId == null) removeRow(row.id);
    },
    [removeRow],
  );

  return useMemo(
    () => ({ ...collection, loadDetail, saveRow, discardRow }),
    [collection, loadDetail, saveRow, discardRow],
  );
}
