import { renderHook, act, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { useStudentHomeData } from "@/lib/useStudentHomeData";

// The hook must only call existing user-scoped endpoints through the provider's
// authFetch (which attaches the session token) and must degrade per source.
const authState = vi.hoisted(() => ({ fetcher: vi.fn() }));
vi.mock("@/components/AppProvider", () => ({
  useAppContext: () => ({ authFetch: authState.fetcher }),
}));

function jsonResponse(ok: boolean, body: unknown): { ok: boolean; json: () => Promise<unknown> } {
  return { ok, json: () => Promise.resolve(body) };
}

const DUE = { due_count: 7, cards: [] };
const DECKS = [{ id: 1, title: "کارت‌ها", due: 3, total: 12 }];
// Real API envelope (GET /api/v1/notebooks -> {"items": [...]}, same as the
// notebook workspace reads); the home hook must parse it, not a bare array.
const NOTEBOOKS = { items: [{ id: 5, title: "دفترچهٔ فیزیک", book_id: 3, block_count: 2 }] };
const MISTAKES = { items: [], total: 4 };

beforeEach(() => {
  authState.fetcher = vi.fn(async (url: string) => {
    if (url.includes("/flashcards/due")) return jsonResponse(true, DUE);
    if (url.includes("/flashcards/decks")) return jsonResponse(true, DECKS);
    if (url.includes("/notebooks")) return jsonResponse(true, NOTEBOOKS);
    if (url.includes("/mistakes")) return jsonResponse(true, MISTAKES);
    return jsonResponse(false, {});
  });
});

describe("useStudentHomeData", () => {
  it("fetches only the sources enabled by the capability flags", async () => {
    renderHook(() => useStudentHomeData({ flashcardsEnabled: true, mistakeBankEnabled: false, notebookEnabled: false }));
    await waitFor(() => {
      expect(authState.fetcher).toHaveBeenCalledWith("/api/v1/flashcards/due?limit=1");
    });
    const urls = authState.fetcher.mock.calls.map((call) => call[0] as string);
    expect(urls.some((u) => u.includes("/mistakes"))).toBe(false);
    expect(urls.some((u) => u.includes("/notebooks"))).toBe(false);
    expect(urls.some((u) => u.includes("/flashcards/decks"))).toBe(true);
  });

  it("uses unresolved-mistake filter and returns real counts", async () => {
    const { result } = renderHook(() =>
      useStudentHomeData({ flashcardsEnabled: true, mistakeBankEnabled: true, notebookEnabled: true })
    );
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });
    expect(result.current.dueFlashcards).toBe(7);
    expect(result.current.openMistakes).toBe(4);
    expect(result.current.decks?.[0]).toEqual({ id: 1, title: "کارت‌ها", due: 3, total: 12 });
    expect(result.current.notebooks?.[0]?.title).toBe("دفترچهٔ فیزیک");
    expect(authState.fetcher).toHaveBeenCalledWith("/api/v1/mistakes?status=unresolved&limit=1");
  });

  it("degrades per source: a 500 on one endpoint never fabricates data for it", async () => {
    authState.fetcher = vi.fn(async (url: string) => {
      if (url.includes("/flashcards/due")) return jsonResponse(false, {});
      if (url.includes("/flashcards/decks")) return jsonResponse(true, DECKS);
      if (url.includes("/notebooks")) return jsonResponse(true, NOTEBOOKS);
      return jsonResponse(true, MISTAKES);
    });
    const { result } = renderHook(() =>
      useStudentHomeData({ flashcardsEnabled: true, mistakeBankEnabled: true, notebookEnabled: true })
    );
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });
    expect(result.current.dueFlashcards).toBeNull();
    expect(result.current.errors.due).toBe(true);
    expect(result.current.openMistakes).toBe(4);
    expect(result.current.errors.mistakes).toBe(false);
  });

  it("does not fetch anything when the user is anonymous (all flags off)", async () => {
    renderHook(() => useStudentHomeData({ flashcardsEnabled: false, mistakeBankEnabled: false, notebookEnabled: false }));
    await act(async () => {
      await Promise.resolve();
    });
    expect(authState.fetcher).not.toHaveBeenCalled();
  });

  it("treats a network throw as an error, not as data", async () => {
    authState.fetcher = vi.fn(async () => {
      throw new Error("offline");
    });
    const { result } = renderHook(() =>
      useStudentHomeData({ flashcardsEnabled: true, mistakeBankEnabled: false, notebookEnabled: false })
    );
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });
    expect(result.current.decks).toBeNull();
    expect(result.current.errors.decks).toBe(true);
    expect(result.current.errors.due).toBe(true);
  });
});
