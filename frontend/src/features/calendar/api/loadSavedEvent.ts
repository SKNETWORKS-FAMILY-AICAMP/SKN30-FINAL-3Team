import { request } from "../../../shared/api/index.ts";
import { decodeCalendarEvent } from "../model/decode.ts";
import type { CalendarEventDto } from "../model/dto.ts";

export function loadSavedCalendarEvent(id: number, signal?: AbortSignal): Promise<CalendarEventDto> {
  return request(`/calendar/events/${id}`, { signal, decode: decodeCalendarEvent });
}
