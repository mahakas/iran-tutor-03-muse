import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import MistakeBankWorkspace from "@/components/MistakeBankWorkspace";
import type { MistakeList } from "@/lib/phase5";

const authFetchMock = vi.hoisted(() => vi.fn());

vi.mock("@/components/AppProvider", () => ({
  useAppContext: () => ({ authFetch: (...args: unknown[]) => authFetchMock(...args) }),
}));

// The real picker performs curriculum fetches; for filter tests a stub with a
// controllable onChange is enough.
vi.mock("@/components/BookGradePicker", () => ({
  default: ({ onChange }: { onChange: (bookId: number | null) => void }) => (
    <button type="button" data-testid="book-picker" onClick={() => onChange(3)}>
      انتخاب کتاب
    </button>
  ),
}));

function jsonResponse(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
}

const LIST: MistakeList = {
  total: 2,
  counts: { unresolved: 1, practiced: 1, mastered: 0 },
  items: [
    {
      id: 11, exam_id: "exam-1", question_id: "q1", book_id: 3, chapter_number: 1,
      chapter_title: "فصل حرکت", printed_page_number: 10, topic_tag: "فصل 1",
      error_tag: "wrong", prompt: "سؤال بانک ۱", choices: { A: "الف", B: "ب" },
      status: "unresolved", correct_streak: 0, attempts: 0, flashcard_card_id: null,
    },
    {
      id: 12, exam_id: "exam-1", question_id: "q2", book_id: 3, chapter_number: 2,
      chapter_title: "فصل نیرو", printed_page_number: 14, topic_tag: "فصل 2",
      error_tag: "skipped", prompt: "سؤال بانک ۲", choices: { A: "الف", B: "ب" },
      status: "practiced", correct_streak: 1, attempts: 1, flashcard_card_id: 77,
    },
  ],
};

const PRACTICE = {
  items: [
    {
      id: 11, exam_id: "exam-1", question_id: "q1", book_id: 3, chapter_number: 1,
      chapter_title: "فصل حرکت", printed_page_number: 10, topic_tag: "فصل 1",
      error_tag: "wrong", prompt: "سؤال تمرین", choices: { A: "الف", B: "ب" },
      status: "unresolved", correct_streak: 0, attempts: 0, flashcard_card_id: null,
    },
  ],
};

beforeEach(() => {
  authFetchMock.mockImplementation(async (input: string, init?: RequestInit) => {
    const path = input.split("?")[0];
    if (input.startsWith("/api/v1/mistakes/practice-set")) return jsonResponse(PRACTICE);
    if (path === "/api/v1/mistakes") return jsonResponse(LIST);
    if (/\/api\/v1\/mistakes\/\d+\/answer$/.test(path)) {
      return jsonResponse({ correct: true, correct_option: "A", explanation: "توضیح", status: "practiced" });
    }
    if (/\/api\/v1\/mistakes\/\d+\/flashcard$/.test(path)) {
      return jsonResponse({ card_id: 99, created: true, item: LIST.items[0] });
    }
    return jsonResponse({ detail: `unhandled ${input}` }, 404);
  });
});

describe("MistakeBankWorkspace — redesign phase 05 integration", () => {
  it("shows scoped status counts and never renders the answer key in list mode", async () => {
    render(<MistakeBankWorkspace />);
    await waitFor(() => expect(authFetchMock).toHaveBeenCalledWith("/api/v1/mistakes"));
    expect(await screen.findByText(/حل‌نشده \(۱\)/)).toBeTruthy();
    expect(await screen.findByText(/در حال تمرین \(۱\)/)).toBeTruthy();
    expect(document.body.textContent).not.toContain("پاسخ صحیح:");
  });

  it("sends server-side chapter and error-tag filters and offers a reset", async () => {
    render(<MistakeBankWorkspace />);
    await screen.findByText(/سؤال بانک ۱/);
    await userEvent.click(screen.getByRole("button", { name: "بی‌پاسخ" }));
    await waitFor(() => expect(authFetchMock).toHaveBeenLastCalledWith("/api/v1/mistakes?error_tag=skipped"));
    await userEvent.selectOptions(screen.getByLabelText(/فصل/), "2");
    await waitFor(() => expect(authFetchMock).toHaveBeenLastCalledWith("/api/v1/mistakes?chapter_number=2&error_tag=skipped"));
    const reset = screen.getByRole("button", { name: "پاک‌کردن فیلترها" });
    await userEvent.click(reset);
    await waitFor(() => expect(authFetchMock).toHaveBeenLastCalledWith("/api/v1/mistakes"));
  });

  it("filters the mistake bank by the selected book via the curriculum picker", async () => {
    render(<MistakeBankWorkspace />);
    await screen.findByText(/سؤال بانک ۱/);
    await userEvent.click(screen.getByTestId("book-picker"));
    await waitFor(() => expect(authFetchMock).toHaveBeenLastCalledWith("/api/v1/mistakes?book_id=3"));
  });

  it("practice respects the active scope and posting an answer reports the result", async () => {
    render(<MistakeBankWorkspace />);
    await screen.findByText(/سؤال بانک ۱/);
    await userEvent.selectOptions(screen.getByLabelText(/فصل/), "1");
    await waitFor(() => expect(authFetchMock).toHaveBeenLastCalledWith("/api/v1/mistakes?chapter_number=1"));
    await userEvent.click(screen.getByRole("button", { name: /تمرین دوباره/ }));
    await waitFor(() => expect(authFetchMock).toHaveBeenCalledWith("/api/v1/mistakes/practice-set?chapter_number=1&limit=5"));
    const radios = (await screen.findAllByRole("radio", { name: /A\./ }))
      .filter((radio) => !(radio as HTMLInputElement).disabled);
    await userEvent.click(radios[0]);
    await userEvent.click(screen.getByRole("button", { name: "ثبت پاسخ" }));
    await waitFor(() => expect(authFetchMock).toHaveBeenCalledWith("/api/v1/mistakes/11/answer", expect.objectContaining({ method: "POST" })));
    // The same item renders in both the practice set and the list, so the
    // result block legitimately appears in both copies.
    expect((await screen.findAllByText("درست بود.")).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/توضیح/).length).toBeGreaterThan(0);
  });

  it("links every mistake to its book source and converted cards to the flashcards page", async () => {
    render(<MistakeBankWorkspace />);
    const sourceLinks = await screen.findAllByRole("link", { name: /منبع در کتاب/ });
    expect(sourceLinks.map((link) => link.getAttribute("href"))).toEqual(["/study/3", "/study/3"]);
    expect(screen.getByRole("link", { name: /مشاهدهٔ فلش‌کارت‌ها/ }).getAttribute("href")).toBe("/flashcards");
    await userEvent.click(screen.getByRole("button", { name: /ارسال به فلش‌کارت‌ها/ }));
    await waitFor(() => expect(authFetchMock).toHaveBeenCalledWith("/api/v1/mistakes/11/flashcard", expect.objectContaining({ method: "POST" })));
  });
});
