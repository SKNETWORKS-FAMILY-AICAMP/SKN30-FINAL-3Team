/**
 * 사용할 캘린더 transport 결정.
 *
 * F3와 같은 이유(ADR-005)로 장부 출처와 독립 스위치를 둔다. `VITE_CALENDAR_SOURCE`를 지정하지
 * 않으면 장부 출처를 따른다.
 */

import { APP_ENV } from "../../../config/env.ts";
import { mockTransport } from "../mock/mockTransport.ts";
import { httpTransport } from "./httpTransport.ts";
import type { CalendarTransport } from "./transport.ts";

export const calendarTransport: CalendarTransport =
  APP_ENV.calendarSource === "api" ? httpTransport : mockTransport;
