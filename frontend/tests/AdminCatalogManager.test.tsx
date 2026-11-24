import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AdminCatalogManager from "@/components/AdminCatalogManager";

const auth = vi.hoisted(() => ({ headers: { "X-Admin-Token": "test" } }));
const onUnauthorized = vi.fn();

function jsonResponse(ok: boolean, body: unknown) {
  return { ok, status: ok ? 200 : 409, json: () => Promise.resolve(body) };
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const urlStr = String(url);
    if (urlStr.includes("/grades?")) {
      return jsonResponse(true, {
        items: [
          { id: 1, number: 6, title: "ششم دبستان", cycle_title: "ابتدایی", is_active: true },
        ],
        total: 1,
        page: 1,
        page_size: 25,
      });
    }
    if (urlStr.includes("/cycles?")) return jsonResponse(true, { items: [{ id: 1, title: "ابتدایی" }], total: 1, page: 1, page_size: 200 });
    if (urlStr.endsWith("/grades/1/dependencies")) {
      return jsonResponse(true, { dependencies: { books: 3, links: 5 }, total: 8 });
    }
    if (urlStr.endsWith("/grades/1") && init?.method === "DELETE") {
      return jsonResponse(false, {
        detail: "این پایه به ۸ رکورد وابسته متصل است (books: 3، links: 5). حذف دائمی مجاز نیست — از آرشیو/غیرفعال‌سازی استفاده کنید.",
      });
    }
    return jsonResponse(true, { deleted: true });
  });
  vi.stubGlobal("fetch", fetchMock);
});

describe("AdminCatalogManager — grades module", () => {
  it("loads and renders the entity list with Persian columns", async () => {
    render(<AdminCatalogManager kind="grades" authHeaders={auth.headers} onUnauthorized={onUnauthorized} />);
    await waitFor(() => expect(screen.getByText("ششم دبستان")).toBeInTheDocument());
    expect(screen.getByText("مدیریت پایه‌ها و کلاس‌ها")).toBeInTheDocument();
    expect(screen.getByText("دوره")).toBeInTheDocument();
  });

  it("opens the create form, submits via AJAX and refreshes without reload", async () => {
    render(<AdminCatalogManager kind="grades" authHeaders={auth.headers} onUnauthorized={onUnauthorized} />);
    const user = userEvent.setup();
    await waitFor(() => expect(screen.getByText("ششم دبستان")).toBeInTheDocument());
    await user.click(screen.getByText("افزودن"));
    expect(screen.getByText("افزودن رکورد جدید")).toBeInTheDocument();
    await user.type(screen.getByLabelText(/عنوان/), "پایهٔ جدید تست");
    await user.click(screen.getByText("ذخیره"));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url, init]) => String(url).endsWith("/grades") && (init as RequestInit | undefined)?.method === "POST")).toBe(true)
    );
    expect(screen.getByText("تغییرات ذخیره شد و در کل درسیار اعمال می‌شود.")).toBeInTheDocument();
  });

  it("shows dependency counts in the delete confirm and blocks destructive delete", async () => {
    render(<AdminCatalogManager kind="grades" authHeaders={auth.headers} onUnauthorized={onUnauthorized} />);
    const user = userEvent.setup();
    await waitFor(() => expect(screen.getByText("ششم دبستان")).toBeInTheDocument());
    await user.click(screen.getByLabelText("حذف"));
    await waitFor(() => expect(screen.getByText("تأیید حذف")).toBeInTheDocument());
    expect(screen.getByText(/books: 3/)).toBeInTheDocument();
    await user.click(screen.getByText("حذف دائمی"));
    await waitFor(() => expect(screen.getByText(/وابسته متصل است/)).toBeInTheDocument());
    // the row is still there — nothing was destroyed
    expect(screen.getByText("ششم دبستان")).toBeInTheDocument();
  });

  it("surfaces the archive action for archivable entities", async () => {
    render(<AdminCatalogManager kind="grades" authHeaders={auth.headers} onUnauthorized={onUnauthorized} />);
    await waitFor(() => expect(screen.getByText("ششم دبستان")).toBeInTheDocument());
    expect(screen.getByLabelText("آرشیو")).toBeInTheDocument();
  });

  it("routes 401 to onUnauthorized", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: false, status: 401, json: () => Promise.resolve({ detail: "unauthorized" }) }))
    );
    render(<AdminCatalogManager kind="grades" authHeaders={auth.headers} onUnauthorized={onUnauthorized} />);
    await waitFor(() => expect(onUnauthorized).toHaveBeenCalled());
  });
});
