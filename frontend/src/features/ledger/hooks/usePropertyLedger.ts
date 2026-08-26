/**
 * 매물장 훅.
 *
 * 저장이 두 요청으로 나뉜다. 세대와 매물 건이 `row_version`을 각각 가지므로
 * 계약이 한 요청으로 두 테이블을 함께 수정하지 못하게 한다.
 */

import { useCallback, useMemo } from "react";
import { ApiError } from "../../../shared/api/index.ts";
import { ledgerTransport } from "../api/ledgerTransport.ts";
import type { ListQuery } from "../api/transport.ts";
import type { PropertyUnitDetailDto } from "../model/dto.ts";
import {
  applyLatestInteraction,
  applyServerIdentity,
  applyUnitDetail,
  createPropertyDraftRow,
  hasListingValues,
  newInteractionContent,
  toListingCreatePayload,
  toListingUpdatePayload,
  toPropertyRow,
  toUnitCreatePayload,
  toUnitUpdatePayload,
} from "../model/propertyMapper.ts";
import type { PropertyRow } from "../model/row.ts";
import type { LedgerCollection } from "./useLedgerCollection.ts";
import { toApiError, useLedgerCollection } from "./useLedgerCollection.ts";

export interface PropertyLedger extends LedgerCollection<PropertyRow> {
  /** 상세를 열 때 인물과 상담 로그를 채운다. 목록 응답에는 없기 때문이다. */
  loadDetail: (row: PropertyRow) => Promise<PropertyRow>;
  saveRow: (row: PropertyRow) => Promise<PropertyRow>;
  discardRow: (row: PropertyRow) => void;
  /** 소프트 삭제. 저장되지 않은 빈 행은 서버를 부르지 않고 화면에서만 없앤다. */
  deleteRow: (row: PropertyRow) => Promise<void>;
}

/** 담당자 이름 조회표. 계약에 사용자 목록 엔드포인트가 없어 비어 있을 수 있다. */
export type UserNameLookup = (userId: number | null) => string;

export function usePropertyLedger(
  query: ListQuery,
  options: { enabled?: boolean; userName?: UserNameLookup } = {},
): PropertyLedger {
  const userName = options.userName;

  const toRow = useCallback(
    (dto: Parameters<typeof toPropertyRow>[0]) => toPropertyRow(dto, userName?.(dto.assigned_user_id) ?? ""),
    [userName],
  );

  const stableQuery = useMemo(
    () => query,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [JSON.stringify(query)],
  );

  const collection = useLedgerCollection(
    (listQuery, signal) => ledgerTransport.listPropertyUnits(listQuery, signal),
    toRow,
    createPropertyDraftRow,
    stableQuery,
    { localDraftPrefix: "DRAFT-", enabled: options.enabled ?? true },
  );

  const { patchRow, removeRow } = collection;

  const loadDetail = useCallback(
    async (row: PropertyRow): Promise<PropertyRow> => {
      if (row.serverId == null) return row;
      const [detail, interactions] = await Promise.all([
        ledgerTransport.getPropertyUnit(row.serverId),
        ledgerTransport.listClientInteractions({ unitId: row.serverId, limit: 1 }),
      ]);
      const latest = interactions.items[0]?.interaction_content ?? "";
      const next = applyLatestInteraction(applyUnitDetail(row, detail), latest);
      patchRow(row.id, () => next);
      return next;
    },
    [patchRow],
  );

  const saveRow = useCallback(
    async (row: PropertyRow): Promise<PropertyRow> => {
      patchRow(row.id, (current) => ({ ...current, sync: { status: "saving" } }));

      try {
        let detail: PropertyUnitDetailDto;

        if (row.serverId == null) {
          const create = toUnitCreatePayload(row);
          if (create == null) {
            // 실패 사유를 뭉뚱그리지 않는다. 둘은 사용자가 할 일이 전혀 다르다.
            throw new ApiError({
              kind: "validation",
              message:
                row.complexId == null
                  ? `'${row.complex || "선택한 단지"}'는 아직 서버에 등록되지 않은 단지입니다. 단지 등록 API가 없어 화면에서 만든 단지로는 저장할 수 없습니다. 목록에 있는 단지를 선택해 주세요.`
                  : "호는 저장 전에 반드시 입력해야 합니다.",
            });
          }
          detail = await ledgerTransport.createPropertyUnit(create);
        } else {
          const update = toUnitUpdatePayload(row);
          if (update == null) throw new Error("row_version이 없어 저장할 수 없습니다.");
          detail = await ledgerTransport.updatePropertyUnit(row.serverId, update);
        }

        /*
         * 세대 저장이 끝난 시점에 곧바로 서버 id와 새 row_version을 행에 반영한다.
         * 뒤따르는 매물·상담 로그 요청이 실패해도 이 행은 이미 서버에 있다.
         * 반영하지 않으면 재시도가 세대를 다시 POST해 중복을 만들거나,
         * 낡은 row_version으로 PATCH를 보내 409가 된다.
         */
        patchRow(row.id, (current) => applyServerIdentity(current, detail.unit));

        // 매물 건은 별도 레코드다. 값이 있을 때만 만들거나 고친다.
        const unitId = detail.unit.id;
        if (hasListingValues(row)) {
          if (row.listingId == null) {
            const listing = await ledgerTransport.createPropertyListing(
              unitId,
              toListingCreatePayload(row),
            );
            // 매물 건도 만들어지는 즉시 기록한다. 재시도가 같은 매물을 또 만들지 않게 한다.
            patchRow(row.id, (current) => applyServerIdentity(current, detail.unit, listing));
          } else {
            const listingUpdate = toListingUpdatePayload(row);
            if (listingUpdate != null) {
              const listing = await ledgerTransport.updatePropertyListing(
                row.listingId,
                listingUpdate,
              );
              patchRow(row.id, (current) => applyServerIdentity(current, detail.unit, listing));
            }
          }
        }

        // 상담 로그는 추가 전용이다. 실제로 바뀌었을 때만 새 로그를 남긴다.
        const newLog = newInteractionContent(row.log, "");
        if (newLog != null) {
          await ledgerTransport.createClientInteraction({
            interaction_content: newLog,
            unit_id: unitId,
          });
        }

        const refreshed = await ledgerTransport.getPropertyUnit(unitId);
        const saved = applyLatestInteraction(
          applyUnitDetail(toRow(refreshed.unit), refreshed),
          row.log,
        );
        patchRow(row.id, () => ({ ...saved, id: row.id }));
        return { ...saved, id: row.id };
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

  /** 저장하지 않고 닫은 빈 행은 그리드에 남기지 않는다(F1-GR-32). */
  const discardRow = useCallback(
    (row: PropertyRow) => {
      if (row.serverId == null) removeRow(row.id);
    },
    [removeRow],
  );

  const deleteRow = useCallback(
    async (row: PropertyRow): Promise<void> => {
      if (row.serverId == null) {
        removeRow(row.id);
        return;
      }
      if (row.rowVersion == null) {
        throw new ApiError({
          kind: "validation",
          message: "row_version이 없어 삭제할 수 없습니다. 목록을 새로 불러온 뒤 다시 시도해 주세요.",
        });
      }

      patchRow(row.id, (current) => ({ ...current, sync: { status: "saving" } }));
      try {
        await ledgerTransport.deletePropertyUnit(row.serverId, row.rowVersion);
        removeRow(row.id);
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
    [patchRow, removeRow],
  );

  return useMemo(
    () => ({ ...collection, loadDetail, saveRow, discardRow, deleteRow }),
    [collection, loadDetail, saveRow, discardRow, deleteRow],
  );
}
