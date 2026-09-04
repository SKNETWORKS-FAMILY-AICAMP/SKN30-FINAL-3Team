/**
 * 캘린더 일정 데이터 출처의 공통 인터페이스.
 *
 * 화면과 훅은 이 인터페이스에만 의존한다. 실제 구현이 mock인지 HTTP인지 알지 못한다.
 */

import type {
  CalendarEventCreateInput,
  CalendarEventDto,
  CalendarEventListDto,
  CalendarEventUpdateInput,
} from "../model/dto.ts";

export interface CalendarEventRange {
  /** ISO 날짜(YYYY-MM-DD), 포함. */
  from: string;
  /** ISO 날짜(YYYY-MM-DD), 포함. */
  to: string;
}

export interface CalendarTransport {
  listEvents(range: CalendarEventRange, signal?: AbortSignal): Promise<CalendarEventListDto>;
  createEvent(input: CalendarEventCreateInput, signal?: AbortSignal): Promise<CalendarEventDto>;
  updateEvent(
    eventId: number,
    input: CalendarEventUpdateInput,
    signal?: AbortSignal,
  ): Promise<CalendarEventDto>;
  deleteEvent(eventId: number, rowVersion: number, signal?: AbortSignal): Promise<void>;
}
