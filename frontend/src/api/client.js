let csrfToken = null;

export function setCsrfToken(token) {
  csrfToken = token;
}

export function getCsrfToken() {
  return csrfToken;
}

export async function apiFetch(endpoint, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}),
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
  return apiFetch("/api/v1/auth/me");
}

export async function loginDevelopmentSession() {
  const data = await apiFetch("/api/v1/auth/development-session", {
    method: "POST",
  });
  if (data?.csrf_token) {
    setCsrfToken(data.csrf_token);
  }
  return data;
}

export async function logoutSession() {
  await apiFetch("/api/v1/auth/session", {
    method: "DELETE",
  });
  setCsrfToken(null);
}
