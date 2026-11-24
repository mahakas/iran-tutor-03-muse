import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DeepSolveWorkspace from "@/components/DeepSolveWorkspace";
import type { DeepSolveSession } from "@/lib/phase5";

const authFetchMock = vi.hoisted(() => vi.fn());

vi.mock("@/components/AppProvider", () => ({
  useAppContext: () => ({ authFetch: (input: string, init?: RequestInit) => authFetchMock(input, init) }),
}));

vi.mock("@/components/BookGradePicker", () => ({
  default: () => <div data-testid="book-picker" />,
}));

function jsonResponse(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
}

function session(overrides: Partial<DeepSolveSession>): DeepSolveSession {
  return {
    id: "ds-1",
    problem_text: "مسئلهٔ حرکت",
    topic: "سرعت متوسط",
    subject: "فیزیک",
    book_id: 5,
    chapter_number: 1,
    status: "active",
    total_steps: 2,
    current_step: 0,
    steps: [
      { index: 0, title: "گام یک", state: "current" },
      { index: 1, title: "گام دو", state: "pending" },
    ],
    available_actions: ["hint1"],
    final_answer: null,
    mastery_recorded: false,
    ...overrides,
  };
}

beforeEach(() => {
  authFetchMock.mockImplementation(async (input: string, init?: RequestInit) => {
    const path = input.split("?")[0];
    if (init?.method === "POST" && /\/actions$/.test(path)) {
      return jsonResponse(session({ current_step: 0, available_actions: ["hint2"] }));
    }
    if (path === "/api/v1/deep-solve/sessions/ds-1") {
      return jsonResponse(session({ available_actions: ["hint1"] }));
    }
    if (path === "/api/v1/deep-solve/sessions") {
      return jsonResponse({ items: [{ id: "ds-1", problem_text: "مسئلهٔ حرکت", status: "active" }] });
    }
    return jsonResponse({ detail: `unhandled ${input}` }, 404);
  });
});

describe("DeepSolveWorkspace — server-driven stage progression", () => {
  it("renders only the actions the server lists and advances via the action endpoint", async () => {
    render(<DeepSolveWorkspace />);
    const historyButton = await screen.findByRole("button", { name: /مسئلهٔ حرکت/ });
    await userEvent.click(historyButton);
    expect(await screen.findByRole("button", { name: "راهنمای ۱" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "راهنمای ۲" })).toBeNull();
    expect(screen.queryByRole("button", { name: "نمایش گام فعلی" })).toBeNull();
    expect(screen.queryByRole("button", { name: "پاسخ کامل" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "راهنمای ۱" }));
    await waitFor(() => expect(authFetchMock).toHaveBeenCalledWith(
      "/api/v1/deep-solve/sessions/ds-1/actions",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ action: "hint1" }) }),
    ));
    // The next stage comes from the server response, not from any client logic.
    expect(await screen.findByRole("button", { name: "راهنمای ۲" })).toBeTruthy();
  });

  it("a completed session shows the final answer, its book source and re-practice CTAs", async () => {
    authFetchMock.mockImplementation(async (input: string) => {
      const path = input.split("?")[0];
      if (path === "/api/v1/deep-solve/sessions") {
        return jsonResponse({ items: [{ id: "ds-1", problem_text: "مسئلهٔ حرکت", status: "completed" }] });
      }
      if (path === "/api/v1/deep-solve/sessions/ds-1") {
        return jsonResponse(session({ status: "completed", available_actions: [], final_answer: "سرعت ۲۰ متر بر ثانیه" }));
      }
      return jsonResponse({ detail: `unhandled ${input}` }, 404);
    });
    render(<DeepSolveWorkspace />);
    await userEvent.click(await screen.findByRole("button", { name: /مسئلهٔ حرکت/ }));
    expect(await screen.findByText(/پاسخ نهایی:/)).toBeTruthy();
    expect(screen.getByText(/سرعت ۲۰ متر بر ثانیه/)).toBeTruthy();
    expect(screen.getByRole("link", { name: /منبع در کتاب/ }).getAttribute("href")).toBe("/study/5");
    expect(screen.getByRole("link", { name: /مسیر تسلط/ }).getAttribute("href")).toBe("/mastery");
    await userEvent.click(screen.getByRole("button", { name: /مسئلهٔ تازه/ }));
    await waitFor(() => expect(screen.queryByText(/پاسخ نهایی:/)).toBeNull());
  });

  it("does not render stage content the server withheld for pending steps", async () => {
    render(<DeepSolveWorkspace />);
    await userEvent.click(await screen.findByRole("button", { name: /مسئلهٔ حرکت/ }));
    await screen.findByText(/گام یک/);
    // Pending step is dimmed and carries no explanation/result text at all.
    expect(screen.getByText(/گام دو/)).toBeTruthy();
    expect(screen.queryByText(/نتیجه:/)).toBeNull();
  });
});
