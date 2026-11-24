import { describe, expect, it, vi, beforeEach } from "vitest";
import {
  ApiError,
  apiRequest,
  clearCsrfMemo,
  describeApiError,
  detailToMessage,
  ensureCsrfToken,
  SESSION_EXPIRED_EVENT,
} from "@/lib/apiClient";

function jsonResponse(body: unknown, init: { status?: number; headers?: Record<string, string> } = {}) {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
  });
}

describe("apiClient", () => {
  beforeEach(() => {
    clearCsrfMemo();
    vi.restoreAllMocks();
  });

  it("attaches the CSRF token from the cookie to mutating requests", async () => {
    document.cookie = "iran_tutor_csrf=cookie-token";
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);

    await apiRequest("/api/v1/admin/users", { method: "POST", body: { role: "student" } });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/admin/users");
    expect((init as RequestInit).headers).toMatchObject({
      "X-CSRF-Token": "cookie-token",
      "Content-Type": "application/json",
    });
    expect(String((init as RequestInit).body)).toBe('{"role":"student"}');
  });

  it("obtains a token from /auth/csrf when no cookie exists yet", async () => {
    const fetchMock = vi.fn(async (url: string, _init?: RequestInit) => {
      if (url === "/api/v1/auth/csrf") return jsonResponse({ csrf_token: "fresh-token" });
      return jsonResponse({ ok: true });
    });
    vi.stubGlobal("fetch", fetchMock);

    await apiRequest("/api/v1/account/profile", { method: "PUT", body: {} });

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "/api/v1/auth/csrf",
      "/api/v1/account/profile",
    ]);
    const headers = (fetchMock.mock.calls[1][1] as RequestInit).headers as Record<string, string>;
    expect(headers["X-CSRF-Token"]).toBe("fresh-token");
  });

  it("skips CSRF for public endpoints when told to", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ token: "t" }));
    vi.stubGlobal("fetch", fetchMock);

    await apiRequest("/api/v1/auth/login", {
      method: "POST",
      body: { phone_number: "09123456789", password: "secret123" },
      csrf: false,
    });

    const headers = (fetchMock.mock.calls[0][1] as RequestInit).headers as Record<string, string>;
    expect(headers["X-CSRF-Token"]).toBeUndefined();
  });

  it("maps a 401 to an unauthorized error and broadcasts the expiry event", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "نشست منقضی شده است." }, { status: 401 })));
    const listener = vi.fn();
    window.addEventListener(SESSION_EXPIRED_EVENT, listener);

    await expect(apiRequest("/api/v1/account/profile")).rejects.toMatchObject({
      kind: "unauthorized",
      status: 401,
      message: "نشست منقضی شده است.",
    });
    expect(listener).toHaveBeenCalledTimes(1);
    window.removeEventListener(SESSION_EXPIRED_EVENT, listener);
  });

  it("keeps 403/422 semantics distinct and exposes field errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(jsonResponse({ detail: "دسترسی مجاز نیست." }, { status: 403 }))
        .mockResolvedValueOnce(
          jsonResponse(
            { detail: [{ loc: ["body", "phone_number"], msg: "شماره موبایل نامعتبر است." }] },
            { status: 422 }
          )
        )
    );

    const forbidden = await apiRequest("/api/v1/admin/users").catch((error) => error);
    expect(forbidden).toBeInstanceOf(ApiError);
    expect((forbidden as ApiError).kind).toBe("forbidden");

    const invalid = await apiRequest("/api/v1/auth/register/request-otp", { csrf: false }).catch((error) => error);
    expect((invalid as ApiError).kind).toBe("validation");
    expect((invalid as ApiError).fieldErrors).toEqual({ phone_number: "شماره موبایل نامعتبر است." });
    expect((invalid as ApiError).message).toBe("phone_number: شماره موبایل نامعتبر است.");
  });

  it("reports server failures with the Persian fallback when detail is missing", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(() => Promise.resolve(new Response("", { status: 500 })))
    );
    const error = await apiRequest("/api/v1/admin/users", { method: "DELETE" }).catch((cause) => cause);
    expect((error as ApiError).kind).toBe("server");
    expect((error as ApiError).message).toBe("درخواست انجام نشد. دوباره تلاش کنید.");
  });

  it("collapses duplicate concurrent mutations into one request", async () => {
    // A CSRF token is already known, so both calls go straight to the mutation URL.
    document.cookie = "iran_tutor_csrf=cookie-token";
    let release: (value: Response) => void = () => {};
    const pending = new Promise<Response>((resolve) => {
      release = resolve;
    });
    const fetchMock = vi.fn().mockImplementation(() => pending);
    vi.stubGlobal("fetch", fetchMock);

    const first = apiRequest("/api/v1/admin/users/x/activation", { method: "PUT", body: { is_active: true } });
    const second = apiRequest("/api/v1/admin/users/x/activation", { method: "PUT", body: { is_active: true } });

    // `ensureCsrfToken` is async, so let the first call reach `fetch` before asserting.
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    release(jsonResponse({ ok: true }));
    await expect(Promise.all([first, second])).resolves.toEqual([{ ok: true }, { ok: true }]);
  });

  it("reports network failures instead of throwing a raw TypeError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const error = await apiRequest("/api/v1/admin/users", { method: "POST", body: {} }).catch((cause) => cause);
    expect((error as ApiError).kind).toBe("network");
    expect(describeApiError(error)).toContain("اتصال به سرور");
  });

  it("memoizes the token handed back by the API", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ csrf_token: "rotated-token" })));
    await apiRequest("/api/v1/auth/me");
    const token = await ensureCsrfToken();
    expect(token).toBe("rotated-token");
  });

  it("formats FastAPI detail payloads", () => {
    expect(detailToMessage({ detail: "پیام" }, "fallback")).toBe("پیام");
    expect(detailToMessage({ detail: [{ loc: ["body", "password"], msg: "too short" }] }, "fallback")).toBe(
      "password: too short"
    );
    expect(detailToMessage(null, "fallback")).toBe("fallback");
  });
});
