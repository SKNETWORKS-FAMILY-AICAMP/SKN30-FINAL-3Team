/**
 * 사용할 transport 결정.
 *
 * 개인 로컬에서 API를 연결할 때는 `frontend/.env`의 `VITE_LEDGER_SOURCE`를 `api`로
 * override한다. 공유 기본값은 `frontend/.env.local`이 소유한다.
 * 화면과 훅은 이 선택을 알지 못한다.
 */

import { APP_ENV } from "../../../config/env.ts";
import { mockTransport } from "../mock/mockTransport.ts";
import { httpTransport } from "./httpTransport.ts";
import type { LedgerTransport } from "./transport.ts";

export const ledgerTransport: LedgerTransport =
  APP_ENV.ledgerSource === "api" ? httpTransport : mockTransport;
