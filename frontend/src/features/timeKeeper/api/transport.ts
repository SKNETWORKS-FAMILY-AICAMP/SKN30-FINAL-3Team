/**
 * 일정 데이터 출처의 공통 인터페이스.
 *
 * 화면과 훅은 이 인터페이스에만 의존한다. 실제 구현이 mock인지 HTTP인지 알지 못한다.
 */

import type { AgendaPageDto } from "../model/dto.ts";

export interface AgendaQuery {
  /** 앞으로 며칠까지 볼지. 서버 기본값은 90일(F1-AL-01의 3개월). */
  withinDays?: number;
  /** 이미 지난 기한을 며칠까지 함께 볼지. 서버 기본값은 7일. */
  overdueDays?: number;
  /** 마지막 접촉 후 며칠이면 재연락 대상으로 볼지. 서버 기본값은 30일. */
  recontactDays?: number;
  /** 매물 접수 후 며칠이면 조건 재확인 대상으로 볼지. 서버 기본값은 30일. */
  revalidationDays?: number;
  /** 한 종류에서 실을 최대 건수. 서버 기본값은 3건. */
  perCategoryLimit?: number;
  limit?: number;
  offset?: number;
}

export interface TimeKeeperTransport {
  listAgenda(query: AgendaQuery, signal?: AbortSignal): Promise<AgendaPageDto>;
}
