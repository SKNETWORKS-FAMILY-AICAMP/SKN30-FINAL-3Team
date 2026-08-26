/**
 * 장부 목록의 서버 상태를 소유하는 훅.
 *
 * 상태는 판별 가능한 모델로 둔다. `isLoading`과 `hasError` 같은 독립 boolean을 늘리면
 * "로딩이면서 오류"처럼 불가능한 조합이 생긴다.
 *
 * 페이징을 감춘다. 계약상 `limit`이 최대 500이라 한 번에 다 받을 수 없다.
 * 첫 페이지로 `total`을 확인한 뒤 남은 페이지를 병렬로 받아 이어 붙인다.
 * 상한(`maxRows`)을 두어 무한정 요청하지 않는다.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, isCanceled } from "../../../shared/api/index.ts";
import type { ListQuery } from "../api/transport.ts";
import type { PageDto } from "../model/dto.ts";
import { MAX_PAGE_SIZE } from "../model/dto.ts";
import type { RowSyncState } from "../model/row.ts";

export type CollectionStatus = "loading" | "ready" | "error";

export interface CollectionState<TRow> {
  status: CollectionStatus;
  rows: TRow[];
  /** 서버가 보고한 전체 건수(F1-GR-04). 화면에 실린 행 수와 다를 수 있다. */
  totalCount: number;
  /** 상한에 걸려 일부만 불러왔는지. 그리드 건수 표기가 오해를 주지 않게 하려고 노출한다. */
  truncated: boolean;
  error: ApiError | null;
}

interface RowLike {
  id: string;
  serverId: number | null;
  sync: RowSyncState;
}

export interface CollectionOptions {
  localDraftPrefix: string;
  enabled?: boolean;
  /** 불러올 최대 행 수. 기본 2000행(4페이지). */
  maxRows?: number;
}

export interface LedgerCollection<TRow> {
  state: CollectionState<TRow>;
  reload: () => void;
  replaceRows: (rows: TRow[] | ((current: TRow[]) => TRow[])) => void;
  /** 빈 행 추가(F1-GR-30). 계약상 서버로 보내지 않고 화면 상태로만 만든다. */
  addDraft: () => TRow;
  patchRow: (rowId: string, patch: (row: TRow) => TRow) => void;
  removeRow: (rowId: string) => void;
}

let localDraftSequence = 0;

function nextLocalDraftId(prefix: string): string {
  localDraftSequence += 1;
  return `${prefix}${Date.now()}-${localDraftSequence}`;
}

export function useLedgerCollection<TRow extends RowLike, TDto>(
  fetchPage: (query: ListQuery, signal: AbortSignal) => Promise<PageDto<TDto>>,
  toRow: (dto: TDto) => TRow,
  createLocalDraft: (localId: string) => TRow,
  query: ListQuery,
  options: CollectionOptions,
): LedgerCollection<TRow> {
  const enabled = options.enabled ?? true;
  const maxRows = options.maxRows ?? 2000;

  const [state, setState] = useState<CollectionState<TRow>>({
    status: "loading",
    rows: [],
    totalCount: 0,
    truncated: false,
    error: null,
  });
  const [reloadToken, setReloadToken] = useState(0);

  const fetchRef = useRef(fetchPage);
  fetchRef.current = fetchPage;
  const toRowRef = useRef(toRow);
  toRowRef.current = toRow;

  // 조회 조건은 값으로 비교한다. 객체 정체성으로 비교하면 매 렌더 재조회한다.
  const queryKey = JSON.stringify(query);

  useEffect(() => {
    if (!enabled) return undefined;

    const controller = new AbortController();
    const activeQuery = JSON.parse(queryKey) as ListQuery;
    setState((current) => ({ ...current, status: "loading", error: null }));

    const load = async () => {
      const first = await fetchRef.current(
        { ...activeQuery, limit: MAX_PAGE_SIZE, offset: 0 },
        controller.signal,
      );
      const wanted = Math.min(first.total, maxRows);
      const remaining: Array<Promise<PageDto<TDto>>> = [];
      for (let offset = first.items.length; offset < wanted; offset += MAX_PAGE_SIZE) {
        remaining.push(
          fetchRef.current({ ...activeQuery, limit: MAX_PAGE_SIZE, offset }, controller.signal),
        );
      }
      const pages = remaining.length === 0 ? [] : await Promise.all(remaining);
      const dtos = [first.items, ...pages.map((page) => page.items)].flat();
      return { dtos, total: first.total };
    };

    load()
      .then(({ dtos, total }) => {
        if (controller.signal.aborted) return;
        setState({
          status: "ready",
          rows: dtos.map((dto) => toRowRef.current(dto)),
          totalCount: total,
          truncated: total > dtos.length,
          error: null,
        });
      })
      .catch((error: unknown) => {
        // 취소는 오류가 아니다. 뒤이은 요청이 화면을 갱신한다.
        if (controller.signal.aborted || isCanceled(error)) return;
        setState({
          status: "error",
          rows: [],
          totalCount: 0,
          truncated: false,
          error: toApiError(error),
        });
      });

    return () => controller.abort();
  }, [enabled, maxRows, queryKey, reloadToken]);

  const reload = useCallback(() => setReloadToken((current) => current + 1), []);

  const replaceRows = useCallback((rows: TRow[] | ((current: TRow[]) => TRow[])) => {
    setState((current) => ({
      ...current,
      rows: typeof rows === "function" ? rows(current.rows) : rows,
    }));
  }, []);

  const patchRow = useCallback((rowId: string, patch: (row: TRow) => TRow) => {
    setState((current) => ({
      ...current,
      rows: current.rows.map((row) => (row.id === rowId ? patch(row) : row)),
    }));
  }, []);

  const removeRow = useCallback((rowId: string) => {
    setState((current) => ({
      ...current,
      rows: current.rows.filter((row) => row.id !== rowId),
      totalCount: Math.max(0, current.totalCount - 1),
    }));
  }, []);

  const addDraft = useCallback((): TRow => {
    const draft = createLocalDraft(nextLocalDraftId(options.localDraftPrefix));
    // 빈 행은 서버로 보내지 않는다. 저장 시점에 필수값을 갖춘 POST 한 번으로 확정한다.
    setState((current) => ({ ...current, rows: [draft, ...current.rows] }));
    return draft;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [options.localDraftPrefix]);

  return useMemo(
    () => ({ state, reload, replaceRows, addDraft, patchRow, removeRow }),
    [state, reload, replaceRows, addDraft, patchRow, removeRow],
  );
}

export function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;
  return new ApiError({
    kind: "server",
    message: error instanceof Error ? error.message : "알 수 없는 오류입니다.",
    cause: error,
  });
}
