import { APP_ENV } from "../../../config/env.ts";
import { mockJudgmentApi } from "./mock.ts";
import { request } from "../../../shared/api/index.ts";
import type { AnchorType } from "../model/dto.ts";
import { decodeDetail, decodePage, decodeTarget } from "./model.ts";
import type { ResultFilter } from "./model.ts";
export interface ListQuery {
  anchor_type: AnchorType;
  filter: ResultFilter;
  q?: string;
  assignee_id?: number;
  complex_id?: number;
  trade_type?: string;
  cursor?: string;
  limit?: number;
}
const httpJudgmentApi = {
  list: (query: ListQuery, signal?: AbortSignal) =>
    request("/f3/judgment-results", {
      query: { ...query },
      signal,
      decode: decodePage,
    }),
  target: (type: AnchorType, id: number, signal?: AbortSignal) =>
    request(`/f3/judgment-targets/${type}/${id}`, {
      signal,
      decode: decodeTarget,
    }),
  detail: (
    id: number,
    query: { candidate_id?: number; cursor?: string } = {},
    signal?: AbortSignal,
  ) =>
    request(`/f3/judgment-results/${id}`, {
      query: { ...query, limit: 20 },
      signal,
      decode: decodeDetail,
    }),
};

export const judgmentApi =
  APP_ENV.f3Source === "api" ? httpJudgmentApi : mockJudgmentApi;
