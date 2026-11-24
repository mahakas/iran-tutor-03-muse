/** Phase 5 shared types and helpers: immersive reader, mistake bank, mastery path, deep solve, admin views. */

export type ImmersivePage = {
  pdf_page_index: number;
  printed_page_number: number | null;
  chapter_number: number | null;
  chapter_title: string | null;
};

export type ImmersiveChapter = {
  chapter_number: number;
  chapter_title: string;
  page_start: number;
  page_end: number;
  printed_start: number | null;
  printed_end: number | null;
};

export type ImmersiveOverview = {
  id: number;
  title: string;
  grade_number: number | null;
  major_code: string;
  page_count: number;
  chapters: ImmersiveChapter[];
  pages: ImmersivePage[];
};

export type SourceFigure = {
  id: number;
  pdf_page_index: number;
  printed_page_number: number | null;
  chapter_number: number | null;
  figure_label: string | null;
  caption: string | null;
};

export type ImmersivePageDetail = ImmersivePage & {
  book_id: number;
  book_title: string;
  citation: string;
  markdown_content: string;
  figures: SourceFigure[];
};

export type MistakeStatus = "unresolved" | "practiced" | "mastered";

export type MistakeItem = {
  id: number;
  exam_id: string | null;
  question_id: string | null;
  book_id: number | null;
  chapter_number: number | null;
  chapter_title: string | null;
  printed_page_number: number | null;
  topic_tag: string | null;
  error_tag: string | null;
  prompt: string;
  choices: Record<string, string>;
  status: MistakeStatus;
  correct_streak: number;
  attempts: number;
  flashcard_card_id: number | null;
};

export type MistakeList = { total: number; counts: Record<string, number>; items: MistakeItem[] };

/** Error tags written by exam submission (wrong choice vs no answer). */
export type MistakeErrorTag = "wrong" | "skipped";

export const MISTAKE_ERROR_TAG_LABEL: Record<MistakeErrorTag, string> = {
  wrong: "پاسخ نادرست",
  skipped: "بی‌پاسخ",
};

/** Builds the mistake-bank query string from the active filters (empty string when unfiltered). */
export function mistakeFilterQuery(filters: {
  status: MistakeStatus | "all";
  bookId: number | null;
  chapterNumber: number | null;
  errorTag: MistakeErrorTag | null;
  practice?: boolean;
}): string {
  const params = new URLSearchParams();
  if (filters.status !== "all") params.set("status", filters.status);
  if (filters.bookId !== null) params.set("book_id", String(filters.bookId));
  if (filters.chapterNumber !== null) params.set("chapter_number", String(filters.chapterNumber));
  if (filters.errorTag !== null) params.set("error_tag", filters.errorTag);
  if (filters.practice) params.set("limit", "5");
  return params.size ? `?${params.toString()}` : "";
}

export type MasteryComponentEvidence = { correct: number; total: number };

export type MasteryChapter = ImmersiveChapter & {
  score: number | null;
  threshold: number;
  status: "locked" | "mastered" | "in_progress" | "not_started";
  locked_reason: string | null;
  override: "locked" | "open" | null;
  evidence: Record<string, MasteryComponentEvidence> | null;
};

/**
 * Deterministic, explainable next-step suggestion for one mastery chapter.
 * Pure function of server data (status, score, evidence counters); no AI and no
 * invented numbers. Returns null when no nudge is warranted (locked or mastered).
 */
export function nextChapterStep(
  chapter: Pick<MasteryChapter, "status" | "score" | "threshold" | "evidence">,
): { reason: string; label: string; href: string } | null {
  if (chapter.status === "locked" || chapter.status === "mastered") return null;
  const evidence = chapter.evidence ?? {};
  const total = (key: string) => evidence[key]?.total ?? 0;
  if (total("exam") === 0) {
    return {
      reason: "هنوز هیچ شواهد آزمونی برای این فصل ثبت نشده است",
      label: "آزمون کوتاه بساز",
      href: "/?action=new-exam",
    };
  }
  if (total("solve") === 0) {
    return {
      reason: "شواهد آزمون ثبت شده اما حل گام‌به‌گام برای این فصل خالی است",
      label: "حل گام‌به‌گام یک مسئله",
      href: "/deep-solve",
    };
  }
  if (total("flash") === 0) {
    return {
      reason: "شواهد آزمون و حل ثبت شده‌اند اما مرور فلش‌کارت برای این فصل خالی است",
      label: "مرور فلش‌کارت‌ها",
      href: "/flashcards",
    };
  }
  const below = chapter.score === null || chapter.score < chapter.threshold;
  if (below) {
    return {
      reason: "هر سه منبع شواهد فعال شده‌اند اما امتیاز فصل زیر آستانه است",
      label: "مرور اشتباهات ثبت‌شده",
      href: "/mistakes",
    };
  }
  return null;
}

export type MasteryTree = {
  book: { id: number; title: string };
  threshold: number;
  unlock_mode: "sequential" | "open";
  mastered_count: number;
  chapters: MasteryChapter[];
};

export type DeepSolveStep = {
  index: number;
  title: string;
  state: "done" | "current" | "pending";
  hint1?: string;
  hint2?: string;
  explanation?: string;
  result?: string;
};

export type DeepSolveSession = {
  id: string;
  problem_text: string;
  topic: string | null;
  subject: string | null;
  book_id: number | null;
  chapter_number: number | null;
  status: "active" | "completed";
  total_steps: number;
  current_step: number;
  steps: DeepSolveStep[];
  available_actions: string[];
  final_answer: string | null;
  mastery_recorded: boolean;
};

export type BookListItem = {
  id: number;
  title: string;
  grade_number: number;
  major_code: string;
  branch_code?: string | null;
  field_code?: string | null;
  academic_year_code?: string | null;
  edition_label?: string | null;
  print_year?: number | null;
  publisher?: string | null;
  status: string;
};

export function toPersianDigits(value: string | number): string {
  return String(value).replace(/[0-9]/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[Number(d)]);
}

export function toLatinDigits(value: string): string {
  return value.replace(/[۰-۹]/g, (d) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d)));
}

/**
 * Parses citations like «فصل ۲، صفحه ۴۲» (also «فصل 2، صفحه 42»).
 * Returns the chapter and printed page numbers, or null when the text is not a citation.
 */
export function parseCitation(text: string): { chapter: number; printedPage: number } | null {
  const normalized = toLatinDigits(text);
  const match = normalized.match(/فصل\s*(\d{1,2})\s*[،,]\s*صفحه\s*(\d{1,4})/);
  if (!match) return null;
  return { chapter: Number(match[1]), printedPage: Number(match[2]) };
}

/** Finds the PDF page index for a printed page (and optional chapter) inside a book overview. */
export function findPdfPageIndex(
  pages: ImmersivePage[],
  printedPage: number,
  chapter: number | null,
): number | null {
  const exact = pages.find(
    (page) =>
      page.printed_page_number === printedPage && (chapter === null || page.chapter_number === chapter),
  );
  if (exact) return exact.pdf_page_index;
  const anyChapter = pages.find((page) => page.printed_page_number === printedPage);
  return anyChapter ? anyChapter.pdf_page_index : null;
}

/** Splits an answer into text and citation segments so citations can be rendered as jump links. */
export function splitCitations(text: string): Array<{ kind: "text" | "cite"; value: string }> {
  const parts: Array<{ kind: "text" | "cite"; value: string }> = [];
  const pattern = /«([^»]{2,80})»/g;
  let last = 0;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) parts.push({ kind: "text", value: text.slice(last, match.index) });
    parts.push({ kind: "cite", value: match[1] });
    last = match.index + match[0].length;
  }
  if (last < text.length) parts.push({ kind: "text", value: text.slice(last) });
  return parts;
}

export function phase5ErrorMessage(payload: unknown, fallback: string): string {
  if (payload && typeof payload === "object" && "detail" in payload) {
    const detail = (payload as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
  }
  return fallback;
}

export const MISTAKE_STATUS_LABEL: Record<MistakeStatus, string> = {
  unresolved: "حل‌نشده",
  practiced: "در حال تمرین",
  mastered: "تسلط‌یافته",
};

export const MASTERY_STATUS_LABEL: Record<MasteryChapter["status"], string> = {
  locked: "قفل",
  mastered: "تسلط کامل",
  in_progress: "در حال یادگیری",
  not_started: "شروع‌نشده",
};

export type ObjectiveMasteryStatus =
  | "locked"
  | "mastered"
  | "developing"
  | "needs_support"
  | "submitted_for_review"
  | "not_started";

export const OBJECTIVE_MASTERY_STATUS_LABEL: Record<ObjectiveMasteryStatus, string> = {
  locked: "قفل؛ پیش‌نیاز تکمیل نشده",
  mastered: "تأییدشده و مسلط",
  developing: "در حال پیشرفت",
  needs_support: "نیازمند پشتیبانی",
  submitted_for_review: "ارسال‌شده برای بازبینی",
  not_started: "شروع‌نشده",
};


export type ObjectiveEvidenceStatus = ObjectiveMasteryStatus;

export type ObjectiveEvidenceItem = {
  id: number;
  source_type: string;
  score: number | null;
  qualitative_level: string | null;
  verification_status: "unverified" | "verified" | "rejected" | string;
  reviewed_at: string | null;
  review_note: string | null;
  rubric: Record<string, unknown>;
  feedback: string | null;
  observed_at: string | null;
};

export type ObjectiveMasteryItem = {
  id: number;
  code: string;
  title: string;
  description: string | null;
  competency_type: string | null;
  assessment_profile: "written" | "qualitative_descriptive" | "performance" | "mixed" | string;
  unit: { id: number; code: string; title: string; type: string };
  subject: { code: string; title: string };
  status: ObjectiveEvidenceStatus;
  score: number | null;
  qualitative_level: string | null;
  evidence_count: number;
  latest_evidence: {
    source_type: string;
    score: number | null;
    qualitative_level: string | null;
    verification_status: "unverified" | "verified" | "rejected" | string;
    review_note: string | null;
    reviewed_at: string | null;
    feedback: string | null;
    observed_at: string | null;
  } | null;
  evidence: ObjectiveEvidenceItem[];
  prerequisites: Array<{ code: string; title: string; status: ObjectiveEvidenceStatus }>;
};

export type ObjectiveMasteryTree = {
  book: { id: number; title: string };
  academic_year_code: string | null;
  threshold: number | null;
  mastered_count: number;
  objectives: ObjectiveMasteryItem[];
  message?: string;
};
