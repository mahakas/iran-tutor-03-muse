import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AdminUsersPanel from "@/components/AdminUsersPanel";
import AdminCatalogManager from "@/components/AdminCatalogManager";
import AdminObservabilityPanel from "@/components/AdminObservabilityPanel";
import AdminPodcastsPanel from "@/components/AdminPodcastsPanel";

/**
 * Phase 06 URL contract: every admin list keeps its working context
 * (search/filter/sort/page) in the URL — read back on mount and mirrored on
 * change, so refresh and shared links restore the exact view. The browser QA
 * exercises the same contract end-to-end; these tests pin the unit behavior.
 */

type Handler = (init: RequestInit, url: string) => unknown;

function installFetch(handlers: Record<string, Handler>) {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const method = init.method ?? "GET";
      calls.push(`${method} ${url}`);
      const handler = handlers[`${method} ${url.split("?")[0]}`];
      if (!handler) {
        return new Response(JSON.stringify({ detail: `unhandled ${url}` }), { status: 404 });
      }
      const result = handler(init, url);
      if (result instanceof Response) return result;
      return new Response(JSON.stringify(result), { status: 200, headers: { "Content-Type": "application/json" } });
    })
  );
  return calls;
}

function setUrl(path: string) {
  window.history.replaceState(null, "", path);
}

const EMPTY_SUMMARY = {
  days: 7,
  totals: { calls: 0, tokens_in: 0, tokens_out: 0, estimated_cost_usd: 0, errors: 0, flagged: 0 },
  by_feature: {},
  by_day: {},
  by_user: {},
};

beforeEach(() => {
  setUrl("/admin");
});

afterEach(() => {
  vi.unstubAllGlobals();
  setUrl("/admin");
});

describe("Phase 06 URL contract — filters survive refresh", () => {
  it("AdminUsersPanel reads q/status/page back from the URL on mount", async () => {
    setUrl("/admin?tab=users&q=%D8%B9%D9%84%DB%8C&status=inactive&page=3");
    const calls = installFetch({
      "GET /api/v1/admin/users/roles": () => ({ roles: [], actor: { role: "admin", rank: 50, legacy: false } }),
      "GET /api/v1/admin/users": () => ({ users: [], pagination: null, summary: null }),
    });
    render(<AdminUsersPanel authHeaders={{}} onUnauthorized={vi.fn()} />);
    await waitFor(() => expect(calls.some((c) => c.startsWith("GET /api/v1/admin/users?"))).toBe(true));
    const listCall = calls.find((c) => c.startsWith("GET /api/v1/admin/users?"))!;
    expect(listCall).toContain("page=3");
    expect(listCall).toContain("status=inactive");
    expect(encodeURIComponent("علی")).toBe(listCall.match(/q=([^&]+)/)?.[1] ?? "");
    // the search input is prefilled with the restored query
    const search = document.querySelector<HTMLInputElement>("input[type='search'], input[placeholder]");
    expect(search?.value).toBe("علی");
  });

  it("AdminCatalogManager restores page/q/sort from the URL and mirrors changes back", async () => {
    setUrl("/admin/education/grades?page=2&q=%D9%87%D8%B4%D8%AA%D9%85&sort=number&direction=desc");
    const calls = installFetch({
      "GET /api/v1/admin/catalog/cycles": () => ({ items: [], total: 0 }),
      "GET /api/v1/admin/catalog/grades": () => ({ items: [], total: 0 }),
    });
    render(<AdminCatalogManager kind="grades" authHeaders={{}} onUnauthorized={vi.fn()} />);
    await waitFor(() => expect(calls.some((c) => c.includes("catalog/grades?"))).toBe(true));
    const listCall = calls.find((c) => c.includes("catalog/grades?"))!;
    expect(listCall).toContain("page=2");
    expect(listCall).toContain("q=");
    expect(listCall).toContain("sort=number");
    expect(listCall).toContain("direction=desc");
    // the same context is mirrored back into the URL (refresh-safe)
    await waitFor(() => {
      expect(window.location.search).toContain("page=2");
      expect(window.location.search).toContain("q=");
      expect(window.location.search).toContain("sort=number");
      expect(window.location.search).toContain("direction=desc");
    });
  });

  it("AdminObservabilityPanel restores feature/page/days from the URL and keeps them on navigation", async () => {
    setUrl("/admin?tab=observability&feature=quiz&page=1&days=30");
    const calls = installFetch({
      "GET /api/v1/admin/audit-logs": () => ({ items: [], total: 0, limit: 25, offset: 25 }),
      "GET /api/v1/admin/audit-logs/summary": () => EMPTY_SUMMARY,
    });
    render(<AdminObservabilityPanel authHeaders={{}} onUnauthorized={vi.fn()} />);
    await waitFor(() => expect(calls.some((c) => c.startsWith("GET /api/v1/admin/audit-logs?"))).toBe(true));
    const listCall = calls.find((c) => c.startsWith("GET /api/v1/admin/audit-logs?"))!;
    expect(listCall).toContain("feature_key=quiz");
    expect(listCall).toContain("offset=25");
    expect(calls.some((c) => c.includes("summary?days=30"))).toBe(true);
    await waitFor(() => {
      expect(window.location.search).toContain("feature=quiz");
      expect(window.location.search).toContain("page=1");
      expect(window.location.search).toContain("days=30");
    });
  });

  it("AdminPodcastsPanel renders real stats, syncs the status filter into the URL and shows an honest empty state", async () => {
    setUrl("/admin?tab=podcasts");
    const calls = installFetch({
      "GET /api/v1/admin/podcasts/stats": () => ({
        total_episodes: 2,
        by_status: { completed: 1, failed: 1 },
        completed: 1,
        failed: 1,
        storage_bytes: 2048,
        total_duration_seconds: 125.5,
        avg_processing_seconds: 42.0,
        model_usage: { "test-model": 2 },
        ai_calls: 9,
        tokens_in: 1200,
        tokens_out: 800,
        regenerations: 1,
        feedback: { liked: 1, disliked: 0, reason_counts: {} },
      }),
      "GET /api/v1/admin/podcasts/episodes": () => ({ items: [] }),
    });
    render(<AdminPodcastsPanel authHeaders={{}} onUnauthorized={vi.fn()} />);
    expect(await screen.findByText(/کل اپیزودها/)).toBeInTheDocument();
    expect(screen.getByText("۲").textContent).toBeTruthy(); // کل اپیزودها = ۲ (عدد واقعی API)
    expect(await screen.findByText(/اپیزودی با این فیلتر ثبت نشده است/)).toBeInTheDocument();

    // Status filter is written to the URL and re-fetched server-side.
    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText(/وضعیت/), "failed");
    await waitFor(() => expect(window.location.search).toContain("status=failed"));
    await waitFor(() => expect(calls.filter((c) => c.includes("episodes?")).length).toBeGreaterThan(1));
    expect(
      calls.some((c) => c.includes("/api/v1/admin/podcasts/episodes") && c.includes("status=failed"))
    ).toBe(true);
  });

  it("AdminPodcastsPanel restores a persisted status filter from the URL", async () => {
    setUrl("/admin?tab=podcasts&status=failed");
    const calls = installFetch({
      "GET /api/v1/admin/podcasts/stats": () => ({
        total_episodes: 0,
        by_status: {},
        completed: 0,
        failed: 0,
        storage_bytes: 0,
        total_duration_seconds: 0,
        avg_processing_seconds: null,
        model_usage: {},
        ai_calls: 0,
        tokens_in: 0,
        tokens_out: 0,
        regenerations: 0,
        feedback: { liked: 0, disliked: 0, reason_counts: {} },
      }),
      "GET /api/v1/admin/podcasts/episodes": () => ({ items: [] }),
    });
    render(<AdminPodcastsPanel authHeaders={{}} onUnauthorized={vi.fn()} />);
    await waitFor(() =>
      expect(calls.some((c) => c.includes("/api/v1/admin/podcasts/episodes") && c.includes("status=failed"))).toBe(true)
    );
    const select = screen.getByLabelText(/وضعیت/).querySelector("select") ?? screen.getByLabelText(/وضعیت/);
    expect((select as HTMLSelectElement).value).toBe("failed");
  });
});
