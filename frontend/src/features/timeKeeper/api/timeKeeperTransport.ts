/**
 * 사용할 Time Keeper transport 결정.
 *
 * 일정 목록은 F1 장부의 값을 그대로 읽는 조회이므로 장부 출처를 따른다. F3처럼 별도 스위치를
 * 두지 않는 이유는 가용성이 갈리는 지점이 없기 때문이다. 장부 API가 살아 있으면 이 조회도
 * 살아 있고, Worker나 모델에 의존하지 않는다.
 */

import { APP_ENV } from "../../../config/env.ts";
import { mockTransport } from "../mock/mockTransport.ts";
import { httpTransport } from "./httpTransport.ts";
import type { TimeKeeperTransport } from "./transport.ts";

export const timeKeeperTransport: TimeKeeperTransport =
  APP_ENV.ledgerSource === "api" ? httpTransport : mockTransport;
