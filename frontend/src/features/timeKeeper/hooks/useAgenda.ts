/**
 * 일정·할 일 목록 상태.
 *
 * 앱이 열릴 때 한 번 읽는다. 폴링하지 않는다. 기한은 하루 단위로 움직이는 값이라 브리핑과
 * 알림 버튼이 부를 때 다시 읽는 것으로 충분하고, 주기 호출을 두면 그 자체가 유지할 장치가 된다.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, isCanceled } from "../../../shared/api/errors.ts";
import { timeKeeperTransport } from "../api/timeKeeperTransport.ts";
import type { AgendaQuery } from "../api/transport.ts";
import type { AgendaCategorySummaryDto, AgendaItemDto } from "../model/dto.ts";

export interface AgendaState {
  items: AgendaItemDto[];
  /** 창 안에 실제로 존재하는 종류와 건수. 0건인 종류는 서버가 싣지 않는다. */
  categories: AgendaCategorySummaryDto[];
  /** 창 안의 전체 건수. `items`는 종류별 상한과 `limit`을 적용한 뒤의 행이다. */
  total: number;
  /** 서버가 D-day를 계산한 기준일(ISO 날짜). */
  asOf: string | null;
  withinDays: number | null;
  status: "loading" | "ready" | "error";
  error: ApiError | null;
  /** 성공·실패로 끝난 조회 횟수. 브리핑이 자신이 요청한 재조회의 결과만 기다릴 때 쓴다. */
  settlementCount: number;
  reload: () => void;
}

export function useAgenda(query: AgendaQuery, options: { enabled?: boolean } = {}): AgendaState {
  const enabled = options.enabled ?? true;
  const { withinDays, overdueDays, recontactDays, revalidationDays, perCategoryLimit, limit, offset } =
    query;

  const [items, setItems] = useState<AgendaItemDto[]>([]);
  const [categories, setCategories] = useState<AgendaCategorySummaryDto[]>([]);
  const [total, setTotal] = useState(0);
  const [asOf, setAsOf] = useState<string | null>(null);
  const [windowDays, setWindowDays] = useState<number | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState<ApiError | null>(null);
  const [settlementCount, setSettlementCount] = useState(0);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    if (!enabled) return undefined;
    const controller = new AbortController();
    setStatus("loading");

    timeKeeperTransport
      .listAgenda(
        {
          withinDays,
          overdueDays,
          recontactDays,
          revalidationDays,
          perCategoryLimit,
          limit,
          offset,
        },
        controller.signal,
      )
      .then((page) => {
        if (controller.signal.aborted) return;
        setItems(page.items);
        setCategories(page.categories);
        setTotal(page.total);
        setAsOf(page.as_of);
        setWindowDays(page.within_days);
        setStatus("ready");
        setError(null);
        setSettlementCount((current) => current + 1);
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted || isCanceled(cause)) return;
        setStatus("error");
        setError(
          cause instanceof ApiError
            ? cause
            : new ApiError({ kind: "server", message: "일정 목록을 불러오지 못했습니다.", cause }),
        );
        setSettlementCount((current) => current + 1);
      });

    return () => controller.abort();
    // 원시값만 의존성에 둔다. query 객체를 그대로 넣으면 다시 그릴 때마다 재조회한다.
  }, [
    enabled,
    withinDays,
    overdueDays,
    recontactDays,
    revalidationDays,
    perCategoryLimit,
    limit,
    offset,
    reloadToken,
  ]);

  const reload = useCallback(() => setReloadToken((current) => current + 1), []);

  return useMemo(
    () => ({
      items,
      categories,
      total,
      asOf,
      withinDays: windowDays,
      status,
      error,
      settlementCount,
      reload,
    }),
    [
      items,
      categories,
      total,
      asOf,
      windowDays,
      status,
      error,
      settlementCount,
      reload,
    ],
  );
}
