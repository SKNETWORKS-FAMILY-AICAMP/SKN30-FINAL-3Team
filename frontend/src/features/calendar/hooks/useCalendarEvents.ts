/**
 * 보이는 달 범위의 캘린더 일정 상태와 CRUD.
 *
 * 월을 옮길 때마다 그 범위만 다시 읽는다. 생성·수정·삭제는 성공하면 로컬 목록을 그 자리에서
 * 갱신해 다시 전체를 불러오지 않고, 실패하면 그대로 던져 호출자(모달)가 오류를 보여주게 한다.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, isCanceled } from "../../../shared/api/errors.ts";
import { calendarTransport } from "../api/calendarTransport.ts";
import type { CalendarEventRange } from "../api/transport.ts";
import type {
  CalendarEventCreateInput,
  CalendarEventDto,
  CalendarEventUpdateInput,
} from "../model/dto.ts";

export interface CalendarEventsState {
  events: CalendarEventDto[];
  status: "loading" | "ready" | "error";
  error: ApiError | null;
  reload: () => void;
  createEvent: (input: CalendarEventCreateInput) => Promise<CalendarEventDto>;
  updateEvent: (eventId: number, input: CalendarEventUpdateInput) => Promise<CalendarEventDto>;
  deleteEvent: (eventId: number, rowVersion: number) => Promise<void>;
}

export function useCalendarEvents(
  range: CalendarEventRange,
  options: { enabled?: boolean } = {},
): CalendarEventsState {
  const enabled = options.enabled ?? true;
  const { from, to } = range;
  const [events, setEvents] = useState<CalendarEventDto[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState<ApiError | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    if (!enabled) return undefined;
    const controller = new AbortController();
    setStatus("loading");

    calendarTransport
      .listEvents({ from, to }, controller.signal)
      .then((page) => {
        if (controller.signal.aborted) return;
        setEvents(page.items);
        setStatus("ready");
        setError(null);
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted || isCanceled(cause)) return;
        setStatus("error");
        setError(
          cause instanceof ApiError
            ? cause
            : new ApiError({ kind: "server", message: "일정을 불러오지 못했습니다.", cause }),
        );
      });

    return () => controller.abort();
  }, [enabled, from, to, reloadToken]);

  const reload = useCallback(() => setReloadToken((current) => current + 1), []);

  const createEvent = useCallback(async (input: CalendarEventCreateInput) => {
    const created = await calendarTransport.createEvent(input);
    setEvents((current) => [...current, created]);
    return created;
  }, []);

  const updateEvent = useCallback(
    async (eventId: number, input: CalendarEventUpdateInput) => {
      const updated = await calendarTransport.updateEvent(eventId, input);
      setEvents((current) => current.map((entry) => (entry.id === eventId ? updated : entry)));
      return updated;
    },
    [],
  );

  const deleteEvent = useCallback(async (eventId: number, rowVersion: number) => {
    await calendarTransport.deleteEvent(eventId, rowVersion);
    setEvents((current) => current.filter((entry) => entry.id !== eventId));
  }, []);

  return useMemo(
    () => ({ events, status, error, reload, createEvent, updateEvent, deleteEvent }),
    [events, status, error, reload, createEvent, updateEvent, deleteEvent],
  );
}
