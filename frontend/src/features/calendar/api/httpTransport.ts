/**
 * 실제 Backend를 호출하는 캘린더 transport.
 *
 * 경로와 응답 형태의 정본은 `backend/src/api/calendar.py`다. Cookie·CSRF 헤더·상태 코드 분류와
 * 취소는 `shared/api`의 `request()`가 처리한다.
 */

import { expectNoContent, request } from "../../../shared/api/index.ts";
import { decodeCalendarEvent, decodeCalendarEventList } from "../model/decode.ts";
import type { CalendarTransport } from "./transport.ts";

const PATHS = {
  events: "/calendar/events",
} as const;

export const httpTransport: CalendarTransport = {
  async listEvents(range, signal) {
    return request(PATHS.events, {
      query: { from_date: range.from, to_date: range.to },
      signal,
      decode: (value) => decodeCalendarEventList(value),
    });
  },

  async createEvent(input, signal) {
    return request(PATHS.events, {
      method: "POST",
      body: input,
      signal,
      decode: (value) => decodeCalendarEvent(value),
    });
  },

  async updateEvent(eventId, input, signal) {
    return request(`${PATHS.events}/${eventId}`, {
      method: "PATCH",
      body: input,
      signal,
      decode: (value) => decodeCalendarEvent(value),
    });
  },

  async deleteEvent(eventId, rowVersion, signal) {
    return request(`${PATHS.events}/${eventId}`, {
      method: "DELETE",
      query: { row_version: rowVersion },
      signal,
      decode: expectNoContent,
    });
  },
};
