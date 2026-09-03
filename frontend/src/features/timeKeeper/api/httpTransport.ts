/**
 * 실제 Backend를 호출하는 Time Keeper transport.
 *
 * 경로와 응답 형태의 정본은 `backend/src/api/time_keeper.py`다. 조회 전용이라 CSRF 토큰이
 * 필요 없고, Cookie·상태 코드 분류·취소는 `shared/api`의 `request()`가 처리한다.
 */

import { request } from "../../../shared/api/index.ts";
import { decodeAgendaPage } from "../model/decode.ts";
import type { TimeKeeperTransport } from "./transport.ts";

const PATHS = {
  agenda: "/time-keeper/agenda",
} as const;

export const httpTransport: TimeKeeperTransport = {
  async listAgenda(query, signal) {
    return request(PATHS.agenda, {
      // 지정하지 않은 값은 보내지 않는다. 서버 기본값이 정본이고 화면이 그것을 복제하지 않는다.
      query: {
        within_days: query.withinDays,
        overdue_days: query.overdueDays,
        recontact_days: query.recontactDays,
        revalidation_days: query.revalidationDays,
        per_category_limit: query.perCategoryLimit,
        limit: query.limit,
        offset: query.offset,
      },
      signal,
      decode: (value) => decodeAgendaPage(value),
    });
  },
};
