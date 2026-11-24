import { describe, expect, it } from "vitest";
import {
  mistakeFilterQuery,
  nextChapterStep,
  type MasteryChapter,
} from "@/lib/phase5";

describe("nextChapterStep — deterministic, explainable, server-data only", () => {
  const base: Pick<MasteryChapter, "status" | "score" | "threshold" | "evidence"> = {
    status: "in_progress",
    score: 0.4,
    threshold: 0.7,
    evidence: {
      exam: { correct: 1, total: 3 },
      flash: { correct: 2, total: 5 },
      solve: { correct: 1, total: 2 },
    },
  };

  it("locked and mastered chapters get no nudge", () => {
    expect(nextChapterStep({ ...base, status: "locked" })).toBeNull();
    expect(nextChapterStep({ ...base, status: "mastered", score: 0.9 })).toBeNull();
  });

  it("missing exam evidence suggests building a short exam", () => {
    const next = nextChapterStep({ ...base, evidence: { flash: { correct: 1, total: 2 } } });
    expect(next).toEqual({
      reason: "هنوز هیچ شواهد آزمونی برای این فصل ثبت نشده است",
      label: "آزمون کوتاه بساز",
      href: "/?action=new-exam",
    });
  });

  it("missing solve evidence suggests deep solve", () => {
    const next = nextChapterStep({ ...base, evidence: { exam: { correct: 1, total: 2 } } });
    expect(next?.href).toBe("/deep-solve");
    expect(next?.reason).toContain("حل گام‌به‌گام");
  });

  it("missing flashcard evidence suggests reviewing cards", () => {
    const next = nextChapterStep({ ...base, evidence: { exam: { correct: 1, total: 2 }, solve: { correct: 1, total: 1 } } });
    expect(next?.href).toBe("/flashcards");
    expect(next?.reason).toContain("فلش‌کارت");
  });

  it("all sources present but below threshold suggests mistake review", () => {
    const next = nextChapterStep(base);
    expect(next?.href).toBe("/mistakes");
    expect(next?.reason).toContain("زیر آستانه");
  });

  it("null score counts as below threshold", () => {
    const next = nextChapterStep({ ...base, score: null, status: "not_started" });
    expect(next?.href).toBe("/mistakes");
  });

  it("empty evidence object behaves like not started (exam first)", () => {
    const next = nextChapterStep({ ...base, evidence: null, status: "not_started" });
    expect(next?.href).toBe("/?action=new-exam");
  });
});

describe("mistakeFilterQuery — serializes only active filters", () => {
  it("returns an empty string when everything is unfiltered", () => {
    expect(mistakeFilterQuery({ status: "all", bookId: null, chapterNumber: null, errorTag: null })).toBe("");
  });

  it("serializes status plus scope filters in a stable order", () => {
    const query = mistakeFilterQuery({ status: "unresolved", bookId: 3, chapterNumber: 2, errorTag: "skipped" });
    expect(query).toBe("?status=unresolved&book_id=3&chapter_number=2&error_tag=skipped");
  });

  it("practice mode adds the limit parameter", () => {
    const query = mistakeFilterQuery({ status: "all", bookId: null, chapterNumber: 1, errorTag: null, practice: true });
    expect(query).toBe("?chapter_number=1&limit=5");
  });
});
