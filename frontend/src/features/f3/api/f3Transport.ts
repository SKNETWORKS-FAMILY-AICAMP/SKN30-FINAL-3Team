/**
 * 사용할 F3 transport 결정.
 *
 * `frontend/.env`의 `VITE_F3_SOURCE`로 고른다. 지정하지 않으면 장부 출처를 따른다.
 * Backend는 살아 있어도 `WORKER_ENABLED=false`이면 실행이 `QUEUED`에 머무르므로, 완료 화면을
 * 확인할 때는 장부를 `api`로 둔 채 F3만 `mock`으로 내린다.
 */

import { APP_ENV } from "../../../config/env.ts";
import { mockTransport } from "../mock/mockTransport.ts";
import { httpTransport } from "./httpTransport.ts";
import type { F3Transport } from "./transport.ts";

export const f3Transport: F3Transport =
  APP_ENV.f3Source === "api" ? httpTransport : mockTransport;
