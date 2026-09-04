/**
 * 백엔드 없이 캘린더 화면을 확인하기 위한 메모리 데이터.
 *
 * `ledger`의 mock과 같은 방침이다 — 서버가 돌려줄 409·422를 그대로 흉내 내고, 만든 응답도 실제
 * decoder를 통과시킨다(ADR-005). 날짜는 오늘 기준 상대값으로 만든다. 고정하면 며칠만 지나도
 * 월간 뷰의 "이번 달" 데모가 빈 화면이 된다.
 */

import { APP_ENV } from "../../../config/env.ts";
import { ApiError } from "../../../shared/api/index.ts";
import { decodeCalendarEvent } from "../model/decode.ts";
import type { CalendarTransport } from "../api/transport.ts";
import type { CalendarEventDto } from "../model/dto.ts";

function isoDate(offsetDays: number): string {
  const moment = new Date();
  moment.setHours(12, 0, 0, 0);
  moment.setDate(moment.getDate() + offsetDays);
  return moment.toISOString().slice(0, 10);
}

function seed(): CalendarEventDto[] {
  return [
    {
      id: 1,
      title: "행복아파트 임장",
      category: "임장",
      event_date: isoDate(3),
      start_time: "14:00:00",
      end_time: "15:00:00",
      location: "행복아파트 101동",
      memo: null,
      created_by: 1,
      row_version: 1,
    },
    {
      id: 2,
      title: "사무소 회의",
      category: "기타",
      event_date: isoDate(9),
      start_time: null,
      end_time: null,
      location: null,
      memo: "월간 실적 공유",
      created_by: 1,
      row_version: 1,
    },
  ].map((event) => decodeCalendarEvent(event));
}

let state: CalendarEventDto[] = seed();
let nextId = 3;

async function delay(signal?: AbortSignal): Promise<void> {
  const ms = APP_ENV.mockLatencyMs;
  if (ms <= 0) return;
  await new Promise<void>((resolve, reject) => {
    const onAbort = () => {
      clearTimeout(timer);
      reject(new ApiError({ kind: "canceled", message: "요청이 취소되었습니다." }));
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

function requireEvent(eventId: number): CalendarEventDto {
  const found = state.find((entry) => entry.id === eventId);
  if (found == null) {
    throw new ApiError({ kind: "notFound", message: "대상 일정을 찾지 못했습니다.", status: 404 });
  }
  return found;
}

function assertVersion(current: number, incoming: number): void {
  if (incoming !== current) {
    throw new ApiError({
      kind: "conflict",
      message: "다른 사용자가 먼저 저장했습니다.",
      status: 409,
      code: "ROW_VERSION_CONFLICT",
    });
  }
}

function assertTimeRange(startTime: string | null, endTime: string | null): void {
  if (startTime != null && endTime != null && endTime < startTime) {
    throw new ApiError({ kind: "validation", message: "종료 시각은 시작 시각보다 빠를 수 없습니다." });
  }
}

export const mockTransport: CalendarTransport = {
  async listEvents(range, signal) {
    await delay(signal);
    const items = state
      .filter((event) => event.event_date >= range.from && event.event_date <= range.to)
      .sort((left, right) => left.event_date.localeCompare(right.event_date) || left.id - right.id);
    return structuredClone({ items, from_date: range.from, to_date: range.to });
  },

  async createEvent(input, signal) {
    await delay(signal);
    const title = input.title.trim();
    if (title === "") {
      throw new ApiError({ kind: "validation", message: "제목을 입력해 주세요." });
    }
    const startTime = input.start_time ?? null;
    const endTime = input.end_time ?? null;
    assertTimeRange(startTime, endTime);

    const created: CalendarEventDto = {
      id: nextId++,
      title,
      category: input.category,
      event_date: input.event_date,
      start_time: startTime,
      end_time: endTime,
      location: input.location ?? null,
      memo: input.memo ?? null,
      created_by: 1,
      row_version: 1,
    };
    state = [...state, created];
    return structuredClone(created);
  },

  async updateEvent(eventId, input, signal) {
    await delay(signal);
    const current = requireEvent(eventId);
    assertVersion(current.row_version, input.row_version);

    const startTime = input.start_time === undefined ? current.start_time : input.start_time;
    const endTime = input.end_time === undefined ? current.end_time : input.end_time;
    assertTimeRange(startTime, endTime);

    const updated: CalendarEventDto = {
      ...current,
      title: input.title ?? current.title,
      category: input.category ?? current.category,
      event_date: input.event_date ?? current.event_date,
      start_time: startTime,
      end_time: endTime,
      location: input.location === undefined ? current.location : input.location,
      memo: input.memo === undefined ? current.memo : input.memo,
      row_version: current.row_version + 1,
    };
    state = state.map((entry) => (entry.id === eventId ? updated : entry));
    return structuredClone(updated);
  },

  async deleteEvent(eventId, rowVersion, signal) {
    await delay(signal);
    const current = requireEvent(eventId);
    assertVersion(current.row_version, rowVersion);
    state = state.filter((entry) => entry.id !== eventId);
  },
};
