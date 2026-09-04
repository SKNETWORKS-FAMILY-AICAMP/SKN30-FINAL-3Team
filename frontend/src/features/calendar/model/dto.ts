/**
 * 캘린더 일정 CRUD의 서버 계약.
 *
 * 경로와 필드의 정본은 `backend/src/api/calendar.py`와 그 응답 스키마다. Time Keeper의 DTO를
 * 가져다 쓰지 않는다 — 두 기능이 같은 데이터를 다른 형태로 보여주더라도 계약을 바꾸는 주체가
 * 다르므로, 한쪽 화면 사정으로 필드가 늘거나 줄 때 다른 쪽이 조용히 끌려가지 않게 한다.
 */

/**
 * 일정의 종류. **열거형으로 좁히지 않는다.** 사용자가 직접 고르거나 입력하는 값이다.
 *
 * `timeKeeper`의 `AgendaCategory`와 같은 이유(서버는 검증만 하고 어휘는 화면이 정한다)로 여기도
 * 문자열이다.
 */
export type CalendarCategory = string;

/** 화면이 기본으로 제안하는 종류. F1-SC-05 권장 어휘를 그대로 쓴다. 직접 입력도 허용한다. */
export const KNOWN_CALENDAR_CATEGORIES = ["임장", "계약", "잔금", "이사", "기타"] as const;

/** 서버가 `category`를 생략한 요청에 채우는 기본값. 화면은 이 값을 직접 보내지 않는다. */
export const DEFAULT_CALENDAR_CATEGORY = "기타";

export interface CalendarEventDto {
  id: number;
  title: string;
  category: CalendarCategory;
  /** ISO 날짜(YYYY-MM-DD). */
  event_date: string;
  /** HH:MM:SS. 종일 일정이면 null. */
  start_time: string | null;
  end_time: string | null;
  location: string | null;
  memo: string | null;
  created_by: number | null;
  row_version: number;
}

export interface CalendarEventListDto {
  items: CalendarEventDto[];
  from_date: string;
  to_date: string;
}

export interface CalendarEventCreateInput {
  title: string;
  category: CalendarCategory;
  event_date: string;
  start_time?: string | null;
  end_time?: string | null;
  location?: string | null;
  memo?: string | null;
}

export interface CalendarEventUpdateInput {
  row_version: number;
  title?: string;
  category?: CalendarCategory;
  event_date?: string;
  start_time?: string | null;
  end_time?: string | null;
  location?: string | null;
  memo?: string | null;
}
