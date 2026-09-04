/**
 * 캘린더 일정 응답 런타임 검증.
 *
 * `timeKeeper/model/decode.ts`와 같은 방침이다. 외부 라이브러리 없이 `shared/decode`의 원시
 * 검증기만으로 조립한다. `category`는 서버가 열거형으로 고정하지 않으므로 좁히지 않는다.
 */

import {
  asArray,
  asNullableNumber,
  asNullableString,
  asNumber,
  asRecord,
  asString,
} from "../../../shared/decode/index.ts";
import type { CalendarEventDto, CalendarEventListDto } from "./dto.ts";

export function decodeCalendarEvent(value: unknown, path = "event"): CalendarEventDto {
  const row = asRecord(value, path);
  return {
    id: asNumber(row["id"], `${path}.id`),
    title: asString(row["title"], `${path}.title`),
    category: asString(row["category"], `${path}.category`),
    event_date: asString(row["event_date"], `${path}.event_date`),
    start_time: asNullableString(row["start_time"], `${path}.start_time`),
    end_time: asNullableString(row["end_time"], `${path}.end_time`),
    location: asNullableString(row["location"], `${path}.location`),
    memo: asNullableString(row["memo"], `${path}.memo`),
    created_by: asNullableNumber(row["created_by"], `${path}.created_by`),
    row_version: asNumber(row["row_version"], `${path}.row_version`),
  };
}

export function decodeCalendarEventList(value: unknown): CalendarEventListDto {
  const page = asRecord(value, "calendarEvents");
  return {
    items: asArray(page["items"], "calendarEvents.items").map((entry, index) =>
      decodeCalendarEvent(entry, `calendarEvents.items[${index}]`),
    ),
    from_date: asString(page["from_date"], "calendarEvents.from_date"),
    to_date: asString(page["to_date"], "calendarEvents.to_date"),
  };
}
