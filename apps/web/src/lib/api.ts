const MUTATING_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string | Record<string, unknown> | unknown[] | null;

  constructor(status: number, detail: string | Record<string, unknown> | unknown[] | null, message?: string) {
    super(message ?? (typeof detail === "string" ? detail : `Request failed (${status})`));
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export interface ApiResult<T> {
  data: T | null;
  error: ApiError | null;
  response: Response | null;
}

type RequestOptions = Omit<RequestInit, "body"> & {
  body?: unknown | URLSearchParams | FormData;
  skipCsrfBootstrap?: boolean;
};

let csrfBootstrapPromise: Promise<void> | null = null;

function getCookieValue(name: string): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  if (!match) {
    return null;
  }
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return match[1];
  }
}

async function ensureCsrfCookie(): Promise<void> {
  if (getCookieValue("csrf_token")) {
    return;
  }
  if (!csrfBootstrapPromise) {
    csrfBootstrapPromise = fetch("/login", { credentials: "include" })
      .then(() => undefined)
      .finally(() => {
        csrfBootstrapPromise = null;
      });
  }
  await csrfBootstrapPromise;
}

async function parseErrorDetail(response: Response): Promise<string | Record<string, unknown> | unknown[] | null> {
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    try {
      const payload = (await response.json()) as { detail?: unknown; error?: unknown; message?: unknown };
      if (typeof payload.detail === "string") {
        return payload.detail;
      }
      if (payload.detail !== undefined) {
        return payload.detail as Record<string, unknown> | unknown[];
      }
      if (typeof payload.error === "string") {
        return payload.error;
      }
      if (typeof payload.message === "string") {
        return payload.message;
      }
      return payload as Record<string, unknown>;
    } catch {
      return null;
    }
  }
  try {
    const text = await response.text();
    return text || null;
  } catch {
    return null;
  }
}

export async function apiRequest<T>(url: string, options: RequestOptions = {}): Promise<ApiResult<T>> {
  const method = (options.method ?? "GET").toUpperCase();
  const headers = new Headers(options.headers);

  if (
    options.body !== undefined &&
    !(options.body instanceof FormData) &&
    !(options.body instanceof URLSearchParams)
  ) {
    if (!headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
  }

  if (MUTATING_METHODS.has(method)) {
    if (!options.skipCsrfBootstrap) {
      await ensureCsrfCookie();
    }
    const csrfToken = getCookieValue("csrf_token");
    if (csrfToken) {
      headers.set("X-CSRF-Token", csrfToken);
    }
  }

  let body: BodyInit | undefined;
  if (options.body instanceof FormData || options.body instanceof URLSearchParams) {
    body = options.body;
  } else if (options.body !== undefined) {
    body = JSON.stringify(options.body);
  }

  try {
    const response = await fetch(url, {
      ...options,
      method,
      headers,
      body,
      credentials: "include",
    });

    if (!response.ok) {
      const detail = await parseErrorDetail(response);
      return {
        data: null,
        error: new ApiError(response.status, detail),
        response,
      };
    }

    if (response.status === 204) {
      return { data: null as T, error: null, response };
    }

    const contentType = response.headers.get("content-type") ?? "";
    if (contentType.includes("application/json")) {
      const data = (await response.json()) as T;
      return { data, error: null, response };
    }

    const text = (await response.text()) as unknown as T;
    return { data: text, error: null, response };
  } catch (cause) {
    const message = cause instanceof Error ? cause.message : "Network request failed";
    return {
      data: null,
      error: new ApiError(0, message, message),
      response: null,
    };
  }
}

export const api = {
  get<T>(url: string, options?: RequestOptions) {
    return apiRequest<T>(url, { ...options, method: "GET" });
  },
  post<T>(url: string, body?: unknown, options?: RequestOptions) {
    return apiRequest<T>(url, { ...options, method: "POST", body });
  },
  put<T>(url: string, body?: unknown, options?: RequestOptions) {
    return apiRequest<T>(url, { ...options, method: "PUT", body });
  },
  patch<T>(url: string, body?: unknown, options?: RequestOptions) {
    return apiRequest<T>(url, { ...options, method: "PATCH", body });
  },
  delete<T>(url: string, options?: RequestOptions) {
    return apiRequest<T>(url, { ...options, method: "DELETE" });
  },
};

export interface AuthProfile {
  id: string;
  username: string;
  email: string | null;
  role: string;
  is_superuser: boolean;
  can_access_observability: boolean;
  mfa_enabled: boolean;
  processing_restricted: boolean;
  has_preferences: boolean;
  preferences_url: string;
  created_at: string | null;
  subscription: Record<string, unknown> | null;
  plan: Record<string, unknown> | null;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  refresh_token?: string;
  mfa_required?: boolean;
  mfa_token?: string;
}

export async function login(username: string, password: string): Promise<ApiResult<LoginResponse>> {
  const form = new URLSearchParams();
  form.set("username", username);
  form.set("password", password);

  return apiRequest<LoginResponse>("/api/v1/auth/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: form,
    skipCsrfBootstrap: true,
  });
}

export async function logout(): Promise<ApiResult<{ detail: string }>> {
  return api.post<{ detail: string }>("/api/v1/auth/logout");
}

export async function fetchCurrentUser(): Promise<ApiResult<AuthProfile>> {
  return api.get<AuthProfile>("/api/v1/auth/me");
}
