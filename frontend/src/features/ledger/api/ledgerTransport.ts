/**
 * 사용할 transport 결정.
 *
 * DB·백엔드가 준비되면 `frontend/.env.local`의 `VITE_LEDGER_SOURCE`를 `api`로 바꾸는 것으로 전환한다.
 * 화면과 훅은 이 선택을 알지 못한다.
 */

import { APP_ENV } from "../../../config/env.ts";
import { mockTransport } from "../mock/mockTransport.ts";
import { httpTransport } from "./httpTransport.ts";
import type { LedgerTransport } from "./transport.ts";

export const ledgerTransport: LedgerTransport =
  APP_ENV.ledgerSource === "api" ? httpTransport : mockTransport;
