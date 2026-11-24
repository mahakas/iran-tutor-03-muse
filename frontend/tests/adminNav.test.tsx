import { render, act, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import AdminSideNav, {
  ADMIN_NAV_CATEGORIES,
  ADMIN_TAB_KEYS,
  parseAdminTabParam,
} from "@/components/AdminSideNav";

// The mobile toggle echoes the active item's label, so plain getByText would match
// it too — nav-item queries are always scoped to the sidenav element.
function nav() {
  const el = document.getElementById("admin-side-nav");
  expect(el).not.toBeNull();
  return within(el as HTMLElement);
}

function toggleButton(): HTMLButtonElement {
  return document.querySelector<HTMLButtonElement>(".admin-nav-toggle")!;
}

describe("parseAdminTabParam (?tab= URL contract)", () => {
  it("accepts every registered tab key", () => {
    for (const key of ADMIN_TAB_KEYS) {
      expect(parseAdminTabParam(key)).toBe(key);
    }
  });

  it("falls back to the default tab for unknown or missing values", () => {
    expect(parseAdminTabParam(null)).toBe("books");
    expect(parseAdminTabParam(undefined)).toBe("books");
    expect(parseAdminTabParam("")).toBe("books");
    expect(parseAdminTabParam("does-not-exist")).toBe("books");
    // injection-ish values must never become a tab
    expect(parseAdminTabParam("books?x=1")).toBe("books");
  });

  it("keeps every tab reachable from exactly one category (no dead/duplicate nav)", () => {
    const items = ADMIN_NAV_CATEGORIES.flatMap((category) => category.items);
    const keys = items.map((item) => item.key).sort();
    expect(keys).toEqual([...ADMIN_TAB_KEYS].sort());
    expect(new Set(keys).size).toBe(keys.length);
    for (const item of items) {
      expect(item.label.length).toBeGreaterThan(0);
      expect(item.icon).toBeTruthy();
    }
  });
});

describe("AdminSideNav", () => {
  it("renders the phase-01 category taxonomy", () => {
    render(<AdminSideNav active="overview" onSelect={vi.fn()} />);
    const scope = nav();
    for (const category of ADMIN_NAV_CATEGORIES) {
      expect(scope.getByText(category.title)).toBeInTheDocument();
    }
    // representative items from different categories
    expect(scope.getByText("نمای کلی، سلامت و تراکنش‌ها")).toBeInTheDocument();
    expect(scope.getByText("کتاب‌ها و پردازش PDF")).toBeInTheDocument();
    expect(scope.getByText("کاربران و سهمیه‌ها")).toBeInTheDocument();
    expect(scope.getByText("پلن‌ها و قیمت توکن")).toBeInTheDocument();
    expect(scope.getByText("پادکست‌های آموزشی")).toBeInTheDocument();
  });

  it("every tab is a real anchor to its /admin?tab= URL (deep-linkable, refresh-safe)", () => {
    render(<AdminSideNav active="overview" onSelect={vi.fn()} />);
    const scope = nav();
    for (const key of ADMIN_TAB_KEYS) {
      const link = scope.getByText(
        ADMIN_NAV_CATEGORIES.flatMap((c) => c.items).find((i) => i.key === key)!.label
      ).closest("a")!;
      expect(link).toHaveAttribute("href", `/admin?tab=${key}`);
    }
    // the standalone education route keeps its own URL
    expect(scope.getByText(/مدیریت نظام آموزشی/).closest("a")).toHaveAttribute("href", "/admin/education");
  });

  it("marks the active tab from its prop (sourced from the URL by the page)", () => {
    render(<AdminSideNav active="users" onSelect={vi.fn()} />);
    const scope = nav();
    const active = scope.getByText("کاربران و سهمیه‌ها").closest("a")!;
    expect(active).toHaveClass("active");
    expect(active).toHaveAttribute("aria-current", "page");
    const other = scope.getByText("پلن‌ها و قیمت توکن").closest("a")!;
    expect(other).not.toHaveClass("active");
  });

  it("reports selections so the page can push ?tab=", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<AdminSideNav active="overview" onSelect={onSelect} />);
    await user.click(nav().getByText("مرکز شفافیت (Observability)").closest("a")!);
    expect(onSelect).toHaveBeenCalledWith("observability");
  });

  it("opens the mobile drawer and closes it on Escape", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<AdminSideNav active="overview" onSelect={onSelect} />);
    const toggle = toggleButton();
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    act(() => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });
});
