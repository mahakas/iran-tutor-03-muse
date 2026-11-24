import { describe, expect, it } from "vitest";
import {
  buildNotebookBlockFromMessage,
  citationTextFromSources,
  pickContinueTarget,
  type ContinueInputs,
} from "@/lib/handoffs";
import type { ExamSummary, Source } from "@/lib/types";

function exam(overrides: Partial<ExamSummary> = {}): ExamSummary {
  return {
    id: "exam-1",
    title: "آزمون فصل ۲",
    book_id: 1,
    book_title: "فیزیک ۱",
    grade_number: 10,
    major_code: "riazi",
    exam_type: "final",
    status: "submitted",
    question_count: 5,
    time_limit_seconds: 900,
    expires_at: "2026-11-24T00:00:00Z",
    created_at: "2026-11-23T08:00:00Z",
    submitted_at: "2026-11-23T08:15:00Z",
    report_summary: null,
    ...overrides,
  };
}

const EMPTY: ContinueInputs = {
  activeExams: [],
  chatSessions: [],
  dueFlashcards: null,
  openMistakes: null,
  submittedExams: [],
};

describe("pickContinueTarget — only real activity, honest priority", () => {
  it("returns null for a fresh user with no history", () => {
    expect(pickContinueTarget(EMPTY)).toBeNull();
  });

  it("prefers an unfinished (active) exam so it can really be resumed", () => {
    const target = pickContinueTarget({
      ...EMPTY,
      activeExams: [exam({ id: "e-active", status: "active", title: "آزمون زنده" })],
      chatSessions: [{ id: "c-1", title: "گفت‌وگو", updated_at: "2026-11-23T09:00:00Z" }],
    });
    expect(target).toEqual({ kind: "exam", id: "e-active", title: "آزمون زنده", status: "active" });
  });

  it("falls back to the latest chat by updated_at", () => {
    const target = pickContinueTarget({
      ...EMPTY,
      chatSessions: [
        { id: "c-old", title: "قدیمی", updated_at: "2026-11-20T09:00:00Z" },
        { id: "c-new", title: "تازه", updated_at: "2026-11-23T09:00:00Z" },
      ],
    });
    expect(target).toEqual({ kind: "chat", id: "c-new", title: "تازه" });
  });

  it("uses due flashcard reviews (real SM-2 count) when no chat exists", () => {
    const target = pickContinueTarget({ ...EMPTY, dueFlashcards: 4 });
    expect(target).toEqual({ kind: "flashcards", dueCount: 4 });
  });

  it("offers unresolved mistakes before a finished exam's report card", () => {
    const target = pickContinueTarget({
      ...EMPTY,
      openMistakes: 3,
      submittedExams: [exam()],
    });
    expect(target).toEqual({ kind: "mistakes", openCount: 3 });
  });

  it("points at the most recent finished exam when that is all there is", () => {
    const target = pickContinueTarget({
      ...EMPTY,
      submittedExams: [
        exam({ id: "e-old", submitted_at: "2026-11-01T08:00:00Z" }),
        exam({ id: "e-new", submitted_at: "2026-11-22T08:00:00Z" }),
      ],
    });
    expect(target).toEqual({ kind: "exam", id: "e-new", title: "آزمون فصل ۲", status: "submitted" });
  });

  it("ignores fabricated zeros: explicit zero due cards is not an activity", () => {
    expect(pickContinueTarget({ ...EMPTY, dueFlashcards: 0, openMistakes: 0 })).toBeNull();
  });
});

describe("citationTextFromSources — provenance travels with the content", () => {
  it("composes book, chapter and printed page", () => {
    const text = citationTextFromSources(
      [{ book_title: "فیزیک ۱", chapter_title: "کار و انرژی", printed_page_number: 45 }],
      "فیزیک ۱"
    );
    expect(text).toBe("فیزیک ۱ — کار و انرژی — صفحهٔ ۴۵");
  });

  it("falls back to the chapter number when the title is missing", () => {
    const text = citationTextFromSources([{ book_title: "ریاضی ۲", chapter_number: 3 }], "ریاضی ۲");
    expect(text).toBe("ریاضی ۲ — فصل ۳");
  });

  it("uses the fallback title when there are no sources", () => {
    expect(citationTextFromSources(undefined, "علوم ۱")).toBe("علوم ۱");
  });
});

describe("buildNotebookBlockFromMessage — notebook handoff keeps the source", () => {
  it("builds a text_markdown block with allowed metadata keys only", () => {
    const block = buildNotebookBlockFromMessage(
      {
        content: "  تعریف کار: W = F · d  ",
        sources: [{ book_title: "فیزیک ۱", printed_page_number: 45 }],
      },
      "فیزیک ۱"
    );
    expect(block.block_type).toBe("text_markdown");
    expect(block.content).toBe("تعریف کار: W = F · d");
    expect(Object.keys(block.metadata).sort()).toEqual(["citation", "title"]);
    expect(block.metadata.citation).toContain("فیزیک ۱");
    expect(block.metadata.citation).toContain("صفحهٔ ۴۵");
  });
});

describe("buildNotebookBlockFromMessage — stable handoff identity (Phase 02-B)", () => {
  const SRC = {
    book_title: "فیزیک دهم",
    chapter_number: 2,
    chapter_title: "نیرو",
    printed_page_number: 14,
  } as unknown as Source;

  it("carries conversation/message ids so the backend can replay duplicates", () => {
    const block = buildNotebookBlockFromMessage(
      { content: "پاسخ معلم", sources: [SRC] },
      "فیزیک دهم",
      { conversationId: "conv-7", messageId: "msg-3" }
    );
    expect(block.metadata.conversation_id).toBe("conv-7");
    expect(block.metadata.message_id).toBe("msg-3");
  });

  it("omits the ids when the save has no conversation context", () => {
    const block = buildNotebookBlockFromMessage({ content: "x", sources: [] }, "کتاب");
    expect(block.metadata.conversation_id).toBeUndefined();
    expect(block.metadata.message_id).toBeUndefined();
  });

  it("never fabricates chapter/page for a sourceless answer (book title only)", () => {
    const block = buildNotebookBlockFromMessage({ content: "بدون منبع", sources: [] }, "فیزیک دهم");
    expect(block.metadata.citation).toBe("فیزیک دهم");
    expect(block.metadata.citation).not.toContain("فصل");
    expect(block.metadata.citation).not.toContain("صفحه");
  });

  it("keeps only the primary (first) real citation when several sources exist", () => {
    const second = {
      book_title: "کتاب دیگر",
      chapter_number: 9,
      chapter_title: "فصل دیگر",
      printed_page_number: 99,
    } as unknown as Source;
    const citation = citationTextFromSources([SRC, second], "فیزیک دهم");
    expect(citation).toContain("نیرو");
    expect(citation).not.toContain("فصل دیگر");
  });
});
