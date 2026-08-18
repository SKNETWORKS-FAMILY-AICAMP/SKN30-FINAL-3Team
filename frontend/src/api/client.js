/**
 * CSRF 토큰은 `features/ledger/api/session.ts`가 단일 보관소다.
 * 여기에 별도 보관소를 두면 인증 흐름(AuthContext)이 채운 토큰을 장부 요청이 못 보고
 * 모든 쓰기가 403이 된다. 그래서 저장은 위임하고 이 모듈은 인증 호출만 담당한다.
 */
import { APP_ENV } from "../config/env.ts";
import { getCsrfToken, setCsrfToken } from "../features/ledger/api/session.ts";

export { getCsrfToken, setCsrfToken };

// 인증 경로도 장부 요청과 같은 API 기본 경로를 쓴다(env.ts).
const API_BASE = APP_ENV.apiBaseUrl.replace(/\/$/, "");

export async function apiFetch(endpoint, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...(getCsrfToken() ? { "X-CSRF-Token": getCsrfToken() } : {}),
    ...options.headers,
  };

  const config = {
    credentials: "include",
    ...options,
    headers,
  };

  const response = await fetch(endpoint, config);

  if (!response.ok) {
    let errorData = null;
    try {
      errorData = await response.json();
    } catch {
      // response text is not JSON
    }
    const error = new Error(
      errorData?.message || `HTTP ${response.status}: ${response.statusText}`
    );
    error.status = response.status;
    error.code = errorData?.code;
    throw error;
  }

  if (response.status === 204) {
    return null;
  }

  return response.json();
}

export async function fetchCurrentUser() {
  return apiFetch(`${API_BASE}/auth/me`);
}

export async function loginDevelopmentSession() {
  const data = await apiFetch(`${API_BASE}/auth/development-session`, {
    method: "POST",
  });
  if (data?.csrf_token) {
    setCsrfToken(data.csrf_token);
  }
  return data;
}

export async function logoutSession() {
  await apiFetch(`${API_BASE}/auth/session`, {
    method: "DELETE",
  });
  setCsrfToken(null);
}
