/**
 * Fetch wrapper for every client-side mutation (hotfix 2026-11-22).
 *
 * Why a wrapper instead of raw `fetch` in each component:
 *  - one place that normalizes HTTP/validation errors into Persian messages
 *  - one place that attaches the CSRF token for cookie-based sessions
 *  - one place that reacts to 401 (session expired) by notifying listeners
 *  - automatic in-flight de-duplication so double clicks cannot double-submit
 *  - optional optimistic `abort` on route change
 *
 * It never replaces server-side validation: the backend stays authoritative and the
 * messages it returns are shown verbatim.
 */

export const CSRF_COOKIE = "iran_tutor_csrf";
export const SESSION_EXPIRED_EVENT = "darsyar:session-expired";

export type ApiErrorKind =
  | "network"
  | "unauthorized"
  | "forbidden"
  | "validation"
  | "conflict"
  | "rate_limited"
  | "reauth_required"
  | "server"
  | "unknown";

export class ApiError extends Error {
  readonly status: number;
  readonly kind: ApiErrorKind;
  readonly payload: unknown;
  readonly retryAfterSeconds?: number;
  readonly fieldErrors?: Record<string, string>;

  constructor(
    message: string,
    options: {
      status?: number;
      kind?: ApiErrorKind;
      payload?: unknown;
      retryAfterSeconds?: number;
      fieldErrors?: Record<string, string>;
    } = {}
  ) {
    super(message);
    this.name = "ApiError";
    this.status = options.status ?? 0;
    this.kind = options.kind ?? "unknown";
    this.payload = options.payload;
    this.retryAfterSeconds = options.retryAfterSeconds;
    this.fieldErrors = options.fieldErrors;
  }
}

function kindFor(status: number): ApiErrorKind {
  if (status === 401) return "unauthorized";
  if (status === 403) return "forbidden";
  if (status === 404) return "conflict";
  if (status === 409) return "conflict";
  if (status === 422) return "validation";
  if (status === 428) return "reauth_required";
  if (status === 429) return "rate_limited";
  if (status >= 500) return "server";
  return "unknown";
}

/** FastAPI returns `detail` as a string or a list of `{loc, msg}` objects. */
export function detailToMessage(payload: unknown, fallback: string): string {
  const detail = (payload as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (typeof item === "string") return item;
        const record = item as { msg?: unknown; loc?: unknown };
        const loc = Array.isArray(record.loc) ? record.loc.filter((p) => p !== "body").join(".") : "";
        const msg = typeof record.msg === "string" ? record.msg : "";
        return [loc, msg].filter(Boolean).join(": ");
      })
      .filter(Boolean);
    if (parts.length) return parts.join(" · ");
  }
  return fallback;
}

function fieldErrorsFrom(payload: unknown): Record<string, string> | undefined {
  const detail = (payload as { detail?: unknown } | null)?.detail;
  if (!Array.isArray(detail)) return undefined;
  const map: Record<string, string> = {};
  for (const item of detail) {
    const record = item as { loc?: unknown; msg?: unknown };
    if (!Array.isArray(record.loc)) continue;
    const field = record.loc.filter((p) => p !== "body").join(".");
    if (field && typeof record.msg === "string") map[field] = record.msg;
  }
  return Object.keys(map).length ? map : undefined;
}

export function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const prefix = `${name}=`;
  for (const chunk of document.cookie.split(";")) {
    const value = chunk.trim();
    if (value.startsWith(prefix)) return decodeURIComponent(value.slice(prefix.length));
  }
  return null;
}

let csrfMemo: string | null = null;

export function rememberCsrfToken(token: string | null | undefined): void {
  if (token) csrfMemo = token;
}

export function currentCsrfToken(): string | null {
  return csrfMemo ?? readCookie(CSRF_COOKIE);
}

export function clearCsrfMemo(): void {
  csrfMemo = null;
}

/** Ensure a CSRF token exists (the API hands one out with `/auth/me` and `/auth/csrf`). */
export async function ensureCsrfToken(): Promise<string | null> {
  const existing = currentCsrfToken();
  if (existing) return existing;
  try {
    const response = await fetch("/api/v1/auth/csrf", {
      credentials: "same-origin",
      cache: "no-store",
    });
    const payload = (await response.json().catch(() => ({}))) as { csrf_token?: string };
    if (payload.csrf_token) {
      rememberCsrfToken(payload.csrf_token);
      return payload.csrf_token;
    }
  } catch {
    // The mutation will still be attempted; the server decides.
  }
  return currentCsrfToken();
}

export function notifySessionExpired(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(SESSION_EXPIRED_EVENT));
}

export type ApiRequestOptions = {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  headers?: Record<string, string>;
  /** Extra headers such as `X-Reauth-Password` for sensitive admin operations. */
  extraHeaders?: Record<string, string>;
  signal?: AbortSignal;
  /** Set to false to skip CSRF handling (login/registration endpoints). */
  csrf?: boolean;
  /** De-duplicate identical in-flight mutations (default true for non-GET). */
  dedupe?: boolean;
  fallbackMessage?: string;
};

const inFlight = new Map<string, Promise<unknown>>();

function dedupeKey(method: string, url: string, body: unknown): string {
  let serialized = "";
  try {
    serialized = body === undefined ? "" : JSON.stringify(body);
  } catch {
    serialized = String(body);
  }
  return `${method}:${url}:${serialized}`;
}

/**
 * Perform a JSON request. Resolves with the parsed body, rejects with `ApiError`.
 * A 401 also dispatches `darsyar:session-expired` so the app can drop its state once.
 */
export async function apiRequest<T = unknown>(
  url: string,
  options: ApiRequestOptions = {}
): Promise<T> {
  const method = options.method ?? "GET";
  const mutating = method !== "GET";
  const fallback = options.fallbackMessage ?? "درخواست انجام نشد. دوباره تلاش کنید.";
  const useDedupe = options.dedupe ?? mutating;

  const run = async (): Promise<T> => {
    const headers: Record<string, string> = { Accept: "application/json", ...(options.headers ?? {}) };
    if (options.body !== undefined) headers["Content-Type"] = "application/json";
    if (mutating && options.csrf !== false) {
      const token = await ensureCsrfToken();
      if (token) headers["X-CSRF-Token"] = token;
    }
    for (const [key, value] of Object.entries(options.extraHeaders ?? {})) {
      if (value) headers[key] = value;
    }

    let response: Response;
    try {
      response = await fetch(url, {
        method,
        cache: "no-store",
        credentials: "same-origin",
        headers,
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
        signal: options.signal,
      });
    } catch (error) {
      if ((error as Error)?.name === "AbortError") throw error;
      throw new ApiError("اتصال به سرور برقرار نشد. وضعیت شبکه را بررسی کنید.", {
        kind: "network",
        payload: error,
      });
    }

    const text = await response.text();
    let payload: unknown = null;
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch {
        payload = text;
      }
    }

    if (response.ok) {
      const token = (payload as { csrf_token?: string } | null)?.csrf_token;
      if (typeof token === "string") rememberCsrfToken(token);
      return payload as T;
    }

    const retryAfter = Number(response.headers.get("retry-after") ?? "") || undefined;
    const kind = kindFor(response.status);
    if (response.status === 401) notifySessionExpired();
    throw new ApiError(detailToMessage(payload, fallback), {
      status: response.status,
      kind,
      payload,
      retryAfterSeconds: retryAfter,
      fieldErrors: fieldErrorsFrom(payload),
    });
  };

  if (!useDedupe) return run();
  const key = dedupeKey(method, url, options.body);
  const existing = inFlight.get(key) as Promise<T> | undefined;
  if (existing) return existing;
  const promise = run().finally(() => {
    inFlight.delete(key);
  });
  inFlight.set(key, promise as Promise<unknown>);
  return promise;
}

export const api = {
  get: <T>(url: string, options?: Omit<ApiRequestOptions, "method" | "body">) =>
    apiRequest<T>(url, { ...options, method: "GET" }),
  post: <T>(url: string, body?: unknown, options?: Omit<ApiRequestOptions, "method" | "body">) =>
    apiRequest<T>(url, { ...options, method: "POST", body }),
  put: <T>(url: string, body?: unknown, options?: Omit<ApiRequestOptions, "method" | "body">) =>
    apiRequest<T>(url, { ...options, method: "PUT", body }),
  patch: <T>(url: string, body?: unknown, options?: Omit<ApiRequestOptions, "method" | "body">) =>
    apiRequest<T>(url, { ...options, method: "PATCH", body }),
  delete: <T>(url: string, body?: unknown, options?: Omit<ApiRequestOptions, "method" | "body">) =>
    apiRequest<T>(url, { ...options, method: "DELETE", body }),
};

/** Persian label for an error, including the coarse category for non-`detail` failures. */
export function describeApiError(error: unknown, fallback = "خطای نامشخص"): string {
  if (error instanceof ApiError) {
    if (error.kind === "rate_limited" && error.retryAfterSeconds) {
      return `${error.message} (${error.retryAfterSeconds} ثانیه دیگر)`;
    }
    return error.message || fallback;
  }
  if (error instanceof Error) return error.message || fallback;
  return fallback;
}
