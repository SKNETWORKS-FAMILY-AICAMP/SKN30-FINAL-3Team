/**
 * 월간 그리드 날짜 계산. React에 의존하지 않는 순수 함수만 둔다.
 *
 * PatternFly의 `CalendarMonth`는 날짜 하나만 고르는 date-picker라 하루에 여러 일정을 얹는
 * 그리드로 쓸 수 없다(`.agents/skills/frontend/references/decisions/ADR-008-calendar-month-grid.md`).
 * 그래서 이 화면은 네이티브 `Date`로 직접 그리드를 계산한다.
 */

const WEEKDAY_LABELS = ["일", "월", "화", "수", "목", "금", "토"] as const;

export function toIsoDate(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function startOfMonth(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), 1);
}

export function addMonths(date: Date, delta: number): Date {
  return new Date(date.getFullYear(), date.getMonth() + delta, 1);
}

export function monthLabel(date: Date): string {
  return `${date.getFullYear()}년 ${date.getMonth() + 1}월`;
}

export function weekdayLabels(): readonly string[] {
  return WEEKDAY_LABELS;
}

/**
 * 달력 한 화면에 그릴 날짜 전체. 이전·다음 달 날짜로 앞뒤를 채워 완전한 주 단위로 만든다.
 *
 * 일요일 시작이다. 그리드 칸 수는 달마다 5~6주로 다르며 여기서 그대로 계산해 화면이 다시
 * 어긋난 주 수를 만들지 않게 한다.
 */
export function monthGridDays(monthStart: Date): Date[] {
  const firstWeekday = monthStart.getDay();
  const gridStart = new Date(monthStart);
  gridStart.setDate(gridStart.getDate() - firstWeekday);

  const nextMonthStart = addMonths(monthStart, 1);
  const lastDayOfMonth = new Date(nextMonthStart);
  lastDayOfMonth.setDate(lastDayOfMonth.getDate() - 1);
  const trailingWeekday = lastDayOfMonth.getDay();
  const gridEnd = new Date(lastDayOfMonth);
  gridEnd.setDate(gridEnd.getDate() + (6 - trailingWeekday));

  const days: Date[] = [];
  for (let cursor = new Date(gridStart); cursor <= gridEnd; cursor.setDate(cursor.getDate() + 1)) {
    days.push(new Date(cursor));
  }
  return days;
}

/** 조회 범위. 그리드가 채운 이전·다음 달 날짜까지 포함해야 그 칸의 일정도 함께 뜬다. */
export function monthQueryRange(monthStart: Date): { from: string; to: string } {
  const days = monthGridDays(monthStart);
  return {
    from: toIsoDate(days[0] ?? monthStart),
    to: toIsoDate(days[days.length - 1] ?? monthStart),
  };
}
