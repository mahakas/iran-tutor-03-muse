import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ExamRunner from "@/components/ExamRunner";
import type { Exam, ExamReport } from "@/lib/types";

function jsonResponse(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
}

const REPORT: ExamReport = {
  score: 66.67,
  scale: "percent",
  correct: 1,
  wrong: 1,
  unanswered: 0,
  total_questions: 2,
  by_question: [
    { id: "q1", correct: true, answer: "A", correct_option: "A", explanation: "درست", source: { book_title: "فیزیک دهم", chapter_title: "فصل 1", printed_page_number: 10, citation: "فصل ۱، صفحه ۱۰" } },
    { id: "q2", correct: false, answer: "B", correct_option: "C", explanation: "غلط", source: { book_title: "فیزیک دهم", chapter_title: "فصل 2", printed_page_number: 14 } },
  ],
} as unknown as ExamReport;

const EXAM: Exam = {
  id: "exam-1",
  title: "آزمون فصل ۱",
  book_id: 3,
  grade_number: 10,
  major_code: "math_physics",
  exam_type: "konkoor",
  time_limit_seconds: 600,
  expires_at: new Date(Date.now() + 10 * 60 * 1000).toISOString(),
  status: "active",
  questions: [
    { id: "q1", prompt: "سؤال اول", choices: { A: "الف", B: "ب", C: "پ", D: "ت" }, points: 1 },
    { id: "q2", prompt: "سؤال دوم", choices: { A: "الف", B: "ب", C: "پ", D: "ت" }, points: 1 },
  ],
} as unknown as Exam;

const fetchMock = vi.hoisted(() => vi.fn());

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ExamRunner — redesign phase 05", () => {
  it("keeps the answer key out of the running view and submits chosen answers", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ report_card: REPORT }));
    render(<ExamRunner exam={EXAM} onExit={() => {}} />);
    // The question text is visible; the key is not in the payload or the DOM.
    expect(await screen.findByText("سؤال اول")).toBeTruthy();
    expect(document.body.textContent).toContain("پاسخ‌ها تا پایان آزمون پنهان‌اند");
    expect(document.body.textContent).not.toContain("پاسخ درست: C");
    await userEvent.click(screen.getByRole("button", { name: /الف/ }));
    await userEvent.click(screen.getByRole("button", { name: /سؤال بعدی/ }));
    await userEvent.click(screen.getByRole("button", { name: /پ/ }));
    await userEvent.click(screen.getByRole("button", { name: /ثبت و دریافت کارنامه/ }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/exams/exam-1/submit");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ answers: { q1: "A", q2: "C" } });
    expect(await screen.findByText(/کارنامهٔ آزمون/)).toBeTruthy();
    expect(screen.getByText(/پاسخ درست از/)).toBeTruthy();
  });

  it("auto-submits an expired exam exactly once and never leaks answers before the report", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ report_card: REPORT }));
    const expired = { ...EXAM, expires_at: new Date(Date.now() - 1000).toISOString() };
    render(<ExamRunner exam={expired} onExit={() => {}} />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/exams/exam-1/submit");
    expect(JSON.parse(String(init.body))).toEqual({ answers: {} });
    expect(await screen.findByText(/کارنامهٔ آزمون/)).toBeTruthy();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1)); // no double submit
  });

  it("the report links mistakes, mastery and the book source, and can restart practice", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ report_card: REPORT }));
    const onExit = vi.fn();
    const onStartNewExam = vi.fn();
    render(<ExamRunner exam={EXAM} onExit={onExit} onStartNewExam={onStartNewExam} />);
    await userEvent.click(screen.getByRole("button", { name: /الف/ }));
    await userEvent.click(screen.getByRole("button", { name: /سؤال بعدی/ }));
    await userEvent.click(screen.getByRole("button", { name: /ثبت و دریافت کارنامه/ }));
    const mistakesLink = await screen.findByRole("link", { name: /مرور اشتباهات در بانک اشتباهات/ });
    expect(mistakesLink.getAttribute("href")).toBe("/mistakes");
    expect(screen.getByRole("link", { name: /منبع کتاب/ }).getAttribute("href")).toBe("/study/3");
    expect(screen.getByRole("link", { name: /شواهد تسلط/ }).getAttribute("href")).toBe("/mastery");
    await userEvent.click(screen.getByRole("button", { name: /تمرین دوباره/ }));
    expect(onStartNewExam).toHaveBeenCalledTimes(1);
    expect(onExit).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "بازگشت به کلاس" }));
    expect(onExit).toHaveBeenCalledTimes(1);
  });

  it("a perfect report hides the mistake-review CTA but keeps book and mastery links", async () => {
    const perfect = { ...REPORT, wrong: 0, unanswered: 0, correct: 2 } as ExamReport;
    fetchMock.mockResolvedValue(jsonResponse({ report_card: perfect }));
    render(<ExamRunner exam={EXAM} onExit={() => {}} onStartNewExam={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: /الف/ }));
    await userEvent.click(screen.getByRole("button", { name: /سؤال بعدی/ }));
    await userEvent.click(screen.getByRole("button", { name: /پ/ }));
    await userEvent.click(screen.getByRole("button", { name: /ثبت و دریافت کارنامه/ }));
    await screen.findByText(/کارنامهٔ آزمون/);
    expect(screen.queryByRole("link", { name: /مرور اشتباهات در بانک اشتباهات/ })).toBeNull();
    expect(screen.getByRole("link", { name: /منبع کتاب/ })).toBeTruthy();
    expect(screen.getByRole("link", { name: /شواهد تسلط/ })).toBeTruthy();
  });
});
