/**
 * HTTP 경계.
 *
 * 네트워크 호출을 화면 곳곳에 흩뜨리지 않기 위해 요청·응답·오류·취소를 한곳에서 다룬다.
 * JSON 요청은 모두 이 함수를 지난다. 기능별 transport는 경로와 DTO만 알면 되고 Cookie,
 * CSRF 헤더, 상태 코드 분류와 취소 처리를 각자 다시 구현하지 않는다.
 *
 * `multipart/form-data`는 아직 여기서 다루지 않는다. F2 음성 업로드가 유일한 예외이며
 * 두 번째 사용처가 생기면 이 경계로 올린다.
 */

import { APP_ENV } from "../../config/env.ts";
import { DecodeError } from "../decode/index.ts";
import { ApiError, kindFromStatus } from "./errors.ts";
import { getCsrfToken } from "./session.ts";

export type QueryValue = string | number | boolean | null | undefined | readonly string[];

export interface RequestOptions<T> {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  query?: Record<string, QueryValue>;
  body?: unknown;
  signal?: AbortSignal | undefined;
  /** 응답 본문 검증기. 본문이 없는 응답에는 `expectNoContent`를 쓴다. */
  decode: (value: unknown) => T;
}

/** 본문 없는 응답(204)용 검증기. */
export function expectNoContent(): void {
  return undefined;
}

export async function request<T>(path: string, options: RequestOptions<T>): Promise<T> {
  const method = options.method ?? "GET";
  const url = buildUrl(path, options.query);

  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";

  // 상태 변경 요청은 CSRF 토큰을 요구한다(ADR-0002).
  if (method !== "GET") {
    const token = getCsrfToken();
    if (token != null) headers["X-CSRF-Token"] = token;
  }

  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers,
      // 세션 쿠키를 실어 보낸다. 이것이 없으면 모든 요청이 401이 된다.
      credentials: "include",
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal ?? null,
    });
  } catch (cause) {
    // fetch는 네트워크 실패와 취소만 throw한다. HTTP 오류 상태는 throw하지 않는다.
    if (isAbortError(cause)) {
      throw new ApiError({ kind: "canceled", message: "요청이 취소되었습니다.", cause });
    }
    throw new ApiError({ kind: "offline", message: "네트워크 요청에 실패했습니다.", cause });
  }

  if (!response.ok) throw await toApiError(response);

  if (response.status === 204) return options.decode(undefined);

  // HTTP 성공 여부와 JSON 파싱 가능 여부는 별개 문제다.
  const text = await response.text();
  if (text.trim() === "") return options.decode(undefined);

  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch (cause) {
    throw new ApiError({
      kind: "contract",
      message: "응답을 JSON으로 해석하지 못했습니다.",
      status: response.status,
      cause,
    });
  }

  try {
    return options.decode(parsed);
  } catch (cause) {
    if (cause instanceof DecodeError) {
      throw new ApiError({
        kind: "contract",
        message: `응답이 계약과 다릅니다. ${cause.message}`,
        status: response.status,
        cause,
      });
    }
    throw cause;
  }
}

function buildUrl(path: string, query?: Record<string, QueryValue>): string {
  const base = `${APP_ENV.apiBaseUrl.replace(/\/$/, "")}${path}`;
  if (query == null) return base;

  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value == null || value === "") continue;
    if (Array.isArray(value)) {
      for (const entry of value) params.append(key, entry);
    } else {
      params.append(key, String(value));
    }
  }

  const serialized = params.toString();
  return serialized === "" ? base : `${base}?${serialized}`;
}

function isAbortError(cause: unknown): boolean {
  return cause instanceof DOMException && cause.name === "AbortError";
}

/**
 * 오류 응답 본문에서 code/message/request_id를 최대한 건져낸다.
 * 본문이 계약을 따르지 않아도 상태 코드로 분류는 유지한다.
 */
async function toApiError(response: Response): Promise<ApiError> {
  const kind = kindFromStatus(response.status);
  let code: string | undefined;
  let requestId: string | undefined;
  let message = `요청이 실패했습니다 (HTTP ${response.status}).`;

  try {
    const body: unknown = await response.json();
    if (typeof body === "object" && body !== null) {
      const record = body as Record<string, unknown>;
      if (typeof record["code"] === "string") code = record["code"];
      if (typeof record["request_id"] === "string") requestId = record["request_id"];
      if (typeof record["message"] === "string") message = record["message"];
    }
  } catch {
    // 오류 응답이 JSON이 아닐 수 있다. 상태 코드 기반 분류만 사용한다.
  }

  return new ApiError({ kind, message, status: response.status, code, requestId });
}
