/**
 * 캘린더 경계 테스트.
 *
 * 화면을 띄우지 않고 세 가지만 본다. 서버 응답을 검증 없이 통과시키지 않는지, 월간 그리드
 * 날짜 계산이 주 단위를 완전히 채우는지, 그리고 캘린더 일정과 장부 읽기 전용 일정이 날짜별로
 * 제대로 갈리는지다.
 */

import assert from "node:assert/strict";
import test from "node:test";

import { decodeCalendarEvent, decodeCalendarEventList } from "../src/features/calendar/model/decode.ts";
import type { CalendarEventDto } from "../src/features/calendar/model/dto.ts";
import {
  addMonths,
  monthGridDays,
  monthLabel,
  monthQueryRange,
  startOfMonth,
  toIsoDate,
} from "../src/features/calendar/model/monthGrid.ts";
import { buildDayCells, eventChipLabel, ledgerChipLabel } from "../src/features/calendar/model/viewModel.ts";
import type { AgendaItemDto } from "../src/features/timeKeeper/model/dto.ts";

function event(overrides: Partial<CalendarEventDto> = {}): CalendarEventDto {
  return {
    id: 1,
    title: "행복아파트 임장",
    category: "임장",
    event_date: "2026-09-10",
    start_time: "14:00:00",
    end_time: "15:00:00",
    location: "행복아파트 101동",
    memo: null,
    created_by: 1,
    row_version: 1,
    ...overrides,
  };
}

function ledgerItem(overrides: Partial<AgendaItemDto> = {}): AgendaItemDto {
  return {
    category: "TENANCY_EXPIRY",
    due_date: "2026-09-12",
    days_until_due: 2,
    unit_id: 7,
    listing_id: null,
    complex_name: "헬리오시티",
    building_number: "101",
    unit_number: "1503",
    tenancy_status: "입주",
    requirement_id: null,
    demand_type: null,
    requirement_status: null,
    assigned_user_id: null,
    last_contact_at: null,
    contacts: [],
    event_id: null,
    title: null,
    location: null,
    ...overrides,
  };
}

test("계약과 다른 응답은 계약 오류로 올린다", () => {
  assert.throws(() => decodeCalendarEvent({ ...event(), row_version: "1" }), /row_version/);
  assert.throws(() => decodeCalendarEvent({ ...event(), title: 1 }), /title/);
  assert.throws(() => decodeCalendarEventList({ items: [], from_date: 1 }), /from_date/);
});

test("계약을 지킨 응답은 필드를 잃지 않고 통과한다", () => {
  const decoded = decodeCalendarEvent(event());

  assert.equal(decoded.title, "행복아파트 임장");
  assert.equal(decoded.category, "임장");
  assert.equal(decoded.start_time, "14:00:00");
  assert.equal(decoded.location, "행복아파트 101동");
});

test("서버가 열어 둔 종류 문자열은 좁히지 않는다", () => {
  // 서버가 새 기본값을 내려도(F2 연동 등) 화면이 죽지 않는다.
  assert.equal(decodeCalendarEvent(event({ category: "ETC" })).category, "ETC");
});

test("월간 그리드는 앞뒤를 채워 완전한 주 단위로 나온다", () => {
  const days = monthGridDays(new Date(2026, 8, 1)); // 2026-09-01은 화요일

  assert.equal(days.length % 7, 0);
  assert.equal(days[0]?.getDay(), 0);
  assert.equal(days[days.length - 1]?.getDay(), 6);
  assert.equal(toIsoDate(days[0]!), "2026-08-30");
});

test("월 이동은 일을 1일로 고정한다", () => {
  const next = addMonths(new Date(2026, 0, 31), 1);
  assert.equal(next.getMonth(), 1);
  assert.equal(next.getDate(), 1);
});

test("월 이름표는 연·월을 그대로 읽는다", () => {
  assert.equal(monthLabel(new Date(2026, 8, 1)), "2026년 9월");
});

test("조회 범위는 그리드가 채운 이전·다음 달 날짜까지 포함한다", () => {
  const range = monthQueryRange(startOfMonth(new Date(2026, 8, 15)));
  const days = monthGridDays(startOfMonth(new Date(2026, 8, 15)));

  assert.equal(range.from, toIsoDate(days[0]!));
  assert.equal(range.to, toIsoDate(days[days.length - 1]!));
});

test("날짜별로 캘린더 일정과 장부 일정을 따로 묶는다", () => {
  const days = [new Date(2026, 8, 10), new Date(2026, 8, 12)];
  const cells = buildDayCells(days, [event()], [ledgerItem()]);

  assert.equal(cells[0]?.date, "2026-09-10");
  assert.equal(cells[0]?.events.length, 1);
  assert.equal(cells[0]?.ledgerItems.length, 0);
  assert.equal(cells[1]?.date, "2026-09-12");
  assert.equal(cells[1]?.events.length, 0);
  assert.equal(cells[1]?.ledgerItems.length, 1);
});

test("칸 문구는 캘린더 일정에 시각을, 장부 일정에 종류·대상을 붙인다", () => {
  assert.equal(eventChipLabel(event()), "14:00 행복아파트 임장");
  assert.equal(eventChipLabel(event({ start_time: null })), "행복아파트 임장");
  assert.equal(ledgerChipLabel(ledgerItem()), "세대 임대차 만기 · 헬리오시티 101동 1503호");
});
