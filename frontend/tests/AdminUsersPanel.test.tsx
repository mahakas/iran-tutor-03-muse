import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AdminUsersPanel from "@/components/AdminUsersPanel";
import { clearCsrfMemo } from "@/lib/apiClient";

const STUDENT = {
  id: "u-1",
  phone_number: "09120000001",
  full_name: "زهرا کریمی",
  first_name: "زهرا",
  last_name: "کریمی",
  role: "student",
  is_active: true,
  is_deleted: false,
  has_password: true,
  plan_code: "trial",
  plan_title: "هدیه ثبت‌نام",
  tokens_remaining: 1200,
  tokens_total: 5000,
  tokens_used_total: 3800,
  tokens_used_today: 120,
  grade_level: 12,
  major: "experimental",
  created_at: "2026-01-05T10:00:00Z",
  last_login_at: "2026-02-01T08:00:00Z",
  days_remaining: 12,
  is_expired: false,
};

const OTHER = { ...STUDENT, id: "u-2", phone_number: "09120000002", full_name: "علی صادقی", role: "teacher" };

const LIST_PAYLOAD = {
  users: [STUDENT, OTHER],
  pagination: { page: 1, page_size: 20, total: 2, total_pages: 1, has_next: false, has_prev: false },
  summary: { total_users: 2, active_users: 2, deleted_users: 0, paid_users: 0, roles: { student: 1, teacher: 1, admin: 0, super_admin: 0 } },
};

const ROLES_PAYLOAD = {
  roles: [
    { code: "student", rank: 10, assignable: true },
    { code: "teacher", rank: 30, assignable: true },
    { code: "moderator", rank: 40, assignable: true },
    { code: "admin", rank: 50, assignable: true },
    { code: "super_admin", rank: 60, assignable: false },
  ],
  actor: { role: "admin", rank: 50, legacy: false },
};

type Handler = (init: RequestInit, url: string) => unknown;

function installFetch(handlers: Record<string, Handler>) {
  const calls: { url: string; method: string; body: unknown; headers: Record<string, string> }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const method = init.method ?? "GET";
      calls.push({
        url,
        method,
        body: init.body ? JSON.parse(String(init.body)) : undefined,
        headers: (init.headers ?? {}) as Record<string, string>,
      });
      const key = `${method} ${url.split("?")[0]}`;
      const handler = handlers[key] ?? handlers[`${method} /api/v1/admin/users`];
      if (!handler) {
        return new Response(JSON.stringify({ detail: `unhandled ${key}` }), { status: 404 });
      }
      const result = handler(init, url);
      if (result instanceof Response) return result;
      return new Response(JSON.stringify(result), { status: 200, headers: { "Content-Type": "application/json" } });
    })
  );
  return calls;
}

function renderPanel(onUnauthorized = vi.fn()) {
  render(<AdminUsersPanel authHeaders={{}} onUnauthorized={onUnauthorized} />);
  return { onUnauthorized };
}

const baseHandlers = (): Record<string, Handler> => ({
  "GET /api/v1/admin/users/roles": () => ROLES_PAYLOAD,
  "GET /api/v1/admin/users": () => LIST_PAYLOAD,
  "GET /api/v1/admin/users/u-1/sessions": () => ({ sessions: [] }),
  "GET /api/v1/admin/users/u-1/audit": () => ({ entries: [] }),
});

describe("AdminUsersPanel", () => {
  beforeEach(() => {
    clearCsrfMemo();
    vi.restoreAllMocks();
    document.cookie = "iran_tutor_csrf=csrf-abc";
    window.history.replaceState(null, "", "/admin?tab=users");
  });

  it("lists users with role + quota columns and no reload", async () => {
    installFetch(baseHandlers());
    renderPanel();

    expect(await screen.findByText("09120000001")).toBeInTheDocument();
    expect(screen.getByText("زهرا کریمی")).toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(within(table).getByText("معلم")).toBeInTheDocument();
    // Filters stay visible after the AJAX load (no full-page navigation).
    expect(screen.getByLabelText("جستجوی کاربران")).toBeInTheDocument();
  });

  it("keeps search + page in the URL and refetches when the query changes", async () => {
    const user = userEvent.setup();
    const calls = installFetch(baseHandlers());
    renderPanel();

    await screen.findByText("09120000001");
    await user.type(screen.getByLabelText("جستجوی کاربران"), "کریمی{Enter}");

    await waitFor(() => expect(calls.some((call) => call.url.includes("q=%DA%A9%D8%B1%DB%8C%D9%85%DB%8C"))).toBe(true));
    expect(decodeURIComponent(window.location.search)).toContain("q=کریمی");

    await user.selectOptions(screen.getByLabelText("وضعیت"), "inactive");
    await waitFor(() => expect(calls.some((call) => call.url.includes("status=inactive"))).toBe(true));
    expect(window.location.search).toContain("status=inactive");
  });

  it("shows a Persian server error inline instead of crashing", async () => {
    installFetch({
      ...baseHandlers(),
      "GET /api/v1/admin/users": () =>
        new Response(JSON.stringify({ detail: "دسترسی به فهرست کاربران مجاز نیست." }), { status: 403 }),
    });
    renderPanel();

    expect(await screen.findByRole("alert")).toHaveTextContent("دسترسی به فهرست کاربران مجاز نیست.");
  });

  it("locks the panel on 401 from any admin call", async () => {
    installFetch({
      ...baseHandlers(),
      "GET /api/v1/admin/users": () => new Response(JSON.stringify({ detail: "expired" }), { status: 401 }),
    });
    const onUnauthorized = vi.fn();
    render(<AdminUsersPanel authHeaders={{}} onUnauthorized={onUnauthorized} />);

    await waitFor(() => expect(onUnauthorized).toHaveBeenCalled());
  });

  it("requires confirmation and re-auth before changing a role, then revokes nothing on the client", async () => {
    const user = userEvent.setup();
    const calls = installFetch({
      ...baseHandlers(),
      "PUT /api/v1/admin/users/u-1/role": () => ({
        user: { ...STUDENT, role: "teacher" },
        sessions_revoked: true,
      }),
    });
    renderPanel();

    await screen.findByText("09120000001");
    await user.click(screen.getAllByRole("button", { name: /مدیریت/ })[0]);
    await screen.findByText(/پروندهٔ کاربر/);

    const roleSelect = screen.getByLabelText("تغییر نقش");
    await user.selectOptions(roleSelect, "teacher");

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("تغییر نقش کاربر")).toBeInTheDocument();
    // Re-auth field is mandatory before the mutation can run.
    const confirmButton = within(dialog).getByRole("button", { name: "اعمال نقش جدید" });
    expect(confirmButton).toBeDisabled();

    await user.type(within(dialog).getByLabelText("رمز عبور مدیر (تأیید هویت)"), "AdminPass1");
    await user.click(confirmButton);

    await waitFor(() =>
      expect(calls.some((call) => call.method === "PUT" && call.url === "/api/v1/admin/users/u-1/role")).toBe(true)
    );
    const roleCall = calls.find((call) => call.url === "/api/v1/admin/users/u-1/role");
    expect(roleCall?.body).toEqual({ role: "teacher" });
    expect(roleCall?.headers["X-Reauth-Password"]).toBe("AdminPass1");
    expect(roleCall?.headers["X-CSRF-Token"]).toBe("csrf-abc");
  });

  it("does not send a destructive delete until the admin confirms", async () => {
    const user = userEvent.setup();
    const calls = installFetch({
      ...baseHandlers(),
      "DELETE /api/v1/admin/users/u-1": () => ({ deleted: true, mode: "soft", revoked_sessions: 2 }),
    });
    renderPanel();

    await screen.findByText("09120000001");
    await user.click(screen.getAllByRole("button", { name: /مدیریت/ })[0]);
    await user.click(await screen.findByRole("button", { name: /حذف حساب/ }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("حذف حساب کاربر")).toBeInTheDocument();
    expect(calls.some((call) => call.method === "DELETE")).toBe(false);

    await user.click(within(dialog).getByRole("button", { name: "انصراف" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(calls.some((call) => call.method === "DELETE")).toBe(false);
  });

  it("only offers roles the backend marked as assignable", async () => {
    const user = userEvent.setup();
    installFetch(baseHandlers());
    renderPanel();

    await screen.findByText("09120000001");
    await user.click(screen.getByRole("button", { name: /کاربر جدید/ }));

    const roleSelects = screen.getAllByRole("combobox");
    const createRole = roleSelects[roleSelects.length - 1];
    const options = within(createRole).getAllByRole("option").map((option) => option.textContent);
    expect(options).toContain("دانش‌آموز");
    expect(options).toContain("مدیر");
    expect(options).not.toContain("مدیر ارشد");
  });

  it("adjusts quotas through PUT /credits and reports success inline", async () => {
    const user = userEvent.setup();
    const calls = installFetch({
      ...baseHandlers(),
      "PUT /api/v1/admin/users/u-1/credits": () => ({
        user: { ...STUDENT, tokens_remaining: 6200, tokens_total: 10000 },
      }),
    });
    renderPanel();

    await screen.findByText("09120000001");
    await user.click(screen.getAllByRole("button", { name: /مدیریت/ })[0]);
    await user.click(await screen.findByRole("tab", { name: "سهمیه و اعتبار" }));

    await user.type(await screen.findByLabelText("افزودن / کسر توکن"), "5000");
    await user.click(screen.getByRole("button", { name: /ذخیرهٔ سهمیه و اعتبار/ }));

    await waitFor(() => expect(calls.some((call) => call.url.endsWith("/credits") && call.method === "PUT")).toBe(true));
    expect(await screen.findByText(/سهمیه و اعتبار کاربر به‌روزرسانی شد/)).toBeInTheDocument();
  });
});
