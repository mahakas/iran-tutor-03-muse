import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach } from "vitest";
import StudentHomeDashboard from "@/components/StudentHomeDashboard";
import type { ChatSessionSummary, ExamSummary } from "@/lib/types";
import type { StudentHomeData } from "@/lib/useStudentHomeData";

// The data hook is tested separately (useStudentHomeData.test.tsx); here it is
// mocked so each scenario can present real-shaped API data without network.
const hookState = vi.hoisted(() => ({
  value: {
    dueFlashcards: null,
    decks: null,
    notebooks: null,
    openMistakes: null,
    loading: false,
    errors: { due: false, decks: false, notebooks: false, mistakes: false },
  } as StudentHomeData,
}));
vi.mock("@/lib/useStudentHomeData", () => ({
  useStudentHomeData: () => hookState.value,
}));

function chat(overrides: Partial<ChatSessionSummary> = {}): ChatSessionSummary {
  return {
    id: "chat-1",
    title: "کار و انرژی در فیزیک",
    book_id: 3,
    book_title: "فیزیک ۱",
    grade_number: 10,
    major_code: "riazi",
    mode: "tutor",
    message_count: 6,
    created_at: "2026-11-22T08:00:00Z",
    updated_at: "2026-11-23T08:30:00Z",
    ...overrides,
  };
}

function exam(overrides: Partial<ExamSummary> = {}): ExamSummary {
  return {
    id: "exam-1",
    title: "آزمون فصل ۲",
    book_id: 3,
    book_title: "فیزیک ۱",
    grade_number: 10,
    major_code: "riazi",
    exam_type: "final",
    status: "submitted",
    question_count: 5,
    time_limit_seconds: 900,
    expires_at: "2026-11-24T00:00:00Z",
    created_at: "2026-11-22T08:00:00Z",
    submitted_at: "2026-11-22T08:15:00Z",
    report_summary: null,
    ...overrides,
  };
}

const BASE_CAPS = { quiz: true, flashcards: true, mistake_bank: true, learning_notebook: true, immersive_reader: true };
const CONTEXT = { gradeTitle: "پایهٔ ۱۰", majorTitle: "ریاضی‌فیزیک", bookTitle: "فیزیک ۱" };

type RenderOpts = {
  authenticated?: boolean;
  chats?: ChatSessionSummary[];
  exams?: ExamSummary[];
  data?: Partial<StudentHomeData>;
  caps?: Partial<typeof BASE_CAPS>;
  context?: Partial<typeof CONTEXT> & { bookId?: number | null };
};

function renderDashboard(opts: RenderOpts = {}) {
  hookState.value = {
    dueFlashcards: null,
    decks: null,
    notebooks: null,
    openMistakes: null,
    loading: false,
    errors: { due: false, decks: false, notebooks: false, mistakes: false },
    ...opts.data,
  };
  const onContinueChat = vi.fn();
  const onContinueExam = vi.fn();
  const onStart = vi.fn();
  const onRequireLogin = vi.fn();
  render(
    <StudentHomeDashboard
      lang="fa"
      isAuthenticated={opts.authenticated ?? true}
      context={{ ...CONTEXT, ...(opts.context ?? {}) }}
      capabilities={{ ...BASE_CAPS, ...(opts.caps ?? {}) }}
      chatSessions={opts.chats ?? []}
      exams={opts.exams ?? []}
      onContinueChat={onContinueChat}
      onContinueExam={onContinueExam}
      onStart={onStart}
      onRequireLogin={onRequireLogin}
    />
  );
  return { onContinueChat, onContinueExam, onStart, onRequireLogin };
}

beforeEach(() => {
  hookState.value = {
    dueFlashcards: null,
    decks: null,
    notebooks: null,
    openMistakes: null,
    loading: false,
    errors: { due: false, decks: false, notebooks: false, mistakes: false },
  };
});

describe("StudentHomeDashboard", () => {
  it("fresh user with no history: honest empty state pointing at the real curriculum picker", async () => {
    const user = userEvent.setup();
    const handlers = renderDashboard();
    expect(screen.getByText("ادامه بده")).toBeInTheDocument();
    expect(
      screen.getByText("هنوز فعالیت ثبت‌شده‌ای نداری. کتابت را انتخاب کن و اولین درس را شروع کن.")
    ).toBeInTheDocument();
    await user.click(screen.getByText("انتخاب کتاب"));
    expect(handlers.onStart).toHaveBeenCalledTimes(1);
    // no fabricated numbers anywhere
    expect(screen.queryByText(/٪/)).not.toBeInTheDocument();
    expect(screen.queryByText(/streak|زنجیره/i)).not.toBeInTheDocument();
  });

  it("anonymous visitor: sign-in card instead of personalized data", async () => {
    const user = userEvent.setup();
    const handlers = renderDashboard({ authenticated: false });
    expect(screen.getByText("برای دیدن برنامهٔ امروز وارد شو.")).toBeInTheDocument();
    await user.click(screen.getByText("ورود به درسیار"));
    expect(handlers.onRequireLogin).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("ذخیره‌شده‌ها")).not.toBeInTheDocument();
  });

  it("user with recent study: continue card resumes the latest chat for that user", async () => {
    const user = userEvent.setup();
    const handlers = renderDashboard({ chats: [chat()] });
    expect(screen.getByText("آخرین گفت‌وگو: «کار و انرژی در فیزیک»")).toBeInTheDocument();
    await user.click(screen.getByText("ادامهٔ گفت‌وگو"));
    expect(handlers.onContinueChat).toHaveBeenCalledWith("chat-1");
    expect(screen.getByText("فعالیت اخیر")).toBeInTheDocument();
  });

  it("user with an unfinished exam: offers a real resume action", async () => {
    const user = userEvent.setup();
    const handlers = renderDashboard({ exams: [exam({ status: "active", title: "آزمون زندهٔ فصل ۳" })] });
    expect(screen.getByText("آزمون نیمه‌تمام: «آزمون زندهٔ فصل ۳»")).toBeInTheDocument();
    await user.click(screen.getByText("ادامهٔ آزمون"));
    expect(handlers.onContinueExam).toHaveBeenCalledWith("exam-1");
  });

  it("user with due SM-2 reviews: today's plan shows the real count in Persian digits", () => {
    renderDashboard({
      data: {
        dueFlashcards: 7,
        decks: [{ id: 1, title: "کارت‌های کار و انرژی", due: 7, total: 20 }],
        openMistakes: 2,
      },
    });
    // with no chat/exam history the continue card itself becomes the review
    expect(screen.getByText("۷ فلش‌کارت برای مرور سررسیده است.")).toBeInTheDocument();
    expect(screen.getByText("۷ مرور فلش‌کارت سررسید")).toBeInTheDocument();
    expect(screen.getByText("۲ اشتباه حل‌نشده")).toBeInTheDocument();
    const deckLink = screen.getByText("کارت‌های کار و انرژی");
    expect(deckLink.closest("a")).toHaveAttribute("href", "/flashcards");
    expect(screen.getByText("۷ سررسید")).toBeInTheDocument();
  });

  it("failed data source: shows an honest unavailability note, never a guess", () => {
    renderDashboard({ chats: [chat()], data: { errors: { due: true, decks: false, notebooks: false, mistakes: true } } });
    expect(screen.getByText("دادهٔ مرورها در دسترس نیست.")).toBeInTheDocument();
    expect(screen.getByText("دادهٔ اشتباهات در دسترس نیست.")).toBeInTheDocument();
    expect(screen.queryByText(/مرور فلش‌کارت سررسید/)).not.toBeInTheDocument();
  });

  it("saved notebooks link to the real notebook workspace", () => {
    renderDashboard({ data: { notebooks: [{ id: 5, title: "دفترچهٔ فیزیک ۱", book_id: 3, block_count: 4 }] } });
    const link = screen.getByText("دفترچهٔ فیزیک ۱");
    expect(link.closest("a")).toHaveAttribute("href", "/notebook");
    expect(screen.getByText("۴ بلوک")).toBeInTheDocument();
  });

  it("shows the active learning context line", () => {
    renderDashboard({ chats: [chat()] });
    expect(screen.getByText("پایهٔ ۱۰ · ریاضی‌فیزیک · فیزیک ۱")).toBeInTheDocument();
  });

  it("with a selected book and immersive reader: study link points at /study/<id>", () => {
    renderDashboard({ context: { bookId: 3 } });
    const links = screen.getAllByText("مطالعهٔ کتاب");
    expect(links.length).toBeGreaterThan(0);
    expect(links[0].closest("a")).toHaveAttribute("href", "/study/3");
  });

  it("without a selected book: no study link is rendered", () => {
    renderDashboard();
    expect(screen.queryByText("مطالعهٔ کتاب")).not.toBeInTheDocument();
  });

  it("without the immersive reader capability: no study link is rendered", () => {
    renderDashboard({ context: { bookId: 3 }, caps: { immersive_reader: false } });
    expect(screen.queryByText("مطالعهٔ کتاب")).not.toBeInTheDocument();
  });
});
