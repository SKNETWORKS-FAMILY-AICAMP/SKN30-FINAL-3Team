/**
 * 월간 그리드 한 칸에 얹을 항목 계산.
 *
 * 캘린더 일정(편집 가능)과 Time Keeper가 읽는 장부 파생 일정(편집 불가)을 날짜별로 묶는다.
 * 장부 파생 일정의 표시 문구는 `timeKeeper`가 소유한 뷰모델을 그대로 쓴다 — 같은 데이터를
 * "다가오는 일정"과 캘린더가 다른 말로 부르지 않게 한다.
 *
 * `timeKeeper`의 배럴(`index.ts`)이 아니라 순수 뷰모델 파일을 직접 가져온다. 배럴은
 * `TimeKeeperNotification.tsx`(JSX)까지 함께 내보내 이 파일처럼 React 없이 도는 순수 계산에
 * 끌어오면 안 된다 — `shared/api`가 `errors.ts`를 배럴과 따로 두는 것과 같은 이유(ADR-004).
 */

import {
  agendaCategoryLabel,
  agendaTargetLabel,
} from "../../timeKeeper/model/viewModel.ts";
import type { AgendaItemDto } from "../../timeKeeper/model/dto.ts";
import type { CalendarEventDto } from "./dto.ts";
import { toIsoDate } from "./monthGrid.ts";

export interface DayCell {
  date: string;
  /** 사용자가 캘린더에서 만든, 편집 가능한 일정. */
  events: CalendarEventDto[];
  /** 장부에서 계산한, 편집 불가능한 일정. */
  ledgerItems: AgendaItemDto[];
}

/**
 * `ledgerItems`는 이미 캘린더 갈래(`event_id != null`)를 뺀 것을 받는다.
 *
 * Time Keeper의 "다가오는 일정" 응답은 캘린더 일정도 함께 담아 오므로, 여기서 또 얹으면 같은
 * 일정이 두 번 그려진다. `events`(이 화면의 직접 조회)가 그 자리를 이미 채운다.
 */
export function buildDayCells(
  days: readonly Date[],
  events: readonly CalendarEventDto[],
  ledgerItems: readonly AgendaItemDto[],
): DayCell[] {
  return days.map((day) => {
    const date = toIsoDate(day);
    return {
      date,
      events: events.filter((event) => event.event_date === date),
      ledgerItems: ledgerItems.filter((item) => item.due_date === date),
    };
  });
}

/** 칸에 그릴 짧은 줄. 캘린더 일정은 시각(있으면)과 제목, 장부 일정은 종류와 대상. */
export function eventChipLabel(event: CalendarEventDto): string {
  const time = event.start_time == null ? null : event.start_time.slice(0, 5);
  return time == null ? event.title : `${time} ${event.title}`;
}

export function ledgerChipLabel(item: AgendaItemDto): string {
  return `${agendaCategoryLabel(item.category)} · ${agendaTargetLabel(item)}`;
}
